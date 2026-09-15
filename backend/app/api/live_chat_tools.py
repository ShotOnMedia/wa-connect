from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from app.canned_response_models import CannedResponse
from app.core.database import get_db
from app.core.security import require_user
from app.flow_channel_models import FlowChannelTarget
from app.flow_models import Flow, FlowStatus
from app.models import Conversation, User, UserRole
from app.services.conversation_control import add_event, automation_paused, set_human_control
from app.services.external_flow_trigger import trigger_telegram_flow, trigger_whatsapp_flow
from app.telegram_models import TelegramConversation
router=APIRouter(prefix="/live-chat-tools",tags=["Live Chat"])
def agent(user): return user.role==UserRole.AGENT or getattr(user.role,"value",user.role)=="agent"
def actor(user): return user.name or user.email or f"User {user.id}"
def access(db,channel,cid,user):
    model=TelegramConversation if channel=="telegram" else Conversation;c=db.get(model,cid)
    if not c: raise HTTPException(404,"Conversation not found")
    if agent(user) and c.assigned_user_id!=user.id: raise HTTPException(403,"This conversation is not assigned to you")
    return c
def wid(user,c): return int(getattr(c,"workspace_id",None) or getattr(user,"workspace_id",0))
class TriggerIn(BaseModel): flow_id:int;resume_automation:bool=False
@router.get("/{channel}/{conversation_id}/flows")
def flows(channel:str,conversation_id:int,db:Session=Depends(get_db),user:User=Depends(require_user)):
    c=access(db,channel,conversation_id,user);workspace=wid(user,c);stmt=(select(Flow).join(FlowChannelTarget,FlowChannelTarget.flow_id==Flow.id).where(Flow.workspace_id==workspace,Flow.status==FlowStatus.ACTIVE,FlowChannelTarget.channel==channel).order_by(Flow.name));return [{"id":f.id,"name":f.name,"description":f.description,"trigger_type":getattr(f.trigger_type,"value",f.trigger_type)} for f in db.scalars(stmt).all()]
@router.post("/{channel}/{conversation_id}/trigger-flow")
async def trigger(channel:str,conversation_id:int,payload:TriggerIn,db:Session=Depends(get_db),user:User=Depends(require_user)):
    c=access(db,channel,conversation_id,user);workspace=wid(user,c);f=db.get(Flow,payload.flow_id);target=db.scalar(select(FlowChannelTarget).where(FlowChannelTarget.flow_id==payload.flow_id))
    if not f or int(f.workspace_id)!=workspace or f.status!=FlowStatus.ACTIVE or not target or target.channel!=channel: raise HTTPException(404,"Active flow not found for this channel")
    if automation_paused(db,channel,c.id):
        if not payload.resume_automation: raise HTTPException(409,"Human control is active. Confirm returning this conversation to automation first.")
        set_human_control(db,workspace_id=workspace,channel=channel,conversation_id=c.id,enabled=False,actor=user)
    try:
        if channel=="telegram": _,session=await trigger_telegram_flow(db,f,c,True)
        elif channel=="whatsapp": _,session=await trigger_whatsapp_flow(db,f,c,True)
        else: raise HTTPException(422,"Unsupported channel")
    except RuntimeError as exc: raise HTTPException(409,str(exc)) from exc
    add_event(db,workspace_id=workspace,channel=channel,conversation_id=c.id,event_type="flow_started",summary=f"{actor(user)} manually started flow {f.name}",actor=user,details={"flow_id":f.id,"flow_name":f.name,"manual":True})
    status=getattr(getattr(session,"status",None),"value",getattr(session,"status",None))
    if status=="completed": add_event(db,workspace_id=workspace,channel=channel,conversation_id=c.id,event_type="flow_completed",summary=f"Automation completed flow {f.name}",details={"flow_id":f.id,"flow_name":f.name,"manual":True})
    db.commit();return {"ok":True,"flow_id":f.id,"flow":f.name,"status":status}
class CannedIn(BaseModel): title:str;shortcut:str;body:str;channel:str="both";active:bool=True
@router.get("/{channel}/{conversation_id}/canned-responses")
def canned(channel:str,conversation_id:int,db:Session=Depends(get_db),user:User=Depends(require_user)):
    c=access(db,channel,conversation_id,user);workspace=wid(user,c);rows=db.scalars(select(CannedResponse).where(CannedResponse.workspace_id==workspace,CannedResponse.active.is_(True),or_(CannedResponse.channel=="both",CannedResponse.channel==channel)).order_by(CannedResponse.title)).all();return [{"id":r.id,"title":r.title,"shortcut":r.shortcut,"body":r.body,"channel":r.channel} for r in rows]
@router.get("/canned-responses/manage")
def manage(db:Session=Depends(get_db),user:User=Depends(require_user)):
    rows=db.scalars(select(CannedResponse).where(CannedResponse.workspace_id==user.workspace_id).order_by(CannedResponse.title)).all();return [{"id":r.id,"title":r.title,"shortcut":r.shortcut,"body":r.body,"channel":r.channel,"active":r.active} for r in rows]
@router.post("/canned-responses/manage")
def create(payload:CannedIn,db:Session=Depends(get_db),user:User=Depends(require_user)):
    if agent(user): raise HTTPException(403,"Only managers and admins can manage canned responses")
    shortcut=payload.shortcut.strip().lstrip('/')
    if not shortcut or not payload.title.strip() or not payload.body.strip() or payload.channel not in {"both","whatsapp","telegram"}: raise HTTPException(422,"Title, shortcut and response text are required")
    r=CannedResponse(workspace_id=user.workspace_id,title=payload.title.strip(),shortcut=shortcut,body=payload.body,channel=payload.channel,active=payload.active,created_by_user_id=user.id);db.add(r)
    try: db.commit()
    except Exception as exc: db.rollback();raise HTTPException(409,"That shortcut is already in use") from exc
    db.refresh(r);return {"id":r.id,"title":r.title,"shortcut":r.shortcut,"body":r.body,"channel":r.channel,"active":r.active}
@router.delete("/canned-responses/manage/{response_id}")
def delete(response_id:int,db:Session=Depends(get_db),user:User=Depends(require_user)):
    if agent(user): raise HTTPException(403,"Only managers and admins can manage canned responses")
    r=db.get(CannedResponse,response_id)
    if not r or r.workspace_id!=user.workspace_id: raise HTTPException(404,"Canned response not found")
    db.delete(r);db.commit();return {"ok":True}
