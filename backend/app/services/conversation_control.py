import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.conversation_control_models import ConversationControl, ConversationEvent


def get_control(db: Session, channel: str, conversation_id: int) -> ConversationControl | None:
    return db.scalar(select(ConversationControl).where(ConversationControl.channel == channel, ConversationControl.conversation_id == conversation_id))


def automation_paused(db: Session, channel: str, conversation_id: int) -> bool:
    control = get_control(db, channel, conversation_id)
    return bool(control and control.human_control)


def add_event(db: Session, *, workspace_id: int, channel: str, conversation_id: int, event_type: str, summary: str, actor=None, details: dict | None = None) -> ConversationEvent:
    event = ConversationEvent(workspace_id=workspace_id, channel=channel, conversation_id=conversation_id, event_type=event_type, actor_user_id=getattr(actor, "id", None), actor_name=getattr(actor, "name", None), summary=summary, details_json=json.dumps(details, ensure_ascii=False) if details else None, created_at=datetime.utcnow())
    db.add(event)
    return event


def set_human_control(db: Session, *, workspace_id: int, channel: str, conversation_id: int, enabled: bool, actor) -> ConversationControl:
    control = get_control(db, channel, conversation_id); now = datetime.utcnow()
    if not control:
        control = ConversationControl(workspace_id=workspace_id, channel=channel, conversation_id=conversation_id, human_control=False, updated_at=now); db.add(control); db.flush()
    control.human_control=enabled; control.taken_over_by_user_id=actor.id if enabled else None; control.taken_over_at=now if enabled else None; control.updated_at=now
    add_event(db, workspace_id=workspace_id, channel=channel, conversation_id=conversation_id, event_type="human_takeover" if enabled else "automation_resumed", summary=f"Automation paused by {actor.name}" if enabled else f"Returned to automation by {actor.name}", actor=actor)
    return control


def _status(value): return getattr(value, "value", value) if value is not None else None

def _flow_name(db, flow_id):
    if not flow_id:return None
    from app.flow_models import Flow
    flow=db.get(Flow,flow_id);return flow.name if flow else f"Flow {flow_id}"

def _user_name(db,user_id):
    if not user_id:return "Unassigned"
    from app.models import User
    user=db.get(User,user_id);return (user.name or user.email) if user else f"User {user_id}"

def _conversation_state(c):return (c.assigned_user_id,_status(c.status))

def _record_conversation_transition(db,channel,c,before,after):
    old_user,old_status=before;new_user,new_status=after;changed=False
    if old_user!=new_user:
        old_name,new_name=_user_name(db,old_user),_user_name(db,new_user)
        summary="Automation unassigned the conversation" if not new_user else f"Automation assigned conversation to {new_name}"
        add_event(db,workspace_id=c.workspace_id,channel=channel,conversation_id=c.id,event_type="assignment_changed",summary=summary,details={"from":old_name,"to":new_name});changed=True
    if old_status!=new_status:
        add_event(db,workspace_id=c.workspace_id,channel=channel,conversation_id=c.id,event_type="status_changed",summary=f"Automation changed status from {old_status} to {new_status}",details={"from":old_status,"to":new_status});changed=True
    return changed

def _record_flow_transition(db,channel,c,before,after,commit=True):
    before_id,before_status=before;after_id,after_status=after
    started=bool(after_id and (before_id!=after_id or before_status in {None,"completed","reset","failed"}) and after_status in {"active","waiting","completed"})
    completed=bool(after_id and after_status=="completed" and (before_id!=after_id or before_status!="completed"))
    if started:
        name=_flow_name(db,after_id);add_event(db,workspace_id=c.workspace_id,channel=channel,conversation_id=c.id,event_type="flow_started",summary=f"Automation started flow {name}",details={"flow_id":after_id,"flow_name":name})
    if completed:
        name=_flow_name(db,after_id);add_event(db,workspace_id=c.workspace_id,channel=channel,conversation_id=c.id,event_type="flow_completed",summary=f"Automation completed flow {name}",details={"flow_id":after_id,"flow_name":name})
    if commit and (started or completed):db.commit()
    return started or completed


