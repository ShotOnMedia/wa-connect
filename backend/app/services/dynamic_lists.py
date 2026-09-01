import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ContactFieldDefinition, ContactFieldValue
from app.telegram_models import TelegramContactFieldValue


def _field_value(db: Session, channel: str, contact_id: int, field_id: int):
    model = TelegramContactFieldValue if channel == "telegram" else ContactFieldValue
    row = db.scalar(select(model).where(model.contact_id == contact_id, model.field_id == field_id))
    return row.value_text if row else None


def _field(db: Session, workspace_id: int, field_id: int | str | None = None, field_key: str | None = None):
    """Resolve a field by stable key first, then fall back to its database id."""
    key = str(field_key or "").strip()
    if key:
        found = db.scalar(select(ContactFieldDefinition).where(
            ContactFieldDefinition.workspace_id == workspace_id,
            ContactFieldDefinition.key == key,
            ContactFieldDefinition.active.is_(True),
        ))
        if found:
            return found
    if not field_id:
        return None
    try:
        fid = int(field_id)
    except (TypeError, ValueError):
        return None
    return db.scalar(select(ContactFieldDefinition).where(
        ContactFieldDefinition.id == fid,
        ContactFieldDefinition.workspace_id == workspace_id,
        ContactFieldDefinition.active.is_(True),
    ))


def _path(value: Any, path: str):
    current = value
    path = str(path or "").strip()
    if not path or path == "$":
        return current
    if path.startswith("$."):
        path = path[2:]
    for part in [p for p in re.split(r"\.(?![^\[]*\])", path) if p]:
        match = re.fullmatch(r"([^\[]+)(?:\[(\d+)\])?", part)
        if not match:
            return None
        key, index = match.groups()
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return None
        if index is not None:
            if not isinstance(current, list) or int(index) >= len(current):
                return None
            current = current[int(index)]
    return current


def _items(value: Any):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        if value and all(str(k).isdigit() for k in value):
            return [value[k] for k in sorted(value, key=lambda k: int(k))]
        return list(value.values())
    return []


def _item_value(item: Any, path: str):
    if not str(path or "").strip():
        return item
    return _path(item, path)


def _format(template: str, item: Any):
    text = str(template or "")
    def repl(match):
        value = _item_value(item, match.group(1))
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)
    return re.sub(r"\{\{\s*item\.([^}]+?)\s*\}\}", repl, text)


def build_dynamic_rows(db: Session, channel: str, workspace_id: int, contact_id: int, config: dict, limit: int = 10):
    if str(config.get("row_generation") or "static").lower() != "dynamic":
        return []
    source = _field(db, workspace_id, config.get("dynamic_source_field_id"), config.get("dynamic_source_field_key"))
    if not source:
        return []
    raw = _field_value(db, channel, contact_id, source.id)
    if raw in (None, ""):
        return []
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    data = _path(data, config.get("dynamic_array_path") or "")
    rows = []
    for index, item in enumerate(_items(data)[:limit]):
        title_path = config.get("dynamic_title_path") or ""
        value_path = config.get("dynamic_value_path") or title_path
        title = _item_value(item, title_path)
        selected = _item_value(item, value_path)
        if title is None:
            title = item if not isinstance(item, (dict, list)) else f"Option {index + 1}"
        if selected is None:
            selected = title
        description = _format(config.get("dynamic_description") or "", item)
        rows.append({"index": index,"label": str(title)[:200],"description": description[:200],"selected": selected,"item": item})
    return rows


def save_dynamic_selection(db: Session, channel: str, workspace_id: int, contact_id: int, config: dict, row: dict):
    target = _field(db, workspace_id, config.get("dynamic_save_field_id"), config.get("dynamic_save_field_key"))
    if not target:
        return False
    value = row.get("item") if config.get("dynamic_save_entire_object") else row.get("selected")
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else (None if value is None else str(value))
    model = TelegramContactFieldValue if channel == "telegram" else ContactFieldValue
    existing = db.scalar(select(model).where(model.contact_id == contact_id, model.field_id == target.id))
    if existing:
        existing.value_text = text
        existing.updated_at = datetime.utcnow()
    else:
        db.add(model(contact_id=contact_id, field_id=target.id, value_text=text))
    db.flush()
    return True


def dynamic_selection_value(prefix: str, interactive_node_id: int, index: int) -> str:
    return f"{prefix}:{interactive_node_id}:{index}"


def parse_dynamic_selection(value: str, prefix: str):
    match = re.fullmatch(rf"{re.escape(prefix)}:(\d+):(\d+)", str(value or "").strip())
    return (int(match.group(1)), int(match.group(2))) if match else None
