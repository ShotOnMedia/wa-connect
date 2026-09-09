import json

from sqlalchemy import select

from app.default_action_models import DefaultAction
from app.flow_models import Flow, FlowStatus


TYPE_MAP = {
    "location": "location",
    "photo": "image",
    "image": "image",
    "video": "video",
    "voice": "audio",
    "audio": "audio",
    "document": "document",
    "file": "document",
    "contact": "contact",
    "contacts": "contact",
}


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


def _location_from_mapping(payload):
    """Extract latitude/longitude from either stored Meta message or webhook JSON."""
    if not isinstance(payload, dict):
        return None, None

    # WhatsApp messages are persisted as the individual Meta message object:
    # {"type":"location", "location":{"latitude":..., "longitude":...}}
    location = payload.get("location") or {}
    if isinstance(location, dict):
        lat, lng = location.get("latitude"), location.get("longitude")
        if lat is not None and lng is not None:
            return lat, lng

    # Telegram/default-action helpers may carry a nested message object.
    message = payload.get("message") or {}
    if isinstance(message, dict):
        location = message.get("location") or {}
        if isinstance(location, dict):
            lat, lng = location.get("latitude"), location.get("longitude")
            if lat is not None and lng is not None:
                return lat, lng

    # Also accept a complete Meta webhook payload for callers that have not yet
    # reduced it to the stored message object.
    try:
        entry = (payload.get("entry") or [{}])[0]
        change = (entry.get("changes") or [{}])[0]
        value = change.get("value") or {}
        wam = (value.get("messages") or [{}])[0]
        location = wam.get("location") or {}
        return location.get("latitude"), location.get("longitude")
    except (AttributeError, IndexError, TypeError):
        return None, None


def inbound_values(inbound, channel: str):
    values = {"type": action_type_for(inbound) or str(getattr(inbound, "message_type", "") or "unknown"), "channel": channel}
    if values["type"] == "location":
        lat = lng = None
        raw_payload = getattr(inbound, "payload_json", None)
        try:
            payload = json.loads(raw_payload or "{}") if isinstance(raw_payload, str) else (raw_payload or {})
            lat, lng = _location_from_mapping(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            pass

        # The human-readable body for WhatsApp location messages is itself the
        # location object, so retain it as a safe fallback for older rows/tests.
        if lat is None or lng is None:
            raw_body = getattr(inbound, "body", None)
            try:
                body = json.loads(raw_body or "{}") if isinstance(raw_body, str) else (raw_body or {})
                lat, lng = _location_from_mapping({"location": body})
            except (TypeError, ValueError, json.JSONDecodeError):
                pass

        if lat is not None and lng is not None:
            values.update({"latitude": str(lat), "longitude": str(lng), "location": f"{lat},{lng}"})
    return values


def attach_inbound_values(inbound, channel: str):
    # Transient runtime context; deliberately not persisted on the message row.
    inbound._default_action_values = inbound_values(inbound, channel)