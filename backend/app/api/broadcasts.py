import json
import re
from datetime import datetime, UTC
from fastapi import APIRouter,Depends,HTTPException,Response
from pydantic import BaseModel,Field
from sqlalchemy import func,select
from sqlalchemy.orm import Session
from app.broadcast_models import Broadcast,BroadcastRecipient
from app.core.database import get_db
from app.core.security import require_manager
from app.models import Workspace,WhatsAppPhoneNumber,WhatsAppAccount,Contact,Conversation,ContactFieldValue
from app.telegram_models import TelegramBot,TelegramContact,TelegramConversation,TelegramContactFieldValue
from app.models import ContactFieldDefinition
from app.services.telegram import TelegramError,send_text,send_media
from app.services.whatsapp import WhatsAppError,send_text_message,send_media_message,list_message_templates,send_template_message

router=APIRouter(prefix="/broadcasts",tags=["Broadcasts"],dependencies=[Depends(require_manager)])
def now():return datetime.now(UTC).replace(tzinfo=None)
def utc_naive(value):
    if value is None:return None
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value
class AudienceRule(BaseModel):field:str;operator:str="equals";value:str=""
class AudienceFilter(BaseModel):logic:str="and";rules:list[AudienceRule]=Field(default_factory=list)
class BroadcastIn(BaseModel):
    name:str=Field(min_length=1,max_length=150);channel:str="telegram";channel_account_id:int;message_text:str=Field(min_length=1,max_length=4096);message_mode:str="freeform";provider_template:dict|None=None;audience_type:str="all";contact_ids:list[int]=Field(default_factory=list);audience_filter:AudienceFilter|None=None;audience_segment_id:int|None=None;scheduled_at:datetime|None=None;parse_mode:str="HTML";media_url:str|None=None;media_type:str|None=None;stagger_seconds:float=Field(default=0.05,ge=0.05,le=60)
class AudiencePreviewIn(BaseModel):bot_id:int;audience_filter:AudienceFilter
class WhatsAppAudiencePreviewIn(BaseModel):phone_number_id:int;audience_filter:AudienceFilter;message_mode:str="freeform"
class TestIn(BaseModel):contact_id:int
def workspace(db, bot_id=None):
    # Telegram bots are explicitly attached to a workspace.  When a bot is
    # supplied, use that workspace instead of guessing from the first active
    # workspace (multi-workspace installs can have more than one active row).
    if bot_id is not None:
        wid=db.scalar(select(TelegramBot.workspace_id).where(TelegramBot.id==bot_id))
        if wid is None:raise HTTPException(404,"Telegram bot not found")
        return wid
    wid=db.scalar(select(Workspace.id).where(Workspace.active.is_(True)).order_by(Workspace.id))
    if wid is None:raise HTTPException(400,"No active workspace")
    return wid
def out(b):
    return {"id":b.id,"name":b.name,"channel":b.channel,"channel_account_id":b.channel_account_id,"message_text":b.message_text,"message_mode":b.message_mode,"provider_template":json.loads(b.provider_template_json) if b.provider_template_json else None,"parse_mode":b.parse_mode,"media_url":b.media_url,"media_type":b.media_type,"stagger_seconds":b.stagger_seconds,"audience_type":b.audience_type,"audience_filter":json.loads(b.audience_filter_json) if b.audience_filter_json else None,"audience_segment_id":b.audience_segment_id,"status":b.status,"scheduled_at":b.scheduled_at,"started_at":b.started_at,"completed_at":b.completed_at,"total_recipients":b.total_recipients,"sent_count":b.sent_count,"failed_count":b.failed_count,"created_at":b.created_at,"updated_at":b.updated_at}
def render(text,contact,fields):
    values={"name":" ".join(x for x in [contact.first_name,contact.last_name] if x).strip() or contact.username or str(contact.telegram_user_id),"first_name":contact.first_name or "","last_name":contact.last_name or "","username":contact.username or "","subscriber_id":str(contact.telegram_user_id)}
    values.update(fields)
    return re.sub(r"%([a-zA-Z0-9_.-]+)%",lambda m:str(values.get(m.group(1),m.group(0))),text)
def _system_values(contact):
    return {"name":" ".join(x for x in [contact.first_name,contact.last_name] if x).strip() or contact.username or str(contact.telegram_user_id),"first_name":contact.first_name or "","last_name":contact.last_name or "","username":contact.username or "","subscriber_id":str(contact.telegram_user_id),"language_code":contact.language_code or ""}
