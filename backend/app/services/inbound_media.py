import json,mimetypes
from datetime import datetime
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.flow_channel_models import TelegramFlowSession
from app.flow_models import FlowNode,FlowNodeType,FlowSession
from app.models import ContactFieldDefinition,ContactFieldType,ContactFieldValue
from app.services.telegram import TelegramError,download_file,get_file
from app.telegram_models import TelegramContactFieldValue
from app.services.media_storage import store_media

TELEGRAM_MEDIA={"photo","video","voice","audio","document","sticker"}
WHATSAPP_MEDIA={"image","video","audio","document","sticker"}

def _normalise_type(content_type,file_path=None,fallback="application/octet-stream"):
    mime=str(content_type or "").split(";",1)[0].strip().lower()
    if not mime or mime=="application/octet-stream":mime=str(mimetypes.guess_type(str(file_path or ""))[0] or fallback).lower()
    return mime

def _store_image(db,content,content_type):
    mime=str(content_type or "").split(";",1)[0].strip().lower()
    if mime and not mime.startswith("image/"):raise RuntimeError(f"Incoming media is not an image ({mime})")
    return store_media(db,content,mime or "image/jpeg").url

def _image_field(db,workspace_id,field_id):
    if not field_id:return None
    source=db.get(ContactFieldDefinition,int(field_id))
    if not source or not source.active or source.field_type!=ContactFieldType.IMAGE:return None
    if source.workspace_id==workspace_id:return source
    return db.scalar(select(ContactFieldDefinition).where(ContactFieldDefinition.workspace_id==workspace_id,ContactFieldDefinition.key==source.key,ContactFieldDefinition.active.is_(True),ContactFieldDefinition.field_type==ContactFieldType.IMAGE))
def _waiting_question(db,conversation_id,channel):
    session_model=TelegramFlowSession if channel=="telegram" else FlowSession;session=db.scalar(select(session_model).where(session_model.conversation_id==conversation_id))
    if not session or str(getattr(session.status,"value",session.status))!="waiting" or session.waiting_for!="reply" or not session.current_node_id:return None,None
    node=db.get(FlowNode,session.current_node_id)
    if not node or str(getattr(node.node_type,"value",node.node_type))!=FlowNodeType.QUESTION.value:return None,None
    try:cfg=json.loads(node.config_json or "{}")
    except (TypeError,json.JSONDecodeError):cfg={}
    return node,cfg
def _save_url(db,conversation,field,url,channel):
    model=TelegramContactFieldValue if channel=="telegram" else ContactFieldValue;row=db.scalar(select(model).where(model.contact_id==conversation.contact_id,model.field_id==field.id))
    if row:row.value_text=url;row.updated_at=datetime.utcnow()
    else:db.add(model(contact_id=conversation.contact_id,field_id=field.id,value_text=url))
    db.flush()

def _telegram_item(message,message_type):
    if message_type=="photo":
        photos=message.get("photo") or [];return photos[-1] if photos else None
    return message.get(message_type)

async def persist_inbound_chat_media(db,conversation,inbound,channel):
    """Download ordinary inbound chat media once and replace provider metadata with a durable WA Connect URL."""
    channel=str(channel or "").lower();kind=str(inbound.message_type or "").lower()
    try:payload=json.loads(inbound.payload_json or "{}")
    except (TypeError,json.JSONDecodeError):payload={}
    if channel=="telegram":
        if kind not in TELEGRAM_MEDIA:return None
        message=payload.get("message") or {};item=_telegram_item(message,kind)
        if not isinstance(item,dict) or not item.get("file_id"):return None
        try:
            info=await get_file(conversation.bot.access_token,item["file_id"]);file_path=(info or {}).get("file_path")
            if not file_path:raise TelegramError("Telegram did not return a file path")
            content,content_type=await download_file(conversation.bot.access_token,file_path)
        except TelegramError as exc:raise RuntimeError(f"Could not persist incoming Telegram {kind}: {exc}") from exc
        mime=_normalise_type(item.get("mime_type") or content_type,file_path,"image/jpeg" if kind in {"photo","sticker"} else "application/octet-stream")
        stored=store_media(db,content,mime);item["wa_connect_url"]=stored.url;item["stored_provider"]=stored.provider;item["stored_key"]=stored.key
        if kind=="photo":
            photos=message.get("photo") or []
            if photos:photos[-1]=item
        else:message[kind]=item
        payload["message"]=message;inbound.payload_json=json.dumps(payload,ensure_ascii=False);db.flush();return stored.url
    if channel=="whatsapp":
        if kind not in WHATSAPP_MEDIA:return None
        item=payload.get(kind) or {};media_id=item.get("id")
        if not media_id:return None
        phone=conversation.phone_number
        if not phone.access_token:raise RuntimeError("WhatsApp phone number has no access token")
        headers={"Authorization":f"Bearer {phone.access_token}"};meta_url=f"https://graph.facebook.com/{settings.meta_graph_api_version}/{media_id}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            meta=await client.get(meta_url,headers=headers)
            if meta.is_error:raise RuntimeError(f"Could not retrieve WhatsApp {kind} metadata: HTTP {meta.status_code}")
            meta_data=meta.json() or {};download_url=meta_data.get("url")
            if not download_url:raise RuntimeError("Meta did not return a WhatsApp media download URL")
            response=await client.get(download_url,headers=headers)
            if response.is_error:raise RuntimeError(f"Could not download incoming WhatsApp {kind}: HTTP {response.status_code}")
        mime=_normalise_type(response.headers.get("content-type") or item.get("mime_type") or meta_data.get("mime_type"),None,"image/jpeg" if kind in {"image","sticker"} else "application/octet-stream")
        stored=store_media(db,response.content,mime);item["wa_connect_url"]=stored.url;item["stored_provider"]=stored.provider;item["stored_key"]=stored.key;payload[kind]=item
        inbound.payload_json=json.dumps(payload,ensure_ascii=False);db.flush();return stored.url
    return None

