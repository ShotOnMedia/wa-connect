import json
import mimetypes
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.core.config import settings
from app.flow_channel_models import TelegramFlowSession
from app.flow_models import FlowNode, FlowNodeType, FlowSession
from app.models import ContactFieldDefinition, ContactFieldType, ContactFieldValue
from app.services.telegram import TelegramError, download_file, get_file
from app.telegram_models import TelegramContactFieldValue

MAX_IMAGE_BYTES = 25 * 1024 * 1024


def _public_base_url() -> str:
    configured=str(settings.public_base_url or "").strip().rstrip("/")
    if configured:return configured
    for origin in settings.cors_origins:
        value=str(origin or "").strip().rstrip("/")
        if value.startswith("https://"):return value
    return ""

def _normalise_image_type(content_type:str|None,file_path:str|None=None)->str:
    mime=str(content_type or "").split(";",1)[0].strip().lower()
    if not mime or mime=="application/octet-stream":
        guessed,_=mimetypes.guess_type(str(file_path or ""));mime=str(guessed or "image/jpeg").lower()
    return mime

def _extension(content_type:str|None,fallback:str=".jpg")->str:
    mime=str(content_type or "").split(";",1)[0].strip().lower();known={"image/jpeg":".jpg","image/png":".png","image/webp":".webp","image/gif":".gif","image/heic":".heic","image/heif":".heif"};return known.get(mime) or mimetypes.guess_extension(mime) or fallback

def _store_image(content:bytes,content_type:str|None)->str:
    if not content:raise RuntimeError("Incoming image download returned an empty file")
    if len(content)>MAX_IMAGE_BYTES:raise RuntimeError("Incoming image is larger than the 25 MB storage limit")
    mime=str(content_type or "").split(";",1)[0].strip().lower()
    if mime and not mime.startswith("image/"):raise RuntimeError(f"Incoming media is not an image ({mime})")
    root=Path(settings.inbound_media_dir);root.mkdir(parents=True,exist_ok=True);filename=f"{uuid4().hex}{_extension(mime)}";(root/filename).write_bytes(content);path=f"{settings.api_prefix}/inbound-media/{filename}";base=_public_base_url();return f"{base}{path}" if base else path

def _image_field(db:Session,workspace_id:int,field_id):
    if not field_id:return None
    source=db.get(ContactFieldDefinition,int(field_id))
    if not source or not source.active or source.field_type!=ContactFieldType.IMAGE:return None
    if source.workspace_id==workspace_id:return source
    return db.scalar(select(ContactFieldDefinition).where(ContactFieldDefinition.workspace_id==workspace_id,ContactFieldDefinition.key==source.key,ContactFieldDefinition.active.is_(True),ContactFieldDefinition.field_type==ContactFieldType.IMAGE))

def _waiting_question(db:Session,conversation_id:int,channel:str):
    session_model=TelegramFlowSession if channel=="telegram" else FlowSession;session=db.scalar(select(session_model).where(session_model.conversation_id==conversation_id))
    if not session or str(getattr(session.status,"value",session.status))!="waiting" or session.waiting_for!="reply" or not session.current_node_id:return None,None
    node=db.get(FlowNode,session.current_node_id)
    if not node or str(getattr(node.node_type,"value",node.node_type))!=FlowNodeType.QUESTION.value:return None,None
    try:cfg=json.loads(node.config_json or "{}")
    except (TypeError,json.JSONDecodeError):cfg={}
    return node,cfg

def _save_url(db:Session,conversation,field,url:str,channel:str):
    model=TelegramContactFieldValue if channel=="telegram" else ContactFieldValue;row=db.scalar(select(model).where(model.contact_id==conversation.contact_id,model.field_id==field.id))
    if row:row.value_text=url;row.updated_at=datetime.utcnow()
    else:db.add(model(contact_id=conversation.contact_id,field_id=field.id,value_text=url))
    db.flush()

