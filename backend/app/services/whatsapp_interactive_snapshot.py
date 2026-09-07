"""Persist the exact WhatsApp interactive choices shown to a subscriber.

This is installed as a small runtime patch so Live Chat can render a historical
snapshot of list/button options without changing the routing IDs used by flows.
"""
import json
from sqlalchemy import select

from app.flow_models import FlowNodeType
from app.models import Message, MessageDirection
from app.services.dynamic_lists import build_dynamic_rows
from app.services.flow_variables import render_whatsapp

_installed = False


def _json(value):
    try:
        return json.loads(value or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}


def _choice_nodes(by_id, out, interactive_id, handle):
    result = []
    for edge in out.get(interactive_id, []):
        if edge.source_handle != handle:
            continue
        node = by_id.get(edge.target_node_id)
        if node and node.node_type == FlowNodeType.BUTTON:
            result.append(node)
    return result


def _snapshot_rows(db, conversation, node, by_id, out, config):
    if str(config.get("row_generation") or "static").lower() == "dynamic":
        return [
            {"label": row["label"], "description": row.get("description") or ""}
            for row in build_dynamic_rows(db, "whatsapp", conversation.workspace_id, conversation.contact_id, config, 10)
        ]

    list_nodes = _choice_nodes(by_id, out, node.id, "list_messages")
    if list_nodes:
        template = next(
            (n for n in list_nodes if str(_json(n.config_json).get("row_generation") or "static").lower() == "dynamic"),
            None,
        )
        if template:
            cfg = _json(template.config_json)
            return [
                {"label": row["label"], "description": row.get("description") or ""}
                for row in build_dynamic_rows(db, "whatsapp", conversation.workspace_id, conversation.contact_id, cfg, 10)
            ]
        rows = []
        for choice in list_nodes[:10]:
            cfg = _json(choice.config_json)
            rows.append({
                "label": render_whatsapp(db, conversation, cfg.get("label") or choice.title or "Option").strip(),
                "description": render_whatsapp(db, conversation, cfg.get("description") or "").strip(),
            })
        return rows

    button_nodes = _choice_nodes(by_id, out, node.id, "buttons")
    return [
        {
            "label": render_whatsapp(db, conversation, _json(choice.config_json).get("label") or choice.title or "Button").strip(),
            "description": "",
        }
        for choice in button_nodes[:3]
    ]


def _attach_snapshot(db, conversation, node, by_id, out, config):
    rows = _snapshot_rows(db, conversation, node, by_id, out, config)
    if not rows:
        return
    message = db.scalar(
        select(Message)
        .where(
            Message.conversation_id == conversation.id,
            Message.direction == MessageDirection.OUTBOUND,
            Message.message_type == "interactive",
        )
        .order_by(Message.id.desc())
        .limit(1)
    )
    if not message:
        return
    payload = _json(message.payload_json)
    payload["_wa_connect"] = {
        "kind": "interactive_snapshot",
        "title": render_whatsapp(db, conversation, config.get("text") or "Choose an option").strip() or "Choose an option",
        "button_text": config.get("list_button_text") or "Choose",
        "section_title": config.get("list_section_title") or "Options",
        "options": rows,
    }
    message.payload_json = json.dumps(payload, ensure_ascii=False)
    db.flush()


def install():
    global _installed
    if _installed:
        return
    from app.services import flow_runtime

    original = flow_runtime._send_interactive

    async def wrapped(db, conversation, node, by_id, out, config):
        sent = await original(db, conversation, node, by_id, out, config)
        if sent:
            _attach_snapshot(db, conversation, node, by_id, out, config)
        return sent

    flow_runtime._send_interactive = wrapped
    _installed = True
