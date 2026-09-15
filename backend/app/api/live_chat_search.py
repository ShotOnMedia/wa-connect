from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, cast, exists, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.database import get_db
from app.core.security import require_user
from app.models import Contact, ContactFieldValue, Conversation, Message, User, UserRole
from app.telegram_models import TelegramContact, TelegramContactFieldValue, TelegramConversation

router = APIRouter(prefix="/live-chat-search", tags=["Live Chat"])


def _is_agent(user: User) -> bool:
    return user.role == UserRole.AGENT or getattr(user.role, "value", user.role) == "agent"


def _like(value: str):
    return f"%{value.strip()}%"


def _whatsapp_out(db: Session, conversation: Conversation):
    last = db.scalar(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at.desc()).limit(1))
    return {
        "id": conversation.id,
        "phone_number_id": conversation.phone_number_id,
        "status": getattr(conversation.status, "value", conversation.status),
        "assigned_user_id": conversation.assigned_user_id,
        "last_message_at": conversation.last_message_at,
        "last_message_body": last.body if last else None,
        "last_message_direction": getattr(last.direction, "value", last.direction) if last else None,
        "contact": {"id": conversation.contact.id, "name": conversation.contact.name, "wa_id": conversation.contact.wa_id},
    }


def _telegram_out(conversation: TelegramConversation):
    last = conversation.messages[-1] if conversation.messages else None
    return {
        "id": conversation.id,
        "chat_id": conversation.chat_id,
        "status": conversation.status,
        "assigned_user_id": conversation.assigned_user_id,
        "last_message_at": conversation.last_message_at,
        "last_message_body": last.body if last else None,
        "last_message_type": last.message_type if last else None,
        "last_message_direction": last.direction if last else None,
        "contact": {
            "id": conversation.contact.id,
            "telegram_user_id": conversation.contact.telegram_user_id,
            "username": conversation.contact.username,
            "first_name": conversation.contact.first_name,
            "last_name": conversation.contact.last_name,
            "name": " ".join(filter(None, [conversation.contact.first_name, conversation.contact.last_name])) or conversation.contact.username or str(conversation.contact.telegram_user_id),
        },
        "bot": {"id": conversation.bot.id, "username": conversation.bot.username, "first_name": conversation.bot.first_name},
    }


@router.get("/{channel}")
def search_live_chat(
    channel: str,
    q: str = Query(min_length=1, max_length=200),
    current: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    term = _like(q)
    channel = channel.strip().lower()

    if channel == "whatsapp":
        custom_match = exists(select(ContactFieldValue.id).where(ContactFieldValue.contact_id == Contact.id, ContactFieldValue.value_text.ilike(term)))
        stmt = (
            select(Conversation)
            .join(Contact, Contact.id == Conversation.contact_id)
            .options(joinedload(Conversation.contact))
            .where(or_(Contact.name.ilike(term), Contact.wa_id.ilike(term), cast(Contact.id, String).ilike(term), cast(Conversation.id, String).ilike(term), custom_match))
            .order_by(Conversation.last_message_at.desc())
        )
        if _is_agent(current):
            stmt = stmt.where(Conversation.assigned_user_id == current.id)
        return [_whatsapp_out(db, c) for c in db.scalars(stmt).unique().all()]

    if channel == "telegram":
        custom_match = exists(select(TelegramContactFieldValue.id).where(TelegramContactFieldValue.contact_id == TelegramContact.id, TelegramContactFieldValue.value_text.ilike(term)))
        stmt = (
            select(TelegramConversation)
            .join(TelegramContact, TelegramContact.id == TelegramConversation.contact_id)
            .options(joinedload(TelegramConversation.contact), joinedload(TelegramConversation.bot), selectinload(TelegramConversation.messages))
            .where(or_(
                TelegramContact.first_name.ilike(term), TelegramContact.last_name.ilike(term), TelegramContact.username.ilike(term),
                cast(TelegramContact.telegram_user_id, String).ilike(term), cast(TelegramConversation.chat_id, String).ilike(term),
                cast(TelegramContact.id, String).ilike(term), cast(TelegramConversation.id, String).ilike(term), custom_match,
            ))
            .order_by(TelegramConversation.last_message_at.desc())
        )
        if _is_agent(current):
            stmt = stmt.where(TelegramConversation.assigned_user_id == current.id)
        return [_telegram_out(c) for c in db.scalars(stmt).unique().all()]

    return []