async def capture_image_field_value(db:Session,conversation,inbound,field_id,channel:str)->tuple[str,int]|None:
    field=_image_field(db,conversation.workspace_id,field_id)
    if not field:return None
    channel=str(channel or "").lower()
    try:payload=json.loads(inbound.payload_json or "{}")
    except (TypeError,json.JSONDecodeError):payload={}
    if channel=="telegram":
        if str(inbound.message_type or "").lower()!="photo":raise RuntimeError("Image custom fields can only capture an incoming Telegram photo")
        message=payload.get("message") or {};photos=message.get("photo") or [];item=photos[-1] if photos else None;file_id=(item or {}).get("file_id")
        if not file_id:raise RuntimeError("Telegram photo does not contain a retrievable file id")
        try:
            info=await get_file(conversation.bot.access_token,file_id);file_path=(info or {}).get("file_path")
            if not file_path:raise TelegramError("Telegram did not return a file path")
            content,content_type=await download_file(conversation.bot.access_token,file_path)
        except TelegramError as exc:raise RuntimeError(f"Could not store incoming Telegram image: {exc}") from exc
        return _store_image(content,_normalise_image_type(content_type,file_path)),field.id
    if channel=="whatsapp":
        if str(inbound.message_type or "").lower()!="image":raise RuntimeError("Image custom fields can only capture an incoming WhatsApp image")
        image=payload.get("image") or {};media_id=image.get("id")
        if not media_id:raise RuntimeError("WhatsApp image does not contain a retrievable media id")
        phone=conversation.phone_number
        if not phone.access_token:raise RuntimeError("WhatsApp phone number has no access token")
        headers={"Authorization":f"Bearer {phone.access_token}"};meta_url=f"https://graph.facebook.com/{settings.meta_graph_api_version}/{media_id}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            meta=await client.get(meta_url,headers=headers)
            if meta.is_error:raise RuntimeError(f"Could not retrieve WhatsApp image metadata: HTTP {meta.status_code}")
            download_url=(meta.json() or {}).get("url")
            if not download_url:raise RuntimeError("Meta did not return a WhatsApp media download URL")
            response=await client.get(download_url,headers=headers)
            if response.is_error:raise RuntimeError(f"Could not download incoming WhatsApp image: HTTP {response.status_code}")
        return _store_image(response.content,response.headers.get("content-type") or image.get("mime_type") or "image/jpeg"),field.id
    raise RuntimeError(f"Unsupported image capture channel: {channel}")

async def prepare_waiting_image_capture(db:Session,conversation,inbound,channel:str):
    _,cfg=_waiting_question(db,conversation.id,channel)
    if not cfg:return None
    field_id=cfg.get("capture_field_id") or cfg.get("save_reply_field_id") or cfg.get("field_id");captured=await capture_image_field_value(db,conversation,inbound,field_id,channel)
    if not captured:return None
    url,target_field_id=captured;_save_url(db,conversation,_image_field(db,conversation.workspace_id,target_field_id),url,channel);capture={"url":url,"field_id":target_field_id,"body":inbound.body,"payload_json":inbound.payload_json}
    if channel=="telegram":
        # Keep the persisted Live Chat message as Telegram media metadata, but
        # expose the durable stored URL to the flow runtime for this request.
        setattr(inbound,"_captured_image_url",url);set_committed_value(inbound,"body",url)
    else:
        try:payload=json.loads(inbound.payload_json or "{}")
        except (TypeError,json.JSONDecodeError):payload={}
        image=payload.get("image") or {};image["id"]=url;payload["image"]=image;set_committed_value(inbound,"payload_json",json.dumps(payload,ensure_ascii=False))
    return capture

def restore_captured_image_field(db:Session,conversation,inbound,capture,channel:str):
    if not capture:return
    field=_image_field(db,conversation.workspace_id,capture.get("field_id"))
    if field:_save_url(db,conversation,field,capture["url"],channel)
    if hasattr(inbound,"_captured_image_url"):delattr(inbound,"_captured_image_url")
    set_committed_value(inbound,"body",capture.get("body"));set_committed_value(inbound,"payload_json",capture.get("payload_json"))
