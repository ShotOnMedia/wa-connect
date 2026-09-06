"""Developer API external router compatibility layer.

Channel-aware compatibility routes are registered before the legacy Developer
API router so Telegram resources can live in the Telegram bot workspace while
the API key remains attached to the primary WhatsApp workspace.
"""
from datetime import datetime
import time
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from app.api.developer_api import ConversationUpdate, FieldsUpdate, FlowTriggerRequest, SubscriberUpdate, TagAssign, _assign_tag, _conversation_out, _field_rows, _flow_channel, _log, _remove_tag, _set_fields, _subscriber_out, external_router as legacy_external_router
from app.core.database import get_db
from app.flow_models import Flow, FlowStatus
from app.models import Contact, ContactFieldDefinition, ContactTag, Conversation, ConversationStatus, User, WhatsAppPhoneNumber
from app.services.developer_api import DeveloperApiContext, require_scope
from app.services.external_flow_trigger import trigger_telegram_flow, trigger_whatsapp_flow
from app.telegram_models import TelegramBot, TelegramContact, TelegramConversation
router = APIRouter(tags=["Developer API v1"])

def _telegram_workspace_ids(db): return {int(v) for v in db.scalars(select(TelegramBot.workspace_id).where(TelegramBot.active.is_(True)).distinct()).all()}
def _workspace_ids(db, ctx, channel):
    if channel == "telegram": return _telegram_workspace_ids(db)
    if channel == "whatsapp": return {int(ctx.workspace_id)}
    return {int(ctx.workspace_id)} | _telegram_workspace_ids(db)
def _visible(db, ctx, flow, channel): return int(flow.workspace_id) in (_telegram_workspace_ids(db) if channel == "telegram" else {int(ctx.workspace_id)})
def _parse_ref(ref, channel=None):
    raw=str(ref).strip()
    if ":" in raw:
        kind, ident=raw.split(":",1)
        if kind not in {"whatsapp","telegram"}: raise HTTPException(422,"Subscriber reference must start with whatsapp: or telegram:")
    else: kind,ident=channel or "whatsapp",raw
    try: return kind,int(ident)
    except ValueError as exc: raise HTTPException(422,"Invalid subscriber reference") from exc
def _subscriber(db,ctx,ref,channel=None):
    kind,ident=_parse_ref(ref,channel)
    if kind=="telegram":
        ids=_telegram_workspace_ids(db); row=db.scalar(select(TelegramContact).where(TelegramContact.id==ident,TelegramContact.workspace_id.in_(ids))) if ids else None
    else: row=db.scalar(select(Contact).where(Contact.id==ident,Contact.workspace_id==ctx.workspace_id))
    if not row: raise HTTPException(404,"Subscriber not found")
    return kind,row

def _check_channel(channel):
    if channel not in {None,"whatsapp","telegram"}: raise HTTPException(422,"channel must be whatsapp or telegram")

@router.get("/subscribers")
def subscribers(request:Request,channel:str|None=None,q:str|None=Query(default=None,max_length=200),limit:int=Query(default=100,ge=1,le=500),db:Session=Depends(get_db),ctx:DeveloperApiContext=Depends(require_scope("subscribers:read"))):
    _check_channel(channel); started=time.perf_counter(); out=[]
    if channel in (None,"whatsapp"):
        stmt=select(Contact).where(Contact.workspace_id==ctx.workspace_id)
        if q: term=f"%{q.strip()}%"; stmt=stmt.where(or_(Contact.name.ilike(term),Contact.wa_id.ilike(term)))
        out += [_subscriber_out(db,"whatsapp",r) for r in db.scalars(stmt.order_by(Contact.updated_at.desc()).limit(limit)).all()]
    if channel in (None,"telegram") and len(out)<limit:
        ids=_telegram_workspace_ids(db)
        if ids:
            stmt=select(TelegramContact).where(TelegramContact.workspace_id.in_(ids))
            if q: term=f"%{q.strip()}%"; stmt=stmt.where(or_(TelegramContact.first_name.ilike(term),TelegramContact.last_name.ilike(term),TelegramContact.username.ilike(term)))
            out += [_subscriber_out(db,"telegram",r) for r in db.scalars(stmt.order_by(TelegramContact.updated_at.desc()).limit(limit-len(out))).all()]
    _log(db,ctx,request,started,channel=channel); return {"data":out,"count":len(out)}