def _matches(value,operator,wanted):
    value=str(value or "");wanted=str(wanted or "");a=value.casefold();b=wanted.casefold()
    if operator=="equals":return a==b
    if operator=="not_equals":return a!=b
    if operator=="contains":return b in a
    if operator=="not_contains":return b not in a
    if operator=="starts_with":return a.startswith(b)
    if operator=="ends_with":return a.endswith(b)
    if operator=="is_empty":return not value.strip()
    if operator=="is_not_empty":return bool(value.strip())
    raise HTTPException(400,f"Unsupported audience filter operator: {operator}")
def filter_contacts(db,rows,spec):
    if not spec or not spec.rules:return rows
    logic=spec.logic.lower()
    if logic not in ("and","or"):raise HTTPException(400,"Filter logic must be and or or")
    fv=field_values(db,[c.id for c,_ in rows]);out=[]
    for contact,conv in rows:
        values=_system_values(contact);values.update(fv.get(contact.id,{}))
        checks=[_matches(values.get(rule.field,""),rule.operator,rule.value) for rule in spec.rules]
        if (all(checks) if logic=="and" else any(checks)):out.append((contact,conv))
    return out
def audience(db,wid,bot_id,kind,ids,spec=None):
    q=select(TelegramContact,TelegramConversation).join(TelegramConversation,TelegramConversation.contact_id==TelegramContact.id).where(TelegramContact.workspace_id==wid,TelegramConversation.telegram_bot_id==bot_id,TelegramConversation.chat_type=="private")
    if kind=="selected":
        if not ids:return []
        q=q.where(TelegramContact.id.in_(ids))
    elif kind not in ("all","filtered"):raise HTTPException(400,"audience_type must be all, selected or filtered")
    rows=db.execute(q.order_by(TelegramContact.id)).all()
    return filter_contacts(db,rows,spec) if kind=="filtered" else rows
def whatsapp_workspace(db,phone_id):
    wid=db.scalar(select(WhatsAppAccount.workspace_id).join(WhatsAppPhoneNumber,WhatsAppPhoneNumber.whatsapp_account_id==WhatsAppAccount.id).where(WhatsAppPhoneNumber.id==phone_id))
    if wid is None:raise HTTPException(404,"WhatsApp connection not found")
    return wid

def whatsapp_field_values(db,contact_ids):
    if not contact_ids:return {}
    rows=db.execute(select(ContactFieldValue.contact_id,ContactFieldDefinition.key,ContactFieldValue.value_text).join(ContactFieldDefinition,ContactFieldDefinition.id==ContactFieldValue.field_id).where(ContactFieldValue.contact_id.in_(contact_ids))).all();result={}
    for cid,key,value in rows:result.setdefault(cid,{})[key]=value or ""
    return result

def whatsapp_system_values(contact):return {"name":contact.name or contact.wa_id,"phone":contact.wa_id,"wa_id":contact.wa_id}
def whatsapp_audience(db,wid,phone_id,kind,ids,spec=None,require_open_window=True):
    q=select(Contact,Conversation).join(Conversation,Conversation.contact_id==Contact.id).where(Contact.workspace_id==wid,Conversation.phone_number_id==phone_id,Contact.archived_at.is_(None),Contact.blocked_at.is_(None))
    if require_open_window:q=q.where(Conversation.service_window_expires_at.is_not(None),Conversation.service_window_expires_at>now())
    if kind=="selected":
        if not ids:return []
        q=q.where(Contact.id.in_(ids))
    elif kind not in ("all","filtered"):raise HTTPException(400,"audience_type must be all, selected or filtered")
    rows=db.execute(q.order_by(Contact.id)).all()
    if kind!="filtered" or not spec or not spec.rules:return rows
    fv=whatsapp_field_values(db,[x.id for x,_ in rows]);out=[]
    for contact,conv in rows:
        values=whatsapp_system_values(contact);values.update(fv.get(contact.id,{}));checks=[_matches(values.get(rule.field,""),rule.operator,rule.value) for rule in spec.rules]
        if all(checks) if spec.logic.lower()=="and" else any(checks):out.append((contact,conv))
    return out

def render_provider_payload(value,values):
    if isinstance(value,str):return re.sub(r"%([a-zA-Z0-9_.-]+)%",lambda m:str(values.get(m.group(1),m.group(0))),value)
    if isinstance(value,list):return [render_provider_payload(x,values) for x in value]
    if isinstance(value,dict):return {k:render_provider_payload(v,values) for k,v in value.items()}
    return value

