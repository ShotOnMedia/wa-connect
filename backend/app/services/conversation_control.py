import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.conversation_control_models import ConversationControl, ConversationEvent


def get_control(db: Session, channel: str, conversation_id: int) -> ConversationControl | None:
    return db.scalar(select(ConversationControl).where(
        ConversationControl.channel == channel,
        ConversationControl.conversation_id == conversation_id,
    ))


def automation_paused(db: Session, channel: str, conversation_id: int) -> bool:
    control = get_control(db, channel, conversation_id)
    return bool(control and control.human_control)


def add_event(db: Session, *, workspace_id: int, channel: str, conversation_id: int,
              event_type: str, summary: str, actor=None, details: dict | None = None) -> ConversationEvent:
    event = ConversationEvent(
        workspace_id=workspace_id,
        channel=channel,
        conversation_id=conversation_id,
        event_type=event_type,
        actor_user_id=getattr(actor, "id", None),
        actor_name=getattr(actor, "name", None),
        summary=summary,
        details_json=json.dumps(details, ensure_ascii=False) if details else None,
        created_at=datetime.utcnow(),
    )
    db.add(event)
    return event


def set_human_control(db: Session, *, workspace_id: int, channel: str, conversation_id: int,
                      enabled: bool, actor) -> ConversationControl:
    control = get_control(db, channel, conversation_id)
    now = datetime.utcnow()
    if not control:
        control = ConversationControl(
            workspace_id=workspace_id,
            channel=channel,
            conversation_id=conversation_id,
            human_control=False,
            updated_at=now,
        )
        db.add(control)
        db.flush()
    control.human_control = enabled
    control.taken_over_by_user_id = actor.id if enabled else None
    control.taken_over_at = now if enabled else None
    control.updated_at = now
    add_event(
        db,
        workspace_id=workspace_id,
        channel=channel,
        conversation_id=conversation_id,
        event_type="human_takeover" if enabled else "automation_resumed",
        summary=(f"Automation paused by {actor.name}" if enabled else f"Returned to automation by {actor.name}"),
        actor=actor,
    )
    return control