def _install_runtime_guards_and_events():
    """Install before webhook/worker modules capture runtime functions."""
    from app.flow_models import FlowSession
    from app.flow_channel_models import TelegramFlowSession
    from app.services import flow_runtime as wa
    from app.services import telegram_flow_queue as queue
    from app.services import telegram_flow_runtime as tg

    if not getattr(wa,"_conversation_events_installed",False):
        original=wa.run_flows_for_inbound
        async def audited(db,c,inbound):
            s=db.scalar(select(FlowSession).where(FlowSession.conversation_id==c.id));before_flow=(s.flow_id,_status(s.status)) if s else (None,None);before_c=_conversation_state(c)
            result=await original(db,c,inbound)
            s=db.scalar(select(FlowSession).where(FlowSession.conversation_id==c.id));after_flow=(s.flow_id,_status(s.status)) if s else (None,None);after_c=_conversation_state(c)
            changed=_record_flow_transition(db,"whatsapp",c,before_flow,after_flow,commit=False)|_record_conversation_transition(db,"whatsapp",c,before_c,after_c)
            if changed:db.commit()
            return result
        wa.run_flows_for_inbound=audited
        original_delay=wa.resume_whatsapp_delay
        async def audited_delay(db,job):
            c=db.get(__import__('app.models',fromlist=['Conversation']).Conversation,job.conversation_id);s=db.scalar(select(FlowSession).where(FlowSession.conversation_id==job.conversation_id));before=(s.flow_id,_status(s.status)) if s else (None,None)
            result=await original_delay(db,job);s=db.scalar(select(FlowSession).where(FlowSession.conversation_id==job.conversation_id));after=(s.flow_id,_status(s.status)) if s else (None,None)
            if c and _record_flow_transition(db,"whatsapp",c,before,after,commit=False):db.commit()
            return result
        wa.resume_whatsapp_delay=audited_delay;wa._conversation_events_installed=True

    if not getattr(tg,"_human_takeover_guard_installed",False):
        original=tg.run_telegram_flows_for_inbound
        async def guarded(db,c,inbound):
            if automation_paused(db,"telegram",c.id):return 0
            s=db.scalar(select(TelegramFlowSession).where(TelegramFlowSession.conversation_id==c.id));before_flow=(s.flow_id,_status(s.status)) if s else (None,None);before_c=_conversation_state(c)
            result=await original(db,c,inbound)
            s=db.scalar(select(TelegramFlowSession).where(TelegramFlowSession.conversation_id==c.id));after_flow=(s.flow_id,_status(s.status)) if s else (None,None);after_c=_conversation_state(c)
            changed=_record_flow_transition(db,"telegram",c,before_flow,after_flow,commit=False)|_record_conversation_transition(db,"telegram",c,before_c,after_c)
            if changed:db.commit()
            return result
        tg.run_telegram_flows_for_inbound=guarded
        original_delay=tg.resume_telegram_delay
        async def audited_tg_delay(db,job):
            from app.telegram_models import TelegramConversation
            c=db.get(TelegramConversation,job.conversation_id);s=db.scalar(select(TelegramFlowSession).where(TelegramFlowSession.conversation_id==job.conversation_id));before=(s.flow_id,_status(s.status)) if s else (None,None)
            result=await original_delay(db,job);s=db.scalar(select(TelegramFlowSession).where(TelegramFlowSession.conversation_id==job.conversation_id));after=(s.flow_id,_status(s.status)) if s else (None,None)
            if c and _record_flow_transition(db,"telegram",c,before,after,commit=False):db.commit()
            return result
        tg.resume_telegram_delay=audited_tg_delay;tg._human_takeover_guard_installed=True

    if not getattr(queue,"_human_takeover_guard_installed",False):
        original_drain=queue.drain_telegram_flow_queue
        async def guarded_drain(db,c):
            if automation_paused(db,"telegram",c.id):return 0
            return await original_drain(db,c)
        queue.drain_telegram_flow_queue=guarded_drain;queue._human_takeover_guard_installed=True


_install_runtime_guards_and_events()
