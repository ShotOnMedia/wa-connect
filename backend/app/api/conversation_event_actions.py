from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.core.security import require_user
from app.flow_models import Flow, FlowSession, FlowSessionStatus
from app.models import Conversation, ConversationStatus, User, UserRole
from app.services.conversation_control import add_event
from app.telegram_models import TelegramConversation

router = APIRouter(tags=["Conversation events"])


class AssignmentIn(BaseModel):
    user_id: int | None = None


class StatusIn(BaseModel):
    status: str


def _is_agent(user):
    return user.role == UserRole.AGENT or getattr(user.role, "value", user.role) == "agent"


def _actor(user):
    return user.name or user.email or f"User {user.id}"


def _target_name(db, user_id):
    if not user_id:
        return "Unassigned"
    user = db.get(User, user_id)
    return (user.name or user.email) if user else f"User {user_id}"


def _wa_access(db, conversation_id, user):
    c = db.scalar(select(Conversation).options(selectinload(Conversation.contact)).where(Conversation.id == conversation_id))
    if not c:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if _is_agent(user) and c.assigned_user_id != user.id:
        raise HTTPException(status_code=403, detail="This conversation is not assigned to you")
    return c


def _tg_access(db, conversation_id, user):
    c = db.get(TelegramConversation, conversation_id)
    if not c:
        raise HTTPException(status_code=404, detail="Telegram conversation not found")
    if _is_agent(user) and c.assigned_user_id != user.id:
        raise HTTPException(status_code=403, detail="This Telegram conversation is not assigned to you")
    return c


