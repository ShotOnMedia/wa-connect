import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.security import require_user
from app.models import User, UserRole
from app.services.media_storage import read_stored_media
from app.services.telegram import TelegramError, download_file, get_file, send_text
from app.telegram_models import TelegramContact, TelegramConversation, TelegramMessage

router=APIRouter(prefix="/telegram",tags=["Telegram"])

class AssignmentIn(BaseModel): user_id:int|None=None
class SendIn(BaseModel): text:str

def _is_agent(user):return user.role==UserRole.AGENT or getattr(user.role,'value',user.role)=='agent'
def _assert_conversation(db,conversation_id,user):
    conversation=db.get(TelegramConversation,conversation_id)
    if not conversation:raise HTTPException(status_code=404,detail="Telegram conversation not found")
    if _is_agent(user) and conversation.assigned_user_id!=user.id:raise HTTPException(status_code=403,detail="This Telegram conversation is not assigned to you")
    return conversation

def _contact_out(c):return {"id":c.id,"telegram_user_id":c.telegram_user_id,"username":c.username,"first_name":c.first_name,"last_name":c.last_name,"name":" ".join(filter(None,[c.first_name,c.last_name])) or c.username or str(c.telegram_user_id),"language_code":c.language_code,"is_bot":False,"created_at":c.created_at,"updated_at":c.updated_at}
def _media_meta(m):
    if m.message_type not in {"photo","video","voice","audio","document","sticker"}:return None
    try:p=json.loads(m.payload_json or "{}")
    except (TypeError,ValueError):return None
    msg=p.get("message") or {};item=(msg.get("photo") or [])[-1] if m.message_type=="photo" and (msg.get("photo") or []) else msg.get(m.message_type)
    if not isinstance(item,dict):return None
    if not item.get("wa_connect_url") and not item.get("file_id"):return None
    return {"file_id":item.get("file_id"),"file_name":item.get("file_name"),"mime_type":item.get("mime_type"),"file_size":item.get("file_size"),"width":item.get("width"),"height":item.get("height"),"duration":item.get("duration"),"emoji":item.get("emoji"),"stored":bool(item.get("stored_key")),"stored_url":item.get("wa_connect_url"),"stored_key":item.get("stored_key"),"stored_provider":item.get("stored_provider"),"url":f"/telegram/messages/{m.id}/media"}
def _message_out(m):return {"id":m.id,"telegram_message_id":m.telegram_message_id,"direction":m.direction,"message_type":m.message_type,"body":m.body,"media":_media_meta(m),"status":m.status,"telegram_timestamp":m.telegram_timestamp,"created_at":m.created_at}
def _conversation_out(c):
    last=c.messages[-1] if c.messages else None;unread=bool(c.last_message_at and (not c.last_read_at or c.last_read_at<c.last_message_at))
    return {"id":c.id,"chat_id":c.chat_id,"chat_type":c.chat_type,"status":c.status,"assigned_user_id":c.assigned_user_id,"last_message_at":c.last_message_at,"last_read_at":c.last_read_at,"unread_count":1 if unread else 0,"last_message_body":last.body if last else None,"last_message_type":last.message_type if last else None,"last_message_direction":last.direction if last else None,"contact":_contact_out(c.contact),"bot":{"id":c.bot.id,"bot_id":c.bot.bot_id,"username":c.bot.username,"first_name":c.bot.first_name}}

@router.get("/conversations")
def conversations(db:Session=Depends(get_db),user:User=Depends(require_user)):
    stmt=select(TelegramConversation).options(joinedload(TelegramConversation.contact),joinedload(TelegramConversation.bot),joinedload(TelegramConversation.messages)).order_by(TelegramConversation.last_message_at.desc())
    if _is_agent(user):stmt=stmt.where(TelegramConversation.assigned_user_id==user.id)
    return [_conversation_out(c) for c in db.scalars(stmt).unique().all()]