def whatsapp_render(text,contact,fields):
    values=whatsapp_system_values(contact);values.update(fields);return re.sub(r"%([a-zA-Z0-9_.-]+)%",lambda m:str(values.get(m.group(1),m.group(0))),text)

def get_broadcast(db,broadcast_id):
    b=db.get(Broadcast,broadcast_id)
    if not b:raise HTTPException(404,"Broadcast not found")
    return b
def normalize_finished(db,b):
    if b.status not in ("queued","scheduled","sending","paused"):return b
    pending=db.scalar(select(func.count()).select_from(BroadcastRecipient).where(BroadcastRecipient.broadcast_id==b.id,BroadcastRecipient.status.in_(["pending","sending"]))) or 0
    if pending:return b
    b.sent_count=db.scalar(select(func.count()).select_from(BroadcastRecipient).where(BroadcastRecipient.broadcast_id==b.id,BroadcastRecipient.status=="sent")) or 0
    b.failed_count=db.scalar(select(func.count()).select_from(BroadcastRecipient).where(BroadcastRecipient.broadcast_id==b.id,BroadcastRecipient.status=="failed")) or 0
    b.status="completed";b.completed_at=b.completed_at or now();b.updated_at=now();db.commit();db.refresh(b)
    return b

def field_values(db,contact_ids):
    if not contact_ids:return {}
    rows=db.execute(select(TelegramContactFieldValue.contact_id,ContactFieldDefinition.key,TelegramContactFieldValue.value_text).join(ContactFieldDefinition,ContactFieldDefinition.id==TelegramContactFieldValue.field_id).where(TelegramContactFieldValue.contact_id.in_(contact_ids))).all()
    result={}
    for cid,key,value in rows:result.setdefault(cid,{})[key]=value or ""
    return result

@router.get("")
def list_broadcasts(channel:str|None=None,channel_account_id:int|None=None,db:Session=Depends(get_db),user=Depends(require_manager)):
    q=select(Broadcast)
    if channel:q=q.where(Broadcast.channel==channel)
    if channel_account_id is not None:q=q.where(Broadcast.channel_account_id==channel_account_id)
    return [out(normalize_finished(db,x)) for x in db.scalars(q.order_by(Broadcast.created_at.desc()).limit(200)).all()]