@router.get("/custom-fields")
def custom_fields(request:Request,channel:str|None=None,db:Session=Depends(get_db),ctx:DeveloperApiContext=Depends(require_scope("fields:read"))):
    _check_channel(channel); started=time.perf_counter(); ids=_workspace_ids(db,ctx,channel)
    rows=db.scalars(select(ContactFieldDefinition).where(ContactFieldDefinition.workspace_id.in_(ids),ContactFieldDefinition.active.is_(True)).order_by(ContactFieldDefinition.sort_order,ContactFieldDefinition.id)).all(); unique={}
    for f in rows:
        if f.key not in unique or int(f.workspace_id)==int(ctx.workspace_id): unique[f.key]={"id":f.id,"key":f.key,"label":f.label,"type":f.field_type.value,"required":f.required}
    out=list(unique.values()); _log(db,ctx,request,started,channel=channel); return {"data":out,"count":len(out)}

@router.get("/tags")
def tags(request:Request,channel:str|None=None,db:Session=Depends(get_db),ctx:DeveloperApiContext=Depends(require_scope("tags:read"))):
    _check_channel(channel); started=time.perf_counter(); rows=db.scalars(select(ContactTag).where(ContactTag.workspace_id.in_(_workspace_ids(db,ctx,channel))).order_by(ContactTag.name,ContactTag.id)).all(); out=[{"id":r.id,"name":r.name,"workspace_id":r.workspace_id} for r in rows]; _log(db,ctx,request,started,channel=channel); return {"data":out,"count":len(out)}

@router.get("/subscribers/{subscriber_ref}")
def get_subscriber(request:Request,subscriber_ref:str,channel:str|None=None,db:Session=Depends(get_db),ctx:DeveloperApiContext=Depends(require_scope("subscribers:read"))):
    started=time.perf_counter(); kind,row=_subscriber(db,ctx,subscriber_ref,channel); out=_subscriber_out(db,kind,row); _log(db,ctx,request,started,channel=kind); return out
@router.patch("/subscribers/{subscriber_ref}")
def update_subscriber(request:Request,subscriber_ref:str,payload:SubscriberUpdate,db:Session=Depends(get_db),ctx:DeveloperApiContext=Depends(require_scope("subscribers:write"))):
    started=time.perf_counter(); kind,row=_subscriber(db,ctx,subscriber_ref)
    if payload.name is not None:
        if kind=="telegram": parts=payload.name.strip().split(" ",1); row.first_name=parts[0] if parts else None; row.last_name=parts[1] if len(parts)>1 else None
        else: row.name=payload.name.strip() or None
    if payload.fields is not None: _set_fields(db,row.workspace_id,row.id,kind,payload.fields)
    row.updated_at=datetime.utcnow(); db.commit(); out=_subscriber_out(db,kind,row); _log(db,ctx,request,started,channel=kind); return out
@router.delete("/subscribers/{subscriber_ref}",status_code=status.HTTP_204_NO_CONTENT)
def delete_subscriber(request:Request,subscriber_ref:str,db:Session=Depends(get_db),ctx:DeveloperApiContext=Depends(require_scope("subscribers:write"))):
    started=time.perf_counter(); kind,row=_subscriber(db,ctx,subscriber_ref)
    if kind=="whatsapp": row.archived_at=datetime.utcnow(); row.updated_at=datetime.utcnow()
    else: db.delete(row)
    db.commit(); _log(db,ctx,request,started,204,kind)