@router.get("/contacts")
def contacts(q:str|None=None,db:Session=Depends(get_db),user:User=Depends(require_user)):
    stmt=select(TelegramContact).order_by(TelegramContact.updated_at.desc())
    if _is_agent(user):stmt=stmt.join(TelegramConversation,TelegramConversation.contact_id==TelegramContact.id).where(TelegramConversation.assigned_user_id==user.id).distinct()
    if q:
        term=f"%{q.strip()}%";stmt=stmt.where(or_(TelegramContact.first_name.ilike(term),TelegramContact.last_name.ilike(term),TelegramContact.username.ilike(term)))
    result=[]
    for c in db.scalars(stmt).all():
        conv_stmt=select(TelegramConversation).options(joinedload(TelegramConversation.bot)).where(TelegramConversation.contact_id==c.id).order_by(TelegramConversation.last_message_at.desc())
        if _is_agent(user):conv_stmt=conv_stmt.where(TelegramConversation.assigned_user_id==user.id)
        convs=db.scalars(conv_stmt).all();result.append({**_contact_out(c),"conversation_count":len(convs),"last_message_at":convs[0].last_message_at if convs else None,"conversations":[{"id":x.id,"chat_id":x.chat_id,"status":x.status,"assigned_user_id":x.assigned_user_id,"last_message_at":x.last_message_at,"bot":{"id":x.bot.id,"username":x.bot.username,"first_name":x.bot.first_name}} for x in convs]})
    return result

@router.get("/contacts/{contact_id}")
def contact(contact_id:int,db:Session=Depends(get_db),user:User=Depends(require_user)):
    c=db.get(TelegramContact,contact_id)
    if not c:raise HTTPException(status_code=404,detail="Telegram contact not found")
    conv_stmt=select(TelegramConversation).options(joinedload(TelegramConversation.bot)).where(TelegramConversation.contact_id==c.id).order_by(TelegramConversation.last_message_at.desc())
    if _is_agent(user):conv_stmt=conv_stmt.where(TelegramConversation.assigned_user_id==user.id)
    convs=db.scalars(conv_stmt).all()
    if _is_agent(user) and not convs:raise HTTPException(status_code=403,detail="This Telegram contact is not assigned to you")
    return {**_contact_out(c),"conversation_count":len(convs),"last_message_at":convs[0].last_message_at if convs else None,"conversations":[{"id":x.id,"chat_id":x.chat_id,"status":x.status,"assigned_user_id":x.assigned_user_id,"last_message_at":x.last_message_at,"bot":{"id":x.bot.id,"username":x.bot.username,"first_name":x.bot.first_name}} for x in convs]}

@router.get("/conversations/{conversation_id}/messages")
def messages(conversation_id:int,db:Session=Depends(get_db),user:User=Depends(require_user)):
    _assert_conversation(db,conversation_id,user);return [_message_out(m) for m in db.scalars(select(TelegramMessage).where(TelegramMessage.conversation_id==conversation_id).order_by(TelegramMessage.created_at.asc())).all()]

@router.get("/messages/{message_id}/media")
async def media(message_id:int,db:Session=Depends(get_db),user:User=Depends(require_user)):
    m=db.scalar(select(TelegramMessage).options(joinedload(TelegramMessage.conversation).joinedload(TelegramConversation.bot)).where(TelegramMessage.id==message_id))
    if not m:raise HTTPException(status_code=404,detail="Telegram message not found")
    _assert_conversation(db,m.conversation_id,user);meta=_media_meta(m)
    if not meta:raise HTTPException(status_code=404,detail="This message has no retrievable Telegram media")
    if meta.get("stored_key"):
        try:stored=read_stored_media(db,meta.get("stored_provider") or "local",meta["stored_key"])
        except Exception as exc:raise HTTPException(status_code=502,detail=f"Stored media retrieval failed: {exc}") from exc
        headers={"Cache-Control":"private, max-age=300"}
        if meta.get("file_name"):headers["Content-Disposition"]=f'inline; filename="{str(meta["file_name"]).replace(chr(34),"")}"'
        return Response(content=stored.content,media_type=meta.get("mime_type") or stored.content_type,headers=headers)
    try:
        info=await get_file(m.conversation.bot.access_token,meta["file_id"]);path=(info or {}).get("file_path")
        if not path:raise TelegramError("Telegram did not return a file path")
        content,content_type=await download_file(m.conversation.bot.access_token,path)
    except TelegramError as exc:raise HTTPException(status_code=502,detail=f"Telegram media retrieval failed: {exc}") from exc
    return Response(content=content,media_type=meta.get("mime_type") or content_type,headers={"Cache-Control":"private, max-age=300"})

@router.post("/conversations/{conversation_id}/read")
def mark_read(conversation_id:int,db:Session=Depends(get_db),user:User=Depends(require_user)):
    c=_assert_conversation(db,conversation_id,user);c.last_read_at=datetime.utcnow();db.commit();return {"ok":True}

