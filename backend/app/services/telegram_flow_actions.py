from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ContactFieldDefinition, ContactTag, User
from app.telegram_models import TelegramContactFieldValue, TelegramContactTagLink, TelegramConversation


def compare(actual, expected, operator: str) -> bool:
    a = str(actual or "").strip()
    e = str(expected or "").strip()
    op = str(operator or "equals")
    if op in {"equals", "open"}: return a.casefold() == e.casefold()
    if op in {"not_equals", "closed"}: return a.casefold() != e.casefold()
    if op == "contains": return e.casefold() in a.casefold()
    if op == "not_contains": return e.casefold() not in a.casefold()
    if op == "starts_with": return a.casefold().startswith(e.casefold())
    if op == "ends_with": return a.casefold().endswith(e.casefold())
    if op == "empty": return not a
    if op == "not_empty": return bool(a)
    return False


def set_field(db: Session, conversation: TelegramConversation, field_id: int, value) -> bool:
    # Custom-field definitions are shared by the multi-channel flow builder. Telegram
    # contacts keep their own values, but may reference a definition originally created
    # while working in the WhatsApp workspace.
    field = db.scalar(select(ContactFieldDefinition).where(
        ContactFieldDefinition.id == int(field_id),
        ContactFieldDefinition.active.is_(True),
    ))
    if not field:
        return False
    text = None if value is None else str(value).strip()
    row = db.scalar(select(TelegramContactFieldValue).where(
        TelegramContactFieldValue.contact_id == conversation.contact_id,
        TelegramContactFieldValue.field_id == field.id,
    ))
    if row:
        row.value_text = text
        row.updated_at = datetime.utcnow()
    else:
        db.add(TelegramContactFieldValue(contact_id=conversation.contact_id, field_id=field.id, value_text=text))
    db.flush()
    return True


def change_tag(db: Session, conversation: TelegramConversation, tag_id: int, add: bool) -> bool:
    tag = db.scalar(select(ContactTag).where(
        ContactTag.id == int(tag_id),
        ContactTag.workspace_id == conversation.workspace_id,
    ))
    if not tag:
        return False
    link = db.scalar(select(TelegramContactTagLink).where(
        TelegramContactTagLink.contact_id == conversation.contact_id,
        TelegramContactTagLink.tag_id == tag.id,
    ))
    if add and not link:
        db.add(TelegramContactTagLink(contact_id=conversation.contact_id, tag_id=tag.id))
    elif not add and link:
        db.delete(link)
    db.flush()
    return True


def assign_user(db: Session, conversation: TelegramConversation, user_id) -> bool:
    if user_id in (None, "", 0, "0"):
        conversation.assigned_user_id = None
        db.flush()
        return True
    user = db.scalar(select(User).where(User.id == int(user_id), User.active.is_(True)))
    if not user:
        return False
    conversation.assigned_user_id = user.id
    db.flush()
    return True


def set_status(db: Session, conversation: TelegramConversation, status) -> bool:
    value = str(status or "").strip().lower()
    if value not in {"open", "pending", "resolved"}:
        return False
    conversation.status = value
    db.flush()
    return True


def condition_result(db: Session, conversation: TelegramConversation, config: dict) -> bool:
    field = str(config.get("field") or "conversation_status")
    operator = str(config.get("operator") or "equals")
    expected = str(config.get("value") or "").strip()

    if field == "conversation_status":
        return compare(conversation.status, expected, operator)
    if field == "assigned_user":
        actual = "" if conversation.assigned_user_id is None else str(conversation.assigned_user_id)
        return compare(actual, expected, operator)
    if field == "tag":
        names = set(db.scalars(
            select(ContactTag.name)
            .join(TelegramContactTagLink, TelegramContactTagLink.tag_id == ContactTag.id)
            .where(TelegramContactTagLink.contact_id == conversation.contact_id)
        ).all())
        if operator == "empty": return not names
        if operator == "not_empty": return bool(names)
        matched = any(name.casefold() == expected.casefold() for name in names)
        return not matched if operator in {"not_equals", "not_contains"} else matched
    if field == "custom_field":
        field_key = str(config.get("field_key") or config.get("key") or expected).strip()
        compare_value = str(config.get("compare_value") if "compare_value" in config else ("" if field_key == expected else expected)).strip()
        row = db.execute(
            select(TelegramContactFieldValue.value_text)
            .join(ContactFieldDefinition, ContactFieldDefinition.id == TelegramContactFieldValue.field_id)
            .where(
                TelegramContactFieldValue.contact_id == conversation.contact_id,
                ContactFieldDefinition.key == field_key,
            )
        ).first()
        return compare((row[0] if row else "") or "", compare_value, operator)
    return False