@router.get("/telegram/fields")
def telegram_fields(bot_id:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    wid=workspace(db,bot_id)
    custom=db.execute(select(ContactFieldDefinition.key,ContactFieldDefinition.label).where(ContactFieldDefinition.workspace_id==wid,ContactFieldDefinition.active.is_(True)).order_by(ContactFieldDefinition.sort_order,ContactFieldDefinition.label)).all()
    system=[{"key":"name","label":"Name"},{"key":"first_name","label":"First name"},{"key":"last_name","label":"Last name"},{"key":"username","label":"Username"},{"key":"subscriber_id","label":"Subscriber ID"},{"key":"language_code","label":"Language code"}]
    # A workspace may define a custom field with the same key as a built-in
    # Telegram field.  Present each insertion token only once.
    seen={item["key"] for item in system}
    return system+[{"key":key,"label":label} for key,label in custom if key not in seen]

@router.get("/telegram/audience")
def telegram_audience(bot_id:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    wid=workspace(db,bot_id);bot=db.get(TelegramBot,bot_id)
    if not bot or bot.workspace_id!=wid:raise HTTPException(404,"Telegram bot not found")
    rows=audience(db,wid,bot_id,"all",[])
    return [{"id":c.id,"name":" ".join(x for x in [c.first_name,c.last_name] if x).strip() or c.username or str(c.telegram_user_id),"username":c.username,"telegram_user_id":c.telegram_user_id} for c,_ in rows]
@router.post("/telegram/audience-preview")
def telegram_audience_preview(body:AudiencePreviewIn,db:Session=Depends(get_db),user=Depends(require_manager)):
    wid=workspace(db,body.bot_id);rows=audience(db,wid,body.bot_id,"filtered",[],body.audience_filter)
    return {"count":len(rows),"contacts":[{"id":c.id,"name":_system_values(c)["name"],"username":c.username,"telegram_user_id":c.telegram_user_id} for c,_ in rows[:100]]}

@router.get("/whatsapp/templates")
async def whatsapp_templates(phone_number_id:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    whatsapp_workspace(db,phone_number_id);phone=db.get(WhatsAppPhoneNumber,phone_number_id)
    from app.core.config import settings
    token=phone.access_token or settings.meta_access_token
    if not token:raise HTTPException(503,"No WhatsApp access token configured")
    account=db.get(WhatsAppAccount,phone.whatsapp_account_id)
    try:rows=await list_message_templates(account.waba_id,token)
    except WhatsAppError as exc:
        message=str(exc)
        if "code\\\":190" in message or "validating access token" in message.lower() or "session has expired" in message.lower():
            raise HTTPException(401,"WhatsApp connection needs to be reconnected — the Meta access token has expired or is invalid") from exc
        raise HTTPException(502,f"Meta could not load WhatsApp templates: {message}") from exc
    return [x for x in rows if str(x.get("status","")).upper()=="APPROVED"]

@router.get("/whatsapp/fields")
def whatsapp_fields(phone_number_id:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    wid=whatsapp_workspace(db,phone_number_id);custom=db.execute(select(ContactFieldDefinition.key,ContactFieldDefinition.label).where(ContactFieldDefinition.workspace_id==wid,ContactFieldDefinition.active.is_(True)).order_by(ContactFieldDefinition.sort_order,ContactFieldDefinition.label)).all();system=[{"key":"name","label":"Name"},{"key":"phone","label":"Phone number"},{"key":"wa_id","label":"WhatsApp ID"}];seen={x["key"] for x in system};return system+[{"key":k,"label":l} for k,l in custom if k not in seen]
@router.get("/whatsapp/audience")
def whatsapp_audience_endpoint(phone_number_id:int,message_mode:str="freeform",db:Session=Depends(get_db),user=Depends(require_manager)):
    wid=whatsapp_workspace(db,phone_number_id);rows=whatsapp_audience(db,wid,phone_number_id,"all",[],None,message_mode!="template");return [{"id":x.id,"name":x.name or x.wa_id,"wa_id":x.wa_id} for x,_ in rows]
@router.post("/whatsapp/audience-preview")
def whatsapp_audience_preview(body:WhatsAppAudiencePreviewIn,db:Session=Depends(get_db),user=Depends(require_manager)):
    wid=whatsapp_workspace(db,body.phone_number_id);rows=whatsapp_audience(db,wid,body.phone_number_id,"filtered",[],body.audience_filter,body.message_mode!="template");return {"count":len(rows),"contacts":[{"id":x.id,"name":x.name or x.wa_id,"wa_id":x.wa_id} for x,_ in rows[:100]]}

@router.post("")
def create(body:BroadcastIn,db:Session=Depends(get_db),user=Depends(require_manager)):
    if body.channel=="telegram":
        wid=workspace(db,body.channel_account_id);account=db.get(TelegramBot,body.channel_account_id)
        if not account or account.workspace_id!=wid or not account.active:raise HTTPException(400,"Select an active Telegram bot")
    elif body.channel=="whatsapp":
        wid=whatsapp_workspace(db,body.channel_account_id);account=db.get(WhatsAppPhoneNumber,body.channel_account_id)
        if not account or not account.active:raise HTTPException(400,"Select an active WhatsApp connection")
    else:raise HTTPException(400,"Unsupported broadcast channel")
    b=Broadcast(workspace_id=wid,channel=body.channel,channel_account_id=account.id,name=body.name.strip(),message_text=body.message_text,message_mode=body.message_mode,provider_template_json=json.dumps(body.provider_template) if body.provider_template else None,parse_mode=body.parse_mode,media_url=body.media_url,media_type=body.media_type,stagger_seconds=body.stagger_seconds,audience_type=body.audience_type,audience_filter_json=json.dumps(body.audience_filter.model_dump()) if body.audience_filter else None,audience_segment_id=body.audience_segment_id if body.audience_type=="filtered" else None,status="draft",scheduled_at=utc_naive(body.scheduled_at),created_by_user_id=user.id,created_at=now(),updated_at=now());db.add(b);db.flush()
    if body.channel=="telegram":
        rows=audience(db,wid,account.id,body.audience_type,body.contact_ids,body.audience_filter);fv=field_values(db,[x.id for x,_ in rows])
        for x,conv in rows:db.add(BroadcastRecipient(broadcast_id=b.id,channel_contact_id=x.id,conversation_id=conv.id,destination=str(conv.chat_id),display_name=_system_values(x)["name"],rendered_text=render(body.message_text,x,fv.get(x.id,{})),status="pending",created_at=now(),updated_at=now()))
    else:
        rows=whatsapp_audience(db,wid,account.id,body.audience_type,body.contact_ids,body.audience_filter,body.message_mode!="template");fv=whatsapp_field_values(db,[x.id for x,_ in rows])
        for x,conv in rows:
            values=whatsapp_system_values(x);values.update(fv.get(x.id,{}));provider_payload=render_provider_payload((body.provider_template or {}).get("components_payload") or [],values) if body.message_mode=="template" else None
            db.add(BroadcastRecipient(broadcast_id=b.id,channel_contact_id=x.id,conversation_id=conv.id,destination=x.wa_id,display_name=x.name or x.wa_id,rendered_text=whatsapp_render(body.message_text,x,fv.get(x.id,{})),provider_payload_json=json.dumps(provider_payload) if provider_payload is not None else None,status="pending",created_at=now(),updated_at=now()))
    b.total_recipients=len(rows);db.commit();db.refresh(b);return out(b)
@router.put("/{broadcast_id}")
def update(broadcast_id:int,body:BroadcastIn,db:Session=Depends(get_db),user=Depends(require_manager)):
    b=get_broadcast(db,broadcast_id)
    if b.status!="draft":raise HTTPException(409,"Only draft broadcasts can be edited")
    if body.channel=="telegram":
        wid=workspace(db,body.channel_account_id);account=db.get(TelegramBot,body.channel_account_id)
        if not account or account.workspace_id!=wid or not account.active:raise HTTPException(400,"Select an active Telegram bot")
        rows=audience(db,wid,account.id,body.audience_type,body.contact_ids,body.audience_filter);fv=field_values(db,[x.id for x,_ in rows])
    elif body.channel=="whatsapp":
        wid=whatsapp_workspace(db,body.channel_account_id);account=db.get(WhatsAppPhoneNumber,body.channel_account_id)
        if not account or not account.active:raise HTTPException(400,"Select an active WhatsApp connection")
        rows=whatsapp_audience(db,wid,account.id,body.audience_type,body.contact_ids,body.audience_filter);fv=whatsapp_field_values(db,[x.id for x,_ in rows])
    else:raise HTTPException(400,"Unsupported broadcast channel")
    db.query(BroadcastRecipient).filter(BroadcastRecipient.broadcast_id==b.id).delete(synchronize_session=False)
    b.workspace_id=wid;b.channel=body.channel;b.channel_account_id=account.id;b.name=body.name.strip();b.message_text=body.message_text;b.parse_mode=body.parse_mode;b.media_url=body.media_url;b.media_type=body.media_type;b.stagger_seconds=body.stagger_seconds;b.audience_type=body.audience_type;b.audience_filter_json=json.dumps(body.audience_filter.model_dump()) if body.audience_filter else None;b.audience_segment_id=body.audience_segment_id if body.audience_type=="filtered" else None;b.scheduled_at=utc_naive(body.scheduled_at);b.total_recipients=len(rows);b.sent_count=0;b.failed_count=0;b.updated_at=now()
    for contact,conv in rows:
        if body.channel=="telegram": destination=str(conv.chat_id);display=_system_values(contact)["name"];rendered=render(body.message_text,contact,fv.get(contact.id,{}))
        else:
            destination=contact.wa_id;display=contact.name or contact.wa_id;rendered=whatsapp_render(body.message_text,contact,fv.get(contact.id,{}));values=whatsapp_system_values(contact);values.update(fv.get(contact.id,{}));provider_payload=render_provider_payload((body.provider_template or {}).get("components_payload") or [],values) if body.message_mode=="template" else None
        db.add(BroadcastRecipient(broadcast_id=b.id,channel_contact_id=contact.id,conversation_id=conv.id,destination=destination,display_name=display,rendered_text=rendered,provider_payload_json=json.dumps(provider_payload) if body.channel=="whatsapp" and provider_payload is not None else None,status="pending",created_at=now(),updated_at=now()))
    db.commit();db.refresh(b);return out(b)

@router.delete("/{broadcast_id}",status_code=204)
def delete(broadcast_id:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    b=get_broadcast(db,broadcast_id)
    if b.status!="draft":raise HTTPException(409,"Only draft broadcasts can be deleted")
    db.delete(b);db.commit();return Response(status_code=204)

@router.get("/{broadcast_id}")
def detail(broadcast_id:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    b=normalize_finished(db,get_broadcast(db,broadcast_id))
    data=out(b);data["recipients"]=[{"id":r.id,"contact_id":r.channel_contact_id,"display_name":r.display_name,"destination":r.destination,"status":r.status,"attempts":r.attempts,"provider_message_id":r.provider_message_id,"last_error":r.last_error,"sent_at":r.sent_at} for r in db.scalars(select(BroadcastRecipient).where(BroadcastRecipient.broadcast_id==b.id).order_by(BroadcastRecipient.id)).all()];return data
@router.post("/{broadcast_id}/queue")
def queue(broadcast_id:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    b=get_broadcast(db,broadcast_id)
    if b.status not in ("draft","scheduled"):raise HTTPException(409,"Broadcast cannot be queued from its current state")
    if not b.total_recipients:raise HTTPException(400,"Broadcast has no recipients")
    b.status="scheduled" if b.scheduled_at and b.scheduled_at>now() else "queued";b.updated_at=now();db.commit();db.refresh(b);return out(b)
@router.post("/{broadcast_id}/pause")
def pause(broadcast_id:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    b=get_broadcast(db,broadcast_id)
    if b.status not in ("queued","scheduled","sending"):raise HTTPException(409,"Only queued, scheduled or sending broadcasts can be paused")
    b.status="paused";b.updated_at=now();db.commit();db.refresh(b);return out(b)

@router.post("/{broadcast_id}/resume")
def resume(broadcast_id:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    b=normalize_finished(db,get_broadcast(db,broadcast_id))
    if b.status!="paused":raise HTTPException(409,"Broadcast is already complete" if b.status=="completed" else "Only paused broadcasts can be resumed")
    pending=db.scalar(select(func.count()).select_from(BroadcastRecipient).where(BroadcastRecipient.broadcast_id==b.id,BroadcastRecipient.status=="pending")) or 0
    sending=db.scalar(select(func.count()).select_from(BroadcastRecipient).where(BroadcastRecipient.broadcast_id==b.id,BroadcastRecipient.status=="sending")) or 0
    if not pending and not sending:raise HTTPException(409,"Broadcast has no recipients left to send")
    b.status="queued";b.completed_at=None;b.updated_at=now();db.commit();db.refresh(b);return out(b)

@router.post("/{broadcast_id}/cancel")
def cancel(broadcast_id:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    b=get_broadcast(db,broadcast_id)
    if b.status in ("completed","cancelled"):raise HTTPException(409,"Broadcast is already finished")
    b.status="cancelled";b.updated_at=now();db.commit();db.refresh(b);return out(b)
@router.post("/{broadcast_id}/test")
async def test(broadcast_id:int,body:TestIn,db:Session=Depends(get_db),user=Depends(require_manager)):
    b=get_broadcast(db,broadcast_id)
    r=db.scalar(select(BroadcastRecipient).where(BroadcastRecipient.broadcast_id==b.id,BroadcastRecipient.channel_contact_id==body.contact_id))
    if not r:raise HTTPException(404,"Recipient is not in this broadcast audience")
    if b.channel=="telegram":
        bot=db.get(TelegramBot,b.channel_account_id);result=await (send_media(bot.access_token,int(r.destination),b.media_type,b.media_url,r.rendered_text,b.parse_mode) if b.media_url else send_text(bot.access_token,int(r.destination),r.rendered_text,b.parse_mode));return {"ok":True,"provider_message_id":result.get("message_id")}
    phone=db.get(WhatsAppPhoneNumber,b.channel_account_id)
    if not phone or not phone.active:raise HTTPException(400,"WhatsApp connection is unavailable")
    conv=db.get(Conversation,r.conversation_id)
    if b.message_mode!="template" and (not conv or not conv.service_window_expires_at or conv.service_window_expires_at<=now()):raise HTTPException(409,"This contact is outside the WhatsApp service window; an approved template message is required")
    from app.core.config import settings
    token=phone.access_token or settings.meta_access_token
    if not token:raise HTTPException(503,"No WhatsApp access token configured")
    if b.message_mode=="template":
        snap=json.loads(b.provider_template_json or "{}");components=json.loads(r.provider_payload_json) if r.provider_payload_json else (snap.get("components_payload") or []);result=await send_template_message(phone.phone_number_id,token,r.destination,snap["name"],snap["language"],components)
    else:result=await (send_media_message(phone.phone_number_id,token,r.destination,b.media_type,b.media_url,r.rendered_text) if b.media_url else send_text_message(phone.phone_number_id,token,r.destination,r.rendered_text))
    return {"ok":True,"provider_message_id":((result.get("messages") or [{}])[0].get("id"))}
