import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ContactFieldDefinition, ContactFieldValue, Conversation
from app.telegram_models import TelegramContactFieldValue, TelegramConversation
from app.user_input_models import UserInputAnswer, UserInputSubmission

VARIABLE_RE = re.compile(r"%([A-Za-z0-9_.-]+)%")
INPUT_PREFIX = "input."


def _keys(text) -> tuple[str, set[str]]:
    value = str(text or "")
    return value, set(VARIABLE_RE.findall(value))


def _replace(value: str, values: dict[str, str | None]) -> str:
    return VARIABLE_RE.sub(lambda match: str(values.get(match.group(1)) or ""), value)


def _input_values(db: Session, conversation_id: int, channel: str, keys: set[str]) -> dict[str, str | None]:
    answer_keys = {key[len(INPUT_PREFIX):] for key in keys if key.startswith(INPUT_PREFIX)}
    if not answer_keys:
        return {}
    submission = db.scalar(
        select(UserInputSubmission)
        .where(
            UserInputSubmission.conversation_id == conversation_id,
            UserInputSubmission.channel == channel,
        )
        .order_by(UserInputSubmission.id.desc())
    )
    if not submission:
        return {}
    rows = db.execute(
        select(UserInputAnswer.answer_key, UserInputAnswer.value_text)
        .where(
            UserInputAnswer.submission_id == submission.id,
            UserInputAnswer.answer_key.in_(answer_keys),
        )
        .order_by(UserInputAnswer.id)
    ).all()
    return {f"{INPUT_PREFIX}{answer_key}": answer_value for answer_key, answer_value in rows}


def render_whatsapp(db: Session, conversation: Conversation, text) -> str:
    value, keys = _keys(text)
    if not keys:
        return value
    field_keys = {key for key in keys if not key.startswith(INPUT_PREFIX)}
    values = _input_values(db, conversation.id, "whatsapp", keys)
    if field_keys:
        rows = db.execute(
            select(ContactFieldDefinition.key, ContactFieldValue.value_text)
            .outerjoin(
                ContactFieldValue,
                (ContactFieldValue.field_id == ContactFieldDefinition.id)
                & (ContactFieldValue.contact_id == conversation.contact_id),
            )
            .where(
                ContactFieldDefinition.workspace_id == conversation.workspace_id,
                ContactFieldDefinition.key.in_(field_keys),
            )
        ).all()
        values.update({str(key): field_value for key, field_value in rows})
    return _replace(value, values)


def render_telegram(db: Session, conversation: TelegramConversation, text) -> str:
    value, keys = _keys(text)
    if not keys:
        return value
    field_keys = {key for key in keys if not key.startswith(INPUT_PREFIX)}
    values = _input_values(db, conversation.id, "telegram", keys)
    if field_keys:
        rows = db.execute(
            select(ContactFieldDefinition.key, TelegramContactFieldValue.value_text)
            .join(
                TelegramContactFieldValue,
                TelegramContactFieldValue.field_id == ContactFieldDefinition.id,
            )
            .where(
                TelegramContactFieldValue.contact_id == conversation.contact_id,
                ContactFieldDefinition.key.in_(field_keys),
            )
        ).all()
        values.update({str(key): field_value for key, field_value in rows})
    return _replace(value, values)