async def capture_image_field_value(db,conversation,inbound,field_id,channel):
    field=_image_field(db,conversation.workspace_id,field_id)
    if not field:return None
    channel=str(channel or "").lower()
    try:payload=json.loads(inbound.payload_json or "{}")
    except (TypeError,json.JSONDecodeError):payload={}
    if channel=="telegram":
        if str(inbound.message_type or "").lower()!="photo":raise RuntimeError("Image custom fields can only capture an incoming Telegram photo")
        message=payload.get("message") or {};photos=message.get("photo") or [];item=photos[-1] if photos else None
        if isinstance(item,dict) and item.get("wa_connect_url"):return item["wa_connect_url"],field.id
        file_id=(item or {}).get("file_id")
        if not file_id:raise RuntimeError("Telegram photo does not contain a retrievable file id")
        try:
            info=await get_file(conversation.bot.access_token,file_id);file_path=(info or {}).get("file_path")
            if not file_path:raise TelegramError("Telegram did not return a file path")
            content,content_type=await download_file(conversation.bot.access_token,file_path)
        except TelegramError as exc:raise RuntimeError(f"Could not store incoming Telegram image: {exc}") from exc
        return _store_image(db,content,_normalise_type(content_type,file_path,"image/jpeg")),field.id
    if channel=="whatsapp":
        if str(inbound.message_type or "").lower()!="image":raise RuntimeError("Image custom fields can only capture an incoming WhatsApp image")
        image=payload.get("image") or {}
        if image.get("wa_connect_url"):return image["wa_connect_url"],field.id
        media_id=image.get("id")
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
        return _store_image(db,response.content,response.headers.get("content-type") or image.get("mime_type") or "image/jpeg"),field.id
    raise RuntimeError(f"Unsupported image capture channel: {channel}")
async def prepare_waiting_image_capture(db,conversation,inbound,channel):
    _,cfg=_waiting_question(db,conversation.id,channel)
    if not cfg:return None
    channel=str(channel or "").lower();actual=str(inbound.message_type or "").lower()
    if channel=="telegram" and actual!="photo":return None
    if channel=="whatsapp" and actual!="image":return None
    field_id=cfg.get("capture_field_id") or cfg.get("save_reply_field_id") or cfg.get("field_id");captured=await capture_image_field_value(db,conversation,inbound,field_id,channel)
    if not captured:return None
    url,target_field_id=captured;_save_url(db,conversation,_image_field(db,conversation.workspace_id,target_field_id),url,channel);capture={"url":url,"field_id":target_field_id,"body":inbound.body,"payload_json":inbound.payload_json}
    if channel=="telegram":inbound._captured_image_url=url;inbound.body=url
    else:
        image=payload_image=json.loads(inbound.payload_json or "{}").get("image") or {};image["id"]=url;payload=json.loads(inbound.payload_json or "{}");payload["image"]=image;inbound.payload_json=json.dumps(payload,ensure_ascii=False)
    return capture
def restore_captured_image_field(db,conversation,inbound,capture,channel):
    if not capture:return
    field=_image_field(db,conversation.workspace_id,capture.get("field_id"))
    if field:_save_url(db,conversation,field,capture["url"],channel)
    if hasattr(inbound,"_captured_image_url"):delattr(inbound,"_captured_image_url")
    inbound.body=capture.get("body");inbound.payload_json=capture.get("payload_json");db.flush()
