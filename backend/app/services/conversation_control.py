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


def _status(value):
    return getattr(value, "value", value) if value is not None else None


def _flow_name(db, flow_id):
    if not flow_id:
        return None
    from app.flow_models import Flow
    flow = db.get(Flow, flow_id)
    return flow.name if flow else f"Flow {flow_id}"


def _record_flow_transition(db, channel, conversation, before, after):
    """Audit only meaningful lifecycle edges, not every waiting/resume hop."""
    before_id, before_status = before
    after_id, after_status = after
    started = bool(after_id and (before_id != after_id or before_status in {None, "completed", "reset", "failed"}) and after_status in {"active", "waiting", "completed"})
    completed = bool(after_id and after_status == "completed" and (before_id != after_id or before_status != "completed"))
    if started:
        name = _flow_name(db, after_id)
        add_event(db, workspace_id=conversation.workspace_id, channel=channel, conversation_id=conversation.id,
                  event_type="flow_started", summary=f"Automation started flow {name}", details={"flow_id": after_id, "flow_name": name})
    if completed:
        name = _flow_name(db, after_id)
        add_event(db, workspace_id=conversation.workspace_id, channel=channel, conversation_id=conversation.id,
                  event_type="flow_completed", summary=f"Automation completed flow {name}", details={"flow_id": after_id, "flow_name": name})
    if started or completed:
        db.commit()


def _install_runtime_guards_and_events():
    """Install before webhook modules capture their runtime functions."""
    from app.flow_models import FlowSession
    from app.flow_channel_models import TelegramFlowSession
    from app.services import flow_runtime as whatsapp_runtime
    from app.services import telegram_flow_queue as queue
    from app.services import telegram_flow_runtime as telegram_runtime

    if not getattr(whatsapp_runtime, "_conversation_events_installed", False):
        original_wa = whatsapp_runtime.run_flows_for_inbound

        async def audited_whatsapp(db, conversation, inbound):
            before_session = db.scalar(select(FlowSession).where(FlowSession.conversation_id == conversation.id))
            before = (before_session.flow_id, _status(before_session.status)) if before_session else (None, None)
            result = await original_wa(db, conversation, inbound)
            after_session = db.scalar(select(FlowSession).where(FlowSession.conversation_id == conversation.id))
            after = (after_session.flow_id, _status(after_session.status)) if after_session else (None, None)
            _record_flow_transition(db, "whatsapp", conversation, before, after)
            return result

        whatsapp_runtime.run_flows_for_inbound = audited_whatsapp
        whatsapp_runtime._conversation_events_installed = True

    if not getattr(telegram_runtime, "_human_takeover_guard_installed", False):
        original_tg = telegram_runtime.run_telegram_flows_for_inbound

        async def guarded_telegram(db, conversation, inbound):
            if automation_paused(db, "telegram", conversation.id):
                return 0
            before_session = db.scalar(select(TelegramFlowSession).where(TelegramFlowSession.conversation_id == conversation.id))
            before = (before_session.flow_id, _status(before_session.status)) if before_session else (None, None)
            result = await original_tg(db, conversation, inbound)
            after_session = db.scalar(select(TelegramFlowSession).where(TelegramFlowSession.conversation_id == conversation.id))
            after = (after_session.flow_id, _status(after_session.status)) if after_session else (None, None)
            _record_flow_transition(db, "telegram", conversation, before, after)
            return result

        telegram_runtime.run_telegram_flows_for_inbound = guarded_telegram
        telegram_runtime._human_takeover_guard_installed = True

    if not getattr(queue, "_human_takeover_guard_installed", False):
        original_drain = queue.drain_telegram_flow_queue

        async def guarded_drain(db, conversation):
            if automation_paused(db, "telegram", conversation.id):
                return 0
            return await original_drain(db, conversation)

        queue.drain_telegram_flow_queue = guarded_drain
        queue._human_takeover_guard_installed = True


_install_runtime_guards_and_events()