@router.patch("/conversations/{conversation_id}/assignment")
def assign(conversation_id:int,request:AssignmentIn,db:Session=Depends(get_db),user:User=Depends(require_user)):
    c=db.get(TelegramConversation,conversation_id)
    if not c:raise HTTPException(status_code=404,detail="Telegram conversation not found")
    if _is_agent(user):raise HTTPException(status_code=403,detail="Only admins and managers can assign Telegram conversations")
    if request.user_id is None:c.assigned_user_id=None
    else:
        target=db.get(User,request.user_id)
        if not target or not target.active:raise HTTPException(status_code=400,detail="Assigned user is unavailable")
        c.assigned_user_id=target.id
    db.commit();return _conversation_out(db.scalar(select(TelegramConversation).options(joinedload(TelegramConversation.contact),joinedload(TelegramConversation.bot),joinedload(TelegramConversation.messages)).where(TelegramConversation.id==c.id)).unique())

@router.post("/conversations/{conversation_id}/messages")
async def send(conversation_id:int,request:SendIn,db:Session=Depends(get_db),user:User=Depends(require_user)):
    c=db.scalar(select(TelegramConversation).options(joinedload(TelegramConversation.bot)).where(TelegramConversation.id==conversation_id))
    if not c:raise HTTPException(status_code=404,detail="Telegram conversation not found")
    if _is_agent(user) and c.assigned_user_id!=user.id:raise HTTPException(status_code=403,detail="This Telegram conversation is not assigned to you")
    text=request.text.strip()
    if not text:raise HTTPException(status_code=422,detail="Message cannot be blank")
    try:sent=await send_text(c.bot.access_token,c.chat_id,text)
    except TelegramError as exc:raise HTTPException(status_code=502,detail=f"Telegram send failed: {exc}") from exc
    timestamp=datetime.utcfromtimestamp(sent["date"]) if sent.get("date") else datetime.utcnow();m=TelegramMessage(conversation_id=c.id,telegram_message_id=int(sent["message_id"]),direction="outbound",message_type="text",body=sent.get("text") or text,payload_json=json.dumps(sent,ensure_ascii=False),status="sent",telegram_timestamp=timestamp);db.add(m);c.last_message_at=timestamp;c.last_read_at=timestamp;db.commit();db.refresh(m);return _message_out(m)

@router.get("/conversations/{conversation_id}/flow-session")
def flow_session(conversation_id:int,db:Session=Depends(get_db),user:User=Depends(require_user)):
    from app.flow_channel_models import TelegramFlowSession
    from app.flow_models import Flow,FlowNode
    _assert_conversation(db,conversation_id,user);session=db.scalar(select(TelegramFlowSession).where(TelegramFlowSession.conversation_id==conversation_id))
    if not session:return None
    flow=db.get(Flow,session.flow_id);node=db.get(FlowNode,session.current_node_id) if session.current_node_id else None;node_type=(node.node_type.value if hasattr(node.node_type,'value') else str(node.node_type)) if node else None
    return {"id":session.id,"flow_id":session.flow_id,"flow_name":flow.name if flow else f"Flow {session.flow_id}","current_node_id":session.current_node_id,"current_node_title":node.title if node else None,"current_node_type":node_type,"status":session.status,"waiting_for":session.waiting_for,"started_at":session.started_at,"updated_at":session.updated_at,"ended_at":session.ended_at}

@router.post("/conversations/{conversation_id}/flow-session/reset")
def reset_flow(conversation_id:int,db:Session=Depends(get_db),user:User=Depends(require_user)):
    from app.flow_channel_models import TelegramFlowSession
    from app.flow_delay_models import FlowDelayJob
    from app.user_input_models import UserInputSubmission
    _assert_conversation(db,conversation_id,user);now=datetime.utcnow();session=db.scalar(select(TelegramFlowSession).where(TelegramFlowSession.conversation_id==conversation_id));previous=session.status if session else None
    if session:session.status="reset";session.current_node_id=None;session.waiting_for=None;session.ended_at=now;session.updated_at=now
    delays=db.execute(update(FlowDelayJob).where(FlowDelayJob.channel=="telegram",FlowDelayJob.conversation_id==conversation_id,FlowDelayJob.status=="pending").values(status="cancelled",completed_at=now,updated_at=now));inputs=db.execute(update(UserInputSubmission).where(UserInputSubmission.channel=="telegram",UserInputSubmission.conversation_id==conversation_id,UserInputSubmission.status=="active").values(status="reset"));db.commit();return {"ok":True,"status":"neutral","previous_status":previous,"session_reset":bool(session),"cancelled_delays":int(delays.rowcount or 0),"reset_input_submissions":int(inputs.rowcount or 0)}