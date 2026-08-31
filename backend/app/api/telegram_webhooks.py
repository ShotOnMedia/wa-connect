import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.telegram_models import TelegramBot, TelegramContact, TelegramConversation, TelegramMessage

router = APIRouter(prefix="/webhooks/telegram", tags=["Telegram webhooks"])
logger = logging.getLogger(__name__)


def detect_message_type(message: dict) -> tuple[str, str | None]:
    if "text" in message:
        return "text", message.get("text")
    if "photo" in message:
        return "photo", message.get("caption")
    if "video" in message:
        return "video", message.get("caption")
    if "voice" in message:
        return "voice", message.get("caption")
    if "audio" in message:
        return "audio", message.get("caption")
    if "document" in message:
        return "document", message.get("caption")
    if "sticker" in message:
        sticker = message.get("sticker") or {}
        return "sticker", sticker.get("emoji")
    if "location" in message:
        location = message.get("location") or {}
        return "location", f"{location.get('latitude')},{location.get('longitude')}"
    if "contact" in message:
        contact = message.get("contact") or {}
        return "contact", contact.get("phone_number")
    return "unknown", None


@router.post("/{bot_id}")
async def receive_telegram_webhook(
    bot_id: int,
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    bot = db.scalar(select(TelegramBot).where(TelegramBot.bot_id == bot_id, TelegramBot.active.is_(True)))
    if not bot:
        raise HTTPException(status_code=404, detail="Telegram bot not found")
    if not x_telegram_bot_api_secret_token or x_telegram_bot_api_secret_token != bot.webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid Telegram webhook secret")

    payload = await request.json()
    message = payload.get("message")
    if not message:
        return {"ok": True, "processed": 0, "ignored": True}

    sender = message.get("from") or {}
    chat = message.get("chat") or {}
    sender_id = sender.get("id")
    chat_id = chat.get("id")
    telegram_message_id = message.get("message_id")
    if sender_id is None or chat_id is None or telegram_message_id is None:
        return {"ok": True, "processed": 0, "ignored": True}

    contact = db.scalar(
        select(TelegramContact).where(
            TelegramContact.workspace_id == bot.workspace_id,
            TelegramContact.telegram_user_id == int(sender_id),
        )
    )
    if not contact:
        contact = TelegramContact(
            workspace_id=bot.workspace_id,
            telegram_user_id=int(sender_id),
        )
        db.add(contact)
        db.flush()

    contact.username = sender.get("username")
    contact.first_name = sender.get("first_name")
    contact.last_name = sender.get("last_name")
    contact.language_code = sender.get("language_code")

    conversation = db.scalar(
        select(TelegramConversation).where(
            TelegramConversation.telegram_bot_id == bot.id,
            TelegramConversation.chat_id == int(chat_id),
        )
    )
    if not conversation:
        conversation = TelegramConversation(
            workspace_id=bot.workspace_id,
            telegram_bot_id=bot.id,
            contact_id=contact.id,
            chat_id=int(chat_id),
            chat_type=chat.get("type") or "private",
            status="open",
        )
        db.add(conversation)
        db.flush()
    else:
        conversation.contact_id = contact.id

    existing = db.scalar(
        select(TelegramMessage).where(
            TelegramMessage.conversation_id == conversation.id,
            TelegramMessage.telegram_message_id == int(telegram_message_id),
        )
    )
    if existing:
        db.commit()
        return {"ok": True, "processed": 0, "duplicate": True}

    message_type, body = detect_message_type(message)
    timestamp = datetime.utcfromtimestamp(message["date"]) if message.get("date") else datetime.utcnow()
    inbound = TelegramMessage(
        conversation_id=conversation.id,
        telegram_message_id=int(telegram_message_id),
        direction="inbound",
        message_type=message_type,
        body=body,
        payload_json=json.dumps(payload, ensure_ascii=False),
        status="received",
        telegram_timestamp=timestamp,
    )
    db.add(inbound)
    conversation.last_message_at = timestamp
    db.commit()

    logger.info("Telegram inbound stored bot=%s chat=%s message=%s", bot.bot_id, chat_id, telegram_message_id)
    return {"ok": True, "processed": 1, "conversation_id": conversation.id, "message_id": inbound.id}
