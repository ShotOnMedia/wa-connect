import json
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.flow_models import Flow, FlowStatus, FlowStepType, FlowTriggerType
from app.models import (
    ContactFieldDefinition,
    ContactFieldValue,
    ContactTag,
    ContactTagLink,
    Conversation,
    ConversationStatus,
    Message,
    MessageDirection,
    MessageStatus,
    User,
)
from app.services.whatsapp import WhatsAppError, send_text_message


def _config(step) -> dict:
    try:
        return json.loads(step.config_json or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}


def _match_keyword(expected: str | None, body: str | None) -> bool:
    if not expected or not body:
        return False
    return expected.strip().casefold() == body.strip().casefold()


def _matching_flows(db: Session, conversation: Conversation, inbound_message: Message) -> list[Flow]:
    flows = db.scalars(
        select(Flow)
        .options(selectinload(Flow.steps))
        .where(Flow.workspace_id == conversation.workspace_id, Flow.status == FlowStatus.ACTIVE)
        .order_by(Flow.id.asc())
    ).all()

    inbound_count = db.scalar(
        select(func.count(Message.id)).where(
            Message.conversation_id == conversation.id,
            Message.direction == MessageDirection.INBOUND,
        )
    ) or 0

    matched = []
    for flow in flows:
        if flow.trigger_type == FlowTriggerType.KEYWORD and _match_keyword(flow.trigger_value, inbound_message.body):
            matched.append(flow)
        elif flow.trigger_type == FlowTriggerType.FIRST_MESSAGE and inbound_count == 1:
            matched.append(flow)
    return matched


async def _execute_step(db: Session, conversation: Conversation, step) -> None:
    config = _config(step)
    contact = conversation.contact

    if step.step_type == FlowStepType.SEND_MESSAGE:
        text = str(config.get("text") or "").strip()
        if not text:
            return
        phone = conversation.phone_number
        if not phone.access_token:
            raise RuntimeError("WhatsApp phone number has no access token")
        response = await send_text_message(phone.phone_number_id, phone.access_token, contact.wa_id, text)
        meta_id = None
        messages = response.get("messages") or []
        if messages:
            meta_id = messages[0].get("id")
        now = datetime.utcnow()
        db.add(Message(
            conversation_id=conversation.id,
            meta_message_id=meta_id,
            direction=MessageDirection.OUTBOUND,
            message_type="text",
            body=text,
            payload_json=json.dumps(response, ensure_ascii=False),
            status=MessageStatus.SENT,
            created_at=now,
        ))
        conversation.last_message_at = now
        db.flush()
        return

    if step.step_type in {FlowStepType.ADD_TAG, FlowStepType.REMOVE_TAG}:
        tag_id = config.get("tag_id")
        if not tag_id:
            return
        tag = db.scalar(select(ContactTag).where(ContactTag.id == int(tag_id), ContactTag.workspace_id == conversation.workspace_id))
        if not tag:
            return
        link = db.scalar(select(ContactTagLink).where(ContactTagLink.contact_id == contact.id, ContactTagLink.tag_id == tag.id))
        if step.step_type == FlowStepType.ADD_TAG and not link:
            db.add(ContactTagLink(contact_id=contact.id, tag_id=tag.id))
        elif step.step_type == FlowStepType.REMOVE_TAG and link:
            db.delete(link)
        db.flush()
        return

    if step.step_type == FlowStepType.SET_FIELD:
        field_id = config.get("field_id")
        if not field_id:
            return
        field = db.scalar(select(ContactFieldDefinition).where(ContactFieldDefinition.id == int(field_id), ContactFieldDefinition.workspace_id == conversation.workspace_id))
        if not field:
            return
        value = config.get("value")
        existing = db.scalar(select(ContactFieldValue).where(ContactFieldValue.contact_id == contact.id, ContactFieldValue.field_id == field.id))
        if existing:
            existing.value_text = None if value is None else str(value)
            existing.updated_at = datetime.utcnow()
        else:
            db.add(ContactFieldValue(contact_id=contact.id, field_id=field.id, value_text=None if value is None else str(value)))
        db.flush()
        return

    if step.step_type == FlowStepType.ASSIGN_USER:
        user_id = config.get("user_id")
        if user_id in (None, "", 0, "0"):
            conversation.assigned_user_id = None
        else:
            user = db.scalar(select(User).where(User.id == int(user_id), User.active.is_(True)))
            if user:
                conversation.assigned_user_id = user.id
        db.flush()
        return

    if step.step_type == FlowStepType.SET_STATUS:
        value = config.get("status")
        if value:
            conversation.status = ConversationStatus(value)
            db.flush()
        return

    # Delay execution needs a durable queue/worker. Do not sleep inside the webhook request.
    if step.step_type == FlowStepType.DELAY:
        return


async def run_flows_for_inbound(db: Session, conversation: Conversation, inbound_message: Message) -> int:
    """Run active synchronous flows matched by one newly-created inbound message.

    Delay steps are intentionally skipped until a durable queued flow-run model is added.
    A failure rolls back only the current flow's uncommitted actions and is re-raised so
    the webhook layer can log it without rejecting Meta's delivery.
    """
    matched = _matching_flows(db, conversation, inbound_message)
    executed = 0
    for flow in matched:
        try:
            for step in sorted(flow.steps, key=lambda item: item.sort_order):
                await _execute_step(db, conversation, step)
            db.commit()
            executed += 1
        except (WhatsAppError, RuntimeError, ValueError):
            db.rollback()
            raise
    return executed
