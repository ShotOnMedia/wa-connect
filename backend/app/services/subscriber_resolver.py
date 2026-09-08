"""Channel-aware subscriber resolution for the Developer API.

Supported selectors:
- telegram:<internal contact id> / whatsapp:<internal contact id>
- telegram_user:<Telegram user id>
- wa_id:<WhatsApp id/phone>
- subscriber_id:<value of the subscriber_id custom field>
- with an explicit channel, bare values fall back through internal id, native
  channel id, then subscriber_id.
"""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Contact, ContactFieldDefinition, ContactFieldValue
from app.telegram_models import TelegramBot, TelegramContact, TelegramContactFieldValue


def telegram_workspace_ids(db: Session) -> set[int]:
    return {int(v) for v in db.scalars(select(TelegramBot.workspace_id).where(TelegramBot.active.is_(True)).distinct()).all()}


def _custom_field_contact(db: Session, channel: str, workspace_ids: set[int], key: str, value: str):
    if not workspace_ids:
        return None
    definition_ids = list(db.scalars(select(ContactFieldDefinition.id).where(
        ContactFieldDefinition.workspace_id.in_(workspace_ids),
        ContactFieldDefinition.key == key,
        ContactFieldDefinition.active.is_(True),
    )).all())
    if not definition_ids:
        return None
    value_model = TelegramContactFieldValue if channel == "telegram" else ContactFieldValue
    contact_model = TelegramContact if channel == "telegram" else Contact
    contact_ids = list(db.scalars(select(value_model.contact_id).where(
        value_model.field_id.in_(definition_ids),
        value_model.value_text == str(value),
    ).limit(2)).all())
    if len(set(contact_ids)) > 1:
        raise HTTPException(409, f"{key} matches more than one {channel} subscriber")
    if not contact_ids:
        return None
    return db.scalar(select(contact_model).where(contact_model.id == contact_ids[0], contact_model.workspace_id.in_(workspace_ids)))


def resolve_subscriber(db: Session, primary_workspace_id: int, subscriber: str, channel: str | None = None):
    raw = str(subscriber).strip()
    if not raw:
        raise HTTPException(422, "subscriber is required")
    if channel not in {None, "whatsapp", "telegram"}:
        raise HTTPException(422, "channel must be whatsapp or telegram")

    tg_ids = telegram_workspace_ids(db)
    wa_ids = {int(primary_workspace_id)}

    if ":" in raw:
        kind, ident = raw.split(":", 1)
        kind = kind.strip().lower()
        ident = ident.strip()
        if kind in {"telegram", "whatsapp"}:
            if channel and channel != kind:
                raise HTTPException(422, f"channel is {channel}, but subscriber reference belongs to {kind}")
            try:
                internal_id = int(ident)
            except ValueError as exc:
                raise HTTPException(422, "Invalid subscriber reference") from exc
            model = TelegramContact if kind == "telegram" else Contact
            ids = tg_ids if kind == "telegram" else wa_ids
            row = db.scalar(select(model).where(model.id == internal_id, model.workspace_id.in_(ids))) if ids else None
            if not row:
                raise HTTPException(404, "Subscriber not found")
            return kind, row
        if kind == "telegram_user":
            if channel and channel != "telegram": raise HTTPException(422, "telegram_user selector requires channel telegram")
            try: telegram_id = int(ident)
            except ValueError as exc: raise HTTPException(422, "Invalid Telegram user ID") from exc
            row = db.scalar(select(TelegramContact).where(TelegramContact.telegram_user_id == telegram_id, TelegramContact.workspace_id.in_(tg_ids))) if tg_ids else None
            if not row: raise HTTPException(404, "Subscriber not found")
            return "telegram", row
        if kind == "wa_id":
            if channel and channel != "whatsapp": raise HTTPException(422, "wa_id selector requires channel whatsapp")
            wa = "".join(ch for ch in ident if ch.isdigit())
            row = db.scalar(select(Contact).where(Contact.wa_id == wa, Contact.workspace_id == primary_workspace_id))
            if not row: raise HTTPException(404, "Subscriber not found")
            return "whatsapp", row
        if kind == "subscriber_id":
            channels = [channel] if channel else ["whatsapp", "telegram"]
            matches = []
            for target in channels:
                ids = tg_ids if target == "telegram" else wa_ids
                row = _custom_field_contact(db, target, ids, "subscriber_id", ident)
                if row: matches.append((target, row))
            if len(matches) > 1:
                raise HTTPException(409, "subscriber_id exists on more than one channel; provide channel")
            if not matches: raise HTTPException(404, "Subscriber not found")
            return matches[0]
        raise HTTPException(422, "Unknown subscriber selector. Use telegram:, whatsapp:, telegram_user:, wa_id:, or subscriber_id:")

    if channel is None:
        raise HTTPException(422, "channel is required for a bare subscriber value; alternatively use an explicit selector prefix")

    ids = tg_ids if channel == "telegram" else wa_ids
    model = TelegramContact if channel == "telegram" else Contact
    try: numeric = int(raw)
    except ValueError: numeric = None
    if numeric is not None:
        row = db.scalar(select(model).where(model.id == numeric, model.workspace_id.in_(ids))) if ids else None
        if row: return channel, row
    if channel == "telegram" and numeric is not None:
        row = db.scalar(select(TelegramContact).where(TelegramContact.telegram_user_id == numeric, TelegramContact.workspace_id.in_(tg_ids))) if tg_ids else None
        if row: return channel, row
    if channel == "whatsapp":
        wa = "".join(ch for ch in raw if ch.isdigit())
        row = db.scalar(select(Contact).where(Contact.wa_id == wa, Contact.workspace_id == primary_workspace_id)) if wa else None
        if row: return channel, row
    row = _custom_field_contact(db, channel, ids, "subscriber_id", raw)
    if row: return channel, row
    raise HTTPException(404, "Subscriber not found")
