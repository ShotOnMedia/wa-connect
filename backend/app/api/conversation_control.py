from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.conversation_control_models import ConversationEvent
from app.core.database import get_db
from app.core.security import require_user
from app.models import Conversation, User, UserRole
from app.services.conversation_control import get_control, set_human_control
from app.telegram_models import TelegramConversation

router = APIRouter(prefix="/conversation-control", tags=["Conversation control"])


def _conversation(db: Session, channel: str, conversation_id: int, user: User):
    if channel == "whatsapp":
        conversation = db.get(Conversation, conversation_id)
    elif channel == "telegram":
        conversation = db.get(TelegramConversation, conversation_id)
    else:
        raise HTTPException(status_code=400, detail="Unsupported channel")
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if user.role == UserRole.AGENT and conversation.assigned_user_id != user.id:
        raise HTTPException(status_code=403, detail="This conversation is not assigned to you")
    return conversation


def _control_out(db: Session, channel: str, conversation_id: int):
    control = get_control(db, channel, conversation_id)
    return {
        "channel": channel,
        "conversation_id": conversation_id,
        "mode": "human" if control and control.human_control else "automation",
        "human_control": bool(control and control.human_control),
        "taken_over_by_user_id": control.taken_over_by_user_id if control else None,
        "taken_over_at": control.taken_over_at if control else None,
    }


@router.get("/{channel}/{conversation_id}")
def control(channel: str, conversation_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    _conversation(db, channel, conversation_id, user)
    return _control_out(db, channel, conversation_id)


@router.post("/{channel}/{conversation_id}/takeover")
def takeover(channel: str, conversation_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    conversation = _conversation(db, channel, conversation_id, user)
    current = get_control(db, channel, conversation_id)
    if current and current.human_control and current.taken_over_by_user_id not in {None, user.id} and user.role == UserRole.AGENT:
        raise HTTPException(status_code=409, detail="Another agent currently controls this conversation")
    set_human_control(db, workspace_id=conversation.workspace_id, channel=channel, conversation_id=conversation_id, enabled=True, actor=user)
    db.commit()
    return _control_out(db, channel, conversation_id)


@router.post("/{channel}/{conversation_id}/resume")
def resume(channel: str, conversation_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    conversation = _conversation(db, channel, conversation_id, user)
    set_human_control(db, workspace_id=conversation.workspace_id, channel=channel, conversation_id=conversation_id, enabled=False, actor=user)
    db.commit()
    return _control_out(db, channel, conversation_id)


@router.get("/{channel}/{conversation_id}/events")
def events(channel: str, conversation_id: int, limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db), user: User = Depends(require_user)):
    _conversation(db, channel, conversation_id, user)
    rows = list(db.scalars(select(ConversationEvent).where(
        ConversationEvent.channel == channel,
        ConversationEvent.conversation_id == conversation_id,
    ).order_by(ConversationEvent.created_at.desc()).limit(limit)).all())
    rows.reverse()
    return [{
        "id": row.id,
        "event_type": row.event_type,
        "actor_user_id": row.actor_user_id,
        "actor_name": row.actor_name,
        "summary": row.summary,
        "details_json": row.details_json,
        "created_at": row.created_at,
    } for row in rows]
