import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ContactFieldDefinition, ContactFieldValue, Conversation
from app.telegram_models import TelegramContactFieldValue, TelegramConversation

VARIABLE_RE = re.compile(r"%([A-Za-z0-9_.-]+)%")


def _keys(text) -> tuple[str, set[str]]:
    value = str(text or "")
    return value, set(VARIABLE_RE.findall(value))


def _replace(value: str, values: dict[str, str | None]) -> str:
    return VARIABLE_RE.sub(lambda match: str(values.get(match.group(1)) or ""), value)


def render_whatsapp(db: Session, conversation: Conversation, text) -> str:
    value, keys = _keys(text)
    if not keys:
        return value
    rows = db.execute(
        select(ContactFieldDefinition.key, ContactFieldValue.value_text)
        .outerjoin(
            ContactFieldValue,
            (ContactFieldValue.field_id == ContactFieldDefinition.id)
            & (ContactFieldValue.contact_id == conversation.contact_id),
        )
        .where(
            ContactFieldDefinition.workspace_id == conversation.workspace_id,
            ContactFieldDefinition.key.in_(keys),
        )
    ).all()
    return _replace(value, {str(key): field_value for key, field_value in rows})


def render_telegram(db: Session, conversation: TelegramConversation, text) -> str:
    value, keys = _keys(text)
    if not keys:
        return value
    rows = db.execute(
        select(ContactFieldDefinition.key, TelegramContactFieldValue.value_text)
        .join(
            TelegramContactFieldValue,
            TelegramContactFieldValue.field_id == ContactFieldDefinition.id,
        )
        .where(
            TelegramContactFieldValue.contact_id == conversation.contact_id,
            ContactFieldDefinition.key.in_(keys),
        )
    ).all()
    return _replace(value, {str(key): field_value for key, field_value in rows})
