import json

from sqlalchemy import select

from app.default_action_models import DefaultAction
from app.flow_models import Flow, FlowStatus


TYPE_MAP = {
    "location": "location",
    "photo": "image",
    "image": "image",
    "sticker": "image",
    "video": "video",
    "voice": "audio",
    "audio": "audio",
    "document": "document",
    "file": "document",
    "contact": "contact",
    "contacts": "contact",
}
MEDIA_TYPES = {"image", "video", "audio", "document"}


def action_type_for(inbound):
    message_type = str(getattr(inbound, "message_type", "") or "").strip().lower()
    return TYPE_MAP.get(message_type, "unmatched_text" if message_type == "text" else None)


def default_flow(db, workspace_id: int, channel: str, inbound):
    action_type = action_type_for(inbound)
    if not action_type:
        return None
    row = db.scalar(select(DefaultAction).where(DefaultAction.workspace_id == workspace_id, DefaultAction.channel == channel, DefaultAction.action_type == action_type, DefaultAction.enabled.is_(True)))
    if not row or not row.flow_id:
        return None
    flow = db.get(Flow, row.flow_id)
    return flow if flow and flow.status == FlowStatus.ACTIVE else None


def _payload(inbound):
    raw = getattr(inbound, "payload_json", None)
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _location_from_mapping(payload):
    """Extract latitude/longitude from stored Meta, Telegram, or complete webhook JSON."""
    if not isinstance(payload, dict):
        return None, None
    location = payload.get("location") or {}
    if isinstance(location, dict):
        lat, lng = location.get("latitude"), location.get("longitude")
        if lat is not None and lng is not None:
            return lat, lng
    message = payload.get("message") or {}
    if isinstance(message, dict):
        location = message.get("location") or {}
        if isinstance(location, dict):
            lat, lng = location.get("latitude"), location.get("longitude")
            if lat is not None and lng is not None:
                return lat, lng
    try:
        entry = (payload.get("entry") or [{}])[0]
        change = (entry.get("changes") or [{}])[0]
        value = change.get("value") or {}
        wam = (value.get("messages") or [{}])[0]
        location = wam.get("location") or {}
        return location.get("latitude"), location.get("longitude")
    except (AttributeError, IndexError, TypeError):
        return None, None


def _telegram_media(message, kind):
    if not isinstance(message, dict):
        return {}
    if kind == "photo":
        photos = message.get("photo") or []
        return photos[-1] if photos and isinstance(photos[-1], dict) else {}
    item = message.get(kind) or {}
    return item if isinstance(item, dict) else {}


def _media_values(payload, channel, raw_kind):
    """Return one channel-neutral media variable set after durable persistence."""
    item = {}
    caption = None
    if channel == "telegram":
        message = payload.get("message") or {}
        item = _telegram_media(message, raw_kind)
        caption = message.get("caption")
    else:
        item = payload.get(raw_kind) or {}
        if not isinstance(item, dict):
            item = {}
        caption = item.get("caption")

    url = item.get("wa_connect_url") or item.get("url")
    mime_type = item.get("mime_type") or item.get("content_type")
    filename = item.get("file_name") or item.get("filename")
    file_size = item.get("file_size")
    provider_id = item.get("file_id") if channel == "telegram" else item.get("id")

    values = {}
    if url:
        values["url"] = str(url)
        values["media_url"] = str(url)
    if mime_type:
        values["mime_type"] = str(mime_type)
    if filename:
        values["filename"] = str(filename)
    if file_size is not None:
        values["file_size"] = str(file_size)
    if caption:
        values["caption"] = str(caption)
    if provider_id:
        values["media_id"] = str(provider_id)
    return values


def _contact_values(payload, channel):
    contact = {}
    if channel == "telegram":
        message = payload.get("message") or {}
        contact = message.get("contact") or {}
        if not isinstance(contact, dict):
            contact = {}
        first = str(contact.get("first_name") or "").strip()
        last = str(contact.get("last_name") or "").strip()
        name = " ".join(part for part in (first, last) if part)
        phone = contact.get("phone_number")
        user_id = contact.get("user_id")
        vcard = contact.get("vcard")
    else:
        contacts = payload.get("contacts") or []
        contact = contacts[0] if contacts and isinstance(contacts[0], dict) else {}
        name_obj = contact.get("name") or {}
        name = name_obj.get("formatted_name") if isinstance(name_obj, dict) else None
        phones = contact.get("phones") or []
        first_phone = phones[0] if phones and isinstance(phones[0], dict) else {}
        phone = first_phone.get("phone") or first_phone.get("wa_id")
        user_id = first_phone.get("wa_id")
        vcard = None

    values = {"contact_json": json.dumps(contact, ensure_ascii=False, separators=(",", ":"))}
    if name:
        values["contact_name"] = str(name)
    if phone:
        values["contact_phone"] = str(phone)
    if user_id is not None:
        values["contact_user_id"] = str(user_id)
    if vcard:
        values["contact_vcard"] = str(vcard)
    return values


def inbound_values(inbound, channel: str):
    channel = str(channel or "").lower()
    raw_kind = str(getattr(inbound, "message_type", "") or "").strip().lower()
    action_type = action_type_for(inbound) or raw_kind or "unknown"
    values = {"type": action_type, "channel": channel}
    payload = _payload(inbound)

    if action_type == "location":
        lat, lng = _location_from_mapping(payload)
        if lat is None or lng is None:
            raw_body = getattr(inbound, "body", None)
            try:
                body = json.loads(raw_body or "{}") if isinstance(raw_body, str) else (raw_body or {})
                lat, lng = _location_from_mapping({"location": body})
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        if lat is not None and lng is not None:
            values.update({"latitude": str(lat), "longitude": str(lng), "location": f"{lat},{lng}"})
    elif action_type in MEDIA_TYPES:
        values.update(_media_values(payload, channel, raw_kind))
    elif action_type == "contact":
        values.update(_contact_values(payload, channel))
    elif action_type == "unmatched_text":
        body = getattr(inbound, "body", None)
        if body is not None:
            values["text"] = str(body)

    return values


def attach_inbound_values(inbound, channel: str):
    # Transient runtime context; deliberately not persisted on the message row.
    inbound._default_action_values = inbound_values(inbound, channel)