@router.get("/subscribers/{subscriber_ref}/fields")
def subscriber_fields(request:Request,subscriber_ref:str,db:Session=Depends(get_db),ctx:DeveloperApiContext=Depends(require_scope("fields:read"))):
    started=time.perf_counter(); kind,row=_subscriber(db,ctx,subscriber_ref); out=_field_rows(db,row.workspace_id,row.id,kind); _log(db,ctx,request,started,channel=kind); return {"subscriber":f"{kind}:{row.id}","fields":out}
@router.patch("/subscribers/{subscriber_ref}/fields")
def update_fields(request:Request,subscriber_ref:str,payload:FieldsUpdate,db:Session=Depends(get_db),ctx:DeveloperApiContext=Depends(require_scope("fields:write"))):
    started=time.perf_counter(); kind,row=_subscriber(db,ctx,subscriber_ref); out=_set_fields(db,row.workspace_id,row.id,kind,payload.fields); db.commit(); _log(db,ctx,request,started,channel=kind); return {"subscriber":f"{kind}:{row.id}","fields":out}
@router.post("/subscribers/{subscriber_ref}/tags")
def add_tag(request:Request,subscriber_ref:str,payload:TagAssign,db:Session=Depends(get_db),ctx:DeveloperApiContext=Depends(require_scope("tags:write"))):
    started=time.perf_counter(); kind,row=_subscriber(db,ctx,subscriber_ref); tag=_assign_tag(db,row.workspace_id,row.id,kind,payload.tag_id,payload.name); db.commit(); _log(db,ctx,request,started,channel=kind); return {"id":tag.id,"name":tag.name}
@router.delete("/subscribers/{subscriber_ref}/tags/{tag_id}",status_code=status.HTTP_204_NO_CONTENT)
def remove_tag(request:Request,subscriber_ref:str,tag_id:int,db:Session=Depends(get_db),ctx:DeveloperApiContext=Depends(require_scope("tags:write"))):
    started=time.perf_counter(); kind,row=_subscriber(db,ctx,subscriber_ref); _remove_tag(db,row.id,kind,tag_id); db.commit(); _log(db,ctx,request,started,204,kind)
@router.patch("/subscribers/{subscriber_ref}/conversation")
def conversation(request:Request,subscriber_ref:str,payload:ConversationUpdate,db:Session=Depends(get_db),ctx:DeveloperApiContext=Depends(require_scope("conversations:write"))):
    started=time.perf_counter(); kind,row=_subscriber(db,ctx,subscriber_ref); model=TelegramConversation if kind=="telegram" else Conversation; conv=db.scalar(select(model).where(model.workspace_id==row.workspace_id,model.contact_id==row.id).order_by(model.last_message_at.desc(),model.id.desc()).limit(1))
    if not conv: raise HTTPException(404,"Subscriber has no conversation")
    if payload.status is not None: conv.status=payload.status if kind=="telegram" else ConversationStatus(payload.status)
    if "assigned_user_id" in payload.model_fields_set:
        if payload.assigned_user_id is not None and not db.scalar(select(User.id).where(User.id==payload.assigned_user_id,User.active.is_(True))): raise HTTPException(422,"Assigned user not found or inactive")
        conv.assigned_user_id=payload.assigned_user_id
    db.commit(); out=_conversation_out(db,kind,row.id); _log(db,ctx,request,started,channel=kind); return out

@router.get("/bot-flows")
def flows(request:Request,channel:str|None=None,db:Session=Depends(get_db),ctx:DeveloperApiContext=Depends(require_scope("flows:read"))):
    _check_channel(channel); started=time.perf_counter(); out=[]
    for f in db.scalars(select(Flow).order_by(Flow.name)).all():
        fc=_flow_channel(db,f.id)
        if (channel and fc!=channel) or not _visible(db,ctx,f,fc): continue
        out.append({"id":f.id,"name":f.name,"description":f.description,"channel":fc,"status":f.status.value,"trigger_type":f.trigger_type.value,"updated_at":f.updated_at})
    _log(db,ctx,request,started,channel=channel); return {"data":out,"count":len(out)}
