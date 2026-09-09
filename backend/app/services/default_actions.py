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


def inbound_values(inbound, channel: str):
    values = {"type": action_type_for(inbound) or str(getattr(inbound, "message_type", "") or "unknown"), "channel": channel}
    if values["type"] == "location":
        lat = lng = None
        try:
            payload = json.loads(getattr(inbound, "payload_json", None) or "{}")
            message = payload.get("message") or {}
            location = message.get("location") or {}
            lat, lng = location.get("latitude"), location.get("longitude")
            if lat is None or lng is None:
                entry = ((payload.get("entry") or [{}])[0].get("changes") or [{}])[0].get("value") or {}
                wam = (entry.get("messages") or [{}])[0]; location = wam.get("location") or {}
                lat, lng = location.get("latitude"), location.get("longitude")
        except Exception:
            pass
        if lat is not None and lng is not None:
            values.update({"latitude": str(lat), "longitude": str(lng), "location": f"{lat},{lng}"})
    return values


def attach_inbound_values(inbound, channel: str):
    # Transient runtime context; deliberately not persisted on the message row.
    inbound._default_action_values = inbound_values(inbound, channel)
