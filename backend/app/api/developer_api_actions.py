"""Developer API channel actions: direct messaging and bot-flow reset."""
from datetime import datetime
import json
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.developer_api import _log
from app.api.developer_api_body import _resolve_body_subscriber
from app.core.database import get_db
from app.flow_channel_models import TelegramFlowSession
from app.flow_delay_models import FlowDelayJob
from app.flow_models import FlowSession, FlowSessionStatus
from app.models import Conversation, Message, MessageDirection, MessageStatus
from app.services.developer_api import DeveloperApiContext, require_scope
from app.services.telegram import TelegramError, send_text
from app.services.whatsapp import WhatsAppError, send_text_message
from app.telegram_models import TelegramBot, TelegramConversation, TelegramMessage
from app.user_input_models import UserInputSubmission

router = APIRouter(tags=["Developer API v1"])
Channel = Literal["whatsapp", "telegram"]


class SendMessageRequest(BaseModel):
    channel: Channel | None = None
    subscriber: str
    message: str = Field(min_length=1, max_length=4096)
    connection_id: int | None = None


class ResetBotFlowRequest(BaseModel):
    channel: Channel | None = None
    subscriber: str


def _conversation(db: Session, channel: str, subscriber, connection_id: int | None = None):
    if channel == "telegram":
        return db.scalar(
            select(TelegramConversation)
            .where(TelegramConversation.workspace_id == subscriber.workspace_id, TelegramConversation.contact_id == subscriber.id)
            .order_by(TelegramConversation.last_message_at.desc(), TelegramConversation.id.desc())
            .limit(1)
        )
    stmt = select(Conversation).where(Conversation.workspace_id == subscriber.workspace_id, Conversation.contact_id == subscriber.id)
    if connection_id is not None:
        stmt = stmt.where(Conversation.phone_number_id == connection_id)
    return db.scalar(stmt.order_by(Conversation.last_message_at.desc(), Conversation.id.desc()).limit(1))


@router.post("/messages/send")
async def send_message(
    request: Request,
    payload: SendMessageRequest,
    db: Session = Depends(get_db),
    ctx: DeveloperApiContext = Depends(require_scope("conversations:write")),
):
    """Send a free-form text message through the subscriber's channel."""
    started = time.perf_counter()
    channel, subscriber = _resolve_body_subscriber(db, ctx, payload.channel, payload.subscriber)
    conversation = _conversation(db, channel, subscriber, payload.connection_id)
    if not conversation:
        raise HTTPException(status_code=409, detail="Subscriber has no conversation to send through")

    text = payload.message.strip()
    if not text:
        raise HTTPException(status_code=422, detail="message cannot be blank")

    now = datetime.utcnow()
    if channel == "telegram":
        bot = db.get(TelegramBot, conversation.telegram_bot_id)
        if not bot or not bot.active:
            raise HTTPException(status_code=409, detail="Telegram bot is not active")
        try:
            result = await send_text(bot.access_token, conversation.chat_id, text)
        except TelegramError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        external_id = int(result.get("message_id") or 0)
        row = TelegramMessage(
            conversation_id=conversation.id,
            telegram_message_id=external_id,
            direction="outbound",
            message_type="text",
            body=text,
            payload_json=json.dumps(result, ensure_ascii=False),
            status="sent",
            telegram_timestamp=now,
        )
    else:
        # Meta permits free-form messages only inside the customer service window.
        if not conversation.service_window_expires_at or conversation.service_window_expires_at < now:
            raise HTTPException(status_code=409, detail="WhatsApp customer service window is closed; use an approved template message")
        phone = conversation.phone_number
        if not phone or not phone.active or not phone.access_token:
            raise HTTPException(status_code=409, detail="WhatsApp connection is not active")
        try:
            result = await send_text_message(phone.phone_number_id, phone.access_token, subscriber.wa_id, text)
        except WhatsAppError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        external_id = ((result.get("messages") or [{}])[0].get("id"))
        row = Message(
            conversation_id=conversation.id,
            meta_message_id=external_id,
            direction=MessageDirection.OUTBOUND,
            message_type="text",
            body=text,
            payload_json=json.dumps(result, ensure_ascii=False),
            status=MessageStatus.SENT,
        )

    db.add(row)
    conversation.last_message_at = now
    conversation.updated_at = now
    db.commit()
    db.refresh(row)
    _log(db, ctx, request, started, channel=channel)
    return {
        "ok": True,
        "subscriber": f"{channel}:{subscriber.id}",
        "channel": channel,
        "conversation_id": conversation.id,
        "message_id": row.id,
        "external_message_id": external_id,
        "status": "sent",
        "message": text,
    }


def _reset_flow(request: Request, payload: ResetBotFlowRequest, db: Session, ctx: DeveloperApiContext):
    """Put a subscriber back into a neutral flow state.

    Resets the current channel flow session, cancels pending durable delays and
    abandons active User Input submissions. It does not delete flow history.
    """
    started = time.perf_counter()
    channel, subscriber = _resolve_body_subscriber(db, ctx, payload.channel, payload.subscriber)
    conversation = _conversation(db, channel, subscriber)
    if not conversation:
        raise HTTPException(status_code=404, detail="Subscriber has no conversation")

    now = datetime.utcnow()
    if channel == "telegram":
        session = db.scalar(select(TelegramFlowSession).where(TelegramFlowSession.conversation_id == conversation.id))
        previous = session.status if session else None
        if session:
            session.status = "reset"
            session.current_node_id = None
            session.waiting_for = None
            session.ended_at = now
            session.updated_at = now
    else:
        session = db.scalar(select(FlowSession).where(FlowSession.conversation_id == conversation.id))
        previous = session.status.value if session else None
        if session:
            session.status = FlowSessionStatus.RESET
            session.current_node_id = None
            session.waiting_for = None
            session.ended_at = now
            session.updated_at = now

    delay_result = db.execute(
        update(FlowDelayJob)
        .where(
            FlowDelayJob.channel == channel,
            FlowDelayJob.conversation_id == conversation.id,
            FlowDelayJob.status == "pending",
        )
        .values(status="cancelled", completed_at=now, updated_at=now)
    )
    input_result = db.execute(
        update(UserInputSubmission)
        .where(
            UserInputSubmission.channel == channel,
            UserInputSubmission.conversation_id == conversation.id,
            UserInputSubmission.status == "active",
        )
        .values(status="reset")
    )
    db.commit()
    _log(db, ctx, request, started, channel=channel)
    return {
        "ok": True,
        "subscriber": f"{channel}:{subscriber.id}",
        "channel": channel,
        "conversation_id": conversation.id,
        "previous_status": previous,
        "status": "neutral",
        "session_reset": bool(session),
        "cancelled_delays": int(delay_result.rowcount or 0),
        "reset_input_submissions": int(input_result.rowcount or 0),
    }


@router.post("/bot-flows/reset")
def post_reset_bot_flow(
    request: Request,
    payload: ResetBotFlowRequest,
    db: Session = Depends(get_db),
    ctx: DeveloperApiContext = Depends(require_scope("flows:trigger")),
):
    return _reset_flow(request, payload, db, ctx)


@router.patch("/bot-flows/reset")
def patch_reset_bot_flow(
    request: Request,
    payload: ResetBotFlowRequest,
    db: Session = Depends(get_db),
    ctx: DeveloperApiContext = Depends(require_scope("flows:trigger")),
):
    return _reset_flow(request, payload, db, ctx)
