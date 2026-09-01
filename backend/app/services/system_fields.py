from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Contact, ContactFieldDefinition, ContactFieldType, ContactFieldValue, Workspace
from app.telegram_models import TelegramContact, TelegramContactFieldValue

SYSTEM_FIELDS = (
    ("name", "Name", ContactFieldType.TEXT, 10),
    ("subscriber_id", "Subscriber ID", ContactFieldType.TEXT, 20),
    ("source", "Source", ContactFieldType.TEXT, 30),
    ("location", "Location", ContactFieldType.TEXT, 40),
    ("latitude", "Latitude", ContactFieldType.NUMBER, 50),
    ("longitude", "Longitude", ContactFieldType.NUMBER, 60),
)
SYSTEM_FIELD_KEYS = {item[0] for item in SYSTEM_FIELDS}


def ensure_system_fields(db: Session, workspace_id: int) -> dict[str, ContactFieldDefinition]:
    existing = {f.key: f for f in db.scalars(select(ContactFieldDefinition).where(ContactFieldDefinition.workspace_id == workspace_id)).all()}
    changed = False
    for key, label, field_type, sort_order in SYSTEM_FIELDS:
        field = existing.get(key)
        if not field:
            field = ContactFieldDefinition(workspace_id=workspace_id, key=key, label=label, field_type=field_type, options_json="[]", required=False, active=True, sort_order=sort_order)
            db.add(field); db.flush(); existing[key] = field; changed = True
        elif not field.active:
            field.active = True; changed = True
    if changed: db.flush()
    return {key: existing[key] for key in SYSTEM_FIELD_KEYS}


def ensure_system_fields_all_workspaces(db: Session) -> None:
    for workspace_id in db.scalars(select(Workspace.id)).all():
        ensure_system_fields(db, workspace_id)


def _set_wa_value(db: Session, contact: Contact, key: str, value) -> None:
    if value is None or str(value).strip() == "": return
    field = ensure_system_fields(db, contact.workspace_id).get(key)
    if not field: return
    text = str(value).strip()
    row = db.scalar(select(ContactFieldValue).where(ContactFieldValue.contact_id == contact.id, ContactFieldValue.field_id == field.id))
    if row: row.value_text = text; row.updated_at = datetime.utcnow()
    else: db.add(ContactFieldValue(contact_id=contact.id, field_id=field.id, value_text=text))


def sync_whatsapp_system_fields(db: Session, contact: Contact, name: str | None = None, location: dict | None = None) -> None:
    _set_wa_value(db, contact, "subscriber_id", contact.wa_id)
    _set_wa_value(db, contact, "source", "whatsapp")
    _set_wa_value(db, contact, "name", name or contact.name)
    if location:
        lat, lng = location.get("latitude"), location.get("longitude")
        if lat is not None and lng is not None:
            _set_wa_value(db, contact, "latitude", lat); _set_wa_value(db, contact, "longitude", lng); _set_wa_value(db, contact, "location", f"{lat},{lng}")


def _set_tg_value(db: Session, contact: TelegramContact, key: str, value) -> None:
    if value is None or str(value).strip() == "": return
    field = ensure_system_fields(db, contact.workspace_id).get(key)
    if not field: return
    text = str(value).strip()
    row = db.scalar(select(TelegramContactFieldValue).where(TelegramContactFieldValue.contact_id == contact.id, TelegramContactFieldValue.field_id == field.id))
    if row: row.value_text = text; row.updated_at = datetime.utcnow()
    else: db.add(TelegramContactFieldValue(contact_id=contact.id, field_id=field.id, value_text=text))


def sync_telegram_system_fields(db: Session, contact: TelegramContact, phone_number: str | None = None, location: dict | None = None) -> None:
    name = " ".join(filter(None, [contact.first_name, contact.last_name])).strip()
    _set_tg_value(db, contact, "source", "telegram")
    _set_tg_value(db, contact, "name", name)
    if phone_number: _set_tg_value(db, contact, "subscriber_id", phone_number)
    if location:
        lat, lng = location.get("latitude"), location.get("longitude")
        if lat is not None and lng is not None:
            _set_tg_value(db, contact, "latitude", lat); _set_tg_value(db, contact, "longitude", lng); _set_tg_value(db, contact, "location", f"{lat},{lng}")