@router.post("/bot-flows/{flow_id}/trigger")
async def trigger(request:Request,flow_id:int,payload:FlowTriggerRequest,db:Session=Depends(get_db),ctx:DeveloperApiContext=Depends(require_scope("flows:trigger"))):
    started=time.perf_counter(); flow=db.get(Flow,flow_id)
    if not flow: raise HTTPException(404,"Flow not found")
    channel=_flow_channel(db,flow.id)
    if not _visible(db,ctx,flow,channel): raise HTTPException(404,"Flow not found")
    if flow.status!=FlowStatus.ACTIVE: raise HTTPException(409,"Only active flows can be triggered")
    if payload.channel and payload.channel!=channel: raise HTTPException(422,f"Flow belongs to {channel}, not {payload.channel}")
    wid=int(flow.workspace_id); raw=str(payload.subscriber).strip()
    if ":" in raw:
        rc,rid=_parse_ref(raw)
        if rc!=channel: raise HTTPException(422,f"Flow belongs to {channel}, but subscriber reference belongs to {rc}")
        model=TelegramContact if channel=="telegram" else Contact; sub=db.scalar(select(model).where(model.workspace_id==wid,model.id==rid))
    elif channel=="telegram":
        try: tid=int(raw)
        except ValueError as exc: raise HTTPException(422,"Telegram subscriber must be a telegram:<id> reference or numeric Telegram user ID") from exc
        sub=db.scalar(select(TelegramContact).where(TelegramContact.workspace_id==wid,TelegramContact.telegram_user_id==tid))
    else: wa="".join(c for c in raw if c.isdigit()); sub=db.scalar(select(Contact).where(Contact.workspace_id==wid,Contact.wa_id==wa))
    if not sub: raise HTTPException(404,f"{channel.title()} subscriber not found")
    if payload.fields: _set_fields(db,wid,sub.id,channel,payload.fields); db.flush()
    if channel=="telegram":
        conv=db.scalar(select(TelegramConversation).where(TelegramConversation.workspace_id==wid,TelegramConversation.contact_id==sub.id).order_by(TelegramConversation.last_message_at.desc(),TelegramConversation.id.desc()).limit(1))
        if not conv: raise HTTPException(409,"Telegram subscriber has no bot conversation to send through")
        try: _,session=await trigger_telegram_flow(db,flow,conv,payload.restart)
        except RuntimeError as exc: raise HTTPException(409,str(exc)) from exc
        db.commit(); state=session.status if session else "unknown"; waiting=session.waiting_for if session else None
    else:
        conv=db.scalar(select(Conversation).where(Conversation.contact_id==sub.id).order_by(Conversation.last_message_at.desc(),Conversation.id.desc()).limit(1))
        if payload.connection_id: conv=db.scalar(select(Conversation).where(Conversation.contact_id==sub.id,Conversation.phone_number_id==payload.connection_id)) or conv
        if not conv:
            phone=db.scalar(select(WhatsAppPhoneNumber).join(WhatsAppPhoneNumber.account).where(WhatsAppPhoneNumber.active.is_(True),WhatsAppPhoneNumber.account.has(workspace_id=wid)).order_by(WhatsAppPhoneNumber.id).limit(1))
            if not phone: raise HTTPException(409,"No active WhatsApp number is connected to this workspace")
            conv=Conversation(workspace_id=wid,phone_number_id=phone.id,contact_id=sub.id); db.add(conv); db.flush()
        try: _,session=await trigger_whatsapp_flow(db,flow,conv,payload.restart)
        except RuntimeError as exc: raise HTTPException(409,str(exc)) from exc
        db.commit(); state=session.status.value if session else "unknown"; waiting=session.waiting_for if session else None
    out={"ok":True,"flow_id":flow.id,"flow":flow.name,"channel":channel,"subscriber":f"{channel}:{sub.id}","status":state,"waiting_for":waiting}; _log(db,ctx,request,started,channel=channel); return out

router.include_router(legacy_external_router)