@router.patch("/conversations/{conversation_id}/assignment")
def wa_assignment(conversation_id: int, request: AssignmentIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    c = db.get(Conversation, conversation_id)
    if not c:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if _is_agent(user):
        raise HTTPException(status_code=403, detail="Agents cannot change conversation assignments")
    old_id = c.assigned_user_id
    if request.user_id is not None:
        target = db.get(User, request.user_id)
        if not target or not target.active:
            raise HTTPException(status_code=400, detail="Assigned user is unavailable")
    c.assigned_user_id = request.user_id
    if old_id != request.user_id:
        old_name, new_name = _target_name(db, old_id), _target_name(db, request.user_id)
        summary = f"{_actor(user)} unassigned the conversation" if request.user_id is None else f"{_actor(user)} assigned conversation to {new_name}"
        add_event(db, workspace_id=c.workspace_id, channel="whatsapp", conversation_id=c.id, event_type="assignment_changed", summary=summary, actor=user, details={"from": old_name, "to": new_name})
    db.commit()
    return {"id": c.id, "assigned_user_id": c.assigned_user_id}


@router.patch("/conversations/{conversation_id}/status")
def wa_status(conversation_id: int, request: StatusIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    c = _wa_access(db, conversation_id, user)
    try:
        new_status = ConversationStatus(request.status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid conversation status") from exc
    old = getattr(c.status, "value", c.status)
    c.status = new_status
    if old != request.status:
        add_event(db, workspace_id=c.workspace_id, channel="whatsapp", conversation_id=c.id, event_type="status_changed", summary=f"{_actor(user)} changed status from {old} to {request.status}", actor=user, details={"from": old, "to": request.status})
    db.commit()
    return {"id": c.id, "status": request.status, "assigned_user_id": c.assigned_user_id}


@router.post("/conversations/{conversation_id}/flow-session/reset")
def wa_reset(conversation_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    c = _wa_access(db, conversation_id, user)
    session = db.scalar(select(FlowSession).where(FlowSession.conversation_id == c.id))
    if not session:
        return None
    flow = db.get(Flow, session.flow_id)
    previous = getattr(session.status, "value", session.status)
    session.status = FlowSessionStatus.RESET
    session.current_node_id = None
    session.waiting_for = None
    session.ended_at = datetime.utcnow()
    session.reset_by_user_id = user.id
    add_event(db, workspace_id=c.workspace_id, channel="whatsapp", conversation_id=c.id, event_type="flow_reset", summary=f"{_actor(user)} reset flow {flow.name if flow else session.flow_id}", actor=user, details={"flow_id": session.flow_id, "previous_status": previous})
    db.commit()
    return {"id": session.id, "flow_id": session.flow_id, "flow_name": flow.name if flow else f"Flow {session.flow_id}", "status": "reset", "current_node_id": None, "waiting_for": None, "started_at": session.started_at, "updated_at": session.updated_at, "ended_at": session.ended_at}


@router.patch("/telegram/conversations/{conversation_id}/assignment")
def tg_assignment(conversation_id: int, request: AssignmentIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    c = db.get(TelegramConversation, conversation_id)
    if not c:
        raise HTTPException(status_code=404, detail="Telegram conversation not found")
    if _is_agent(user):
        raise HTTPException(status_code=403, detail="Only admins and managers can assign Telegram conversations")
    old_id = c.assigned_user_id
    if request.user_id is not None:
        target = db.get(User, request.user_id)
        if not target or not target.active:
            raise HTTPException(status_code=400, detail="Assigned user is unavailable")
    c.assigned_user_id = request.user_id
    if old_id != request.user_id:
        old_name, new_name = _target_name(db, old_id), _target_name(db, request.user_id)
        summary = f"{_actor(user)} unassigned the conversation" if request.user_id is None else f"{_actor(user)} assigned conversation to {new_name}"
        add_event(db, workspace_id=c.workspace_id, channel="telegram", conversation_id=c.id, event_type="assignment_changed", summary=summary, actor=user, details={"from": old_name, "to": new_name})
    db.commit()
    return {"ok": True, "id": c.id, "assigned_user_id": c.assigned_user_id}


@router.patch("/telegram/conversations/{conversation_id}/status")
def tg_status(conversation_id: int, request: StatusIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    c = _tg_access(db, conversation_id, user)
    status = request.status.strip().lower()
    if status not in {"open", "pending", "resolved"}:
        raise HTTPException(status_code=422, detail="Invalid conversation status")
    old = str(c.status or "open").lower()
    c.status = status
    if old != status:
        add_event(db, workspace_id=c.workspace_id, channel="telegram", conversation_id=c.id, event_type="status_changed", summary=f"{_actor(user)} changed status from {old} to {status}", actor=user, details={"from": old, "to": status})
    db.commit()
    return {"ok": True, "id": c.id, "status": c.status}


@router.post("/telegram/conversations/{conversation_id}/flow-session/reset")
def tg_reset(conversation_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    from app.flow_channel_models import TelegramFlowSession
    from app.flow_delay_models import FlowDelayJob
    from app.user_input_models import UserInputSubmission
    c = _tg_access(db, conversation_id, user)
    now = datetime.utcnow()
    session = db.scalar(select(TelegramFlowSession).where(TelegramFlowSession.conversation_id == c.id))
    previous = session.status if session else None
    flow = db.get(Flow, session.flow_id) if session else None
    if session:
        session.status = "reset"; session.current_node_id = None; session.waiting_for = None; session.ended_at = now; session.updated_at = now
        add_event(db, workspace_id=c.workspace_id, channel="telegram", conversation_id=c.id, event_type="flow_reset", summary=f"{_actor(user)} reset flow {flow.name if flow else session.flow_id}", actor=user, details={"flow_id": session.flow_id, "previous_status": previous})
    delays = db.execute(update(FlowDelayJob).where(FlowDelayJob.channel == "telegram", FlowDelayJob.conversation_id == c.id, FlowDelayJob.status == "pending").values(status="cancelled", completed_at=now, updated_at=now))
    inputs = db.execute(update(UserInputSubmission).where(UserInputSubmission.channel == "telegram", UserInputSubmission.conversation_id == c.id, UserInputSubmission.status == "active").values(status="reset"))
    db.commit()
    return {"ok": True, "status": "neutral", "previous_status": previous, "session_reset": bool(session), "cancelled_delays": int(delays.rowcount or 0), "reset_input_submissions": int(inputs.rowcount or 0)}
