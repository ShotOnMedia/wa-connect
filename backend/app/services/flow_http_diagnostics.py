"""HTTP Request flow diagnostics shared by WhatsApp and Telegram.

Also snapshots WhatsApp Interactive Message choices into the stored live-chat body,
so agents can see the exact options that were available when a list/button message
was sent. The WhatsApp message itself remains unchanged.
"""
from __future__ import annotations

from sqlalchemy import select

from app.flow_models import FlowEdge
from app.http_api_models import HttpApi
from app.services.flow_tracking import event as track_event, latest_open_run
from app.services.http_api_executor import execute_http_api


def _has_error_path(db, flow_id: int, node_id: int | None) -> bool:
    if not node_id:
        return False
    return bool(db.scalar(select(FlowEdge.id).where(FlowEdge.flow_id == flow_id, FlowEdge.source_node_id == node_id, FlowEdge.source_handle == "error").limit(1)))


def _failure_message(api: HttpApi | None, result: dict | None, fallback: str) -> str:
    name = (getattr(api, "name", None) or "HTTP Request").strip()
    result = result or {}
    status = result.get("status_code")
    error = str(result.get("error") or "").strip()
    suffix = error or (f"HTTP {status}" if status else fallback)
    return f"{name} failed: {suffix}"


async def _telegram_http(db, conversation, config):
    from app.services import telegram_flow_runtime as runtime
    session = runtime._session(db, conversation.id)
    node_id = session.current_node_id if session else None
    flow_id = session.flow_id if session else None
    run_id = latest_open_run(flow_id, "telegram", conversation.id) if flow_id else None
    aid = config.get("http_api_id")
    api = db.get(HttpApi, int(aid)) if aid else None
    if not api or not api.active:
        message = _failure_message(api, None, "saved API is missing or inactive")
        track_event(run_id, "error", node_id=node_id, node_type="http_request", message=message, run_status="running")
        if not flow_id or not _has_error_path(db, flow_id, node_id): raise RuntimeError(f"{message}; no Error path is connected")
        return False
    result = await execute_http_api(db, api, lambda value: runtime._render(db, conversation, value), channel="telegram", workspace_id=conversation.workspace_id, contact_id=conversation.contact_id, flow_run_id=run_id, apply_mappings=True)
    if result.get("success"):
        status = result.get("status_code")
        track_event(run_id, "success", node_id=node_id, node_type="http_request", message=f"{api.name} succeeded{f' (HTTP {status})' if status else ''}", run_status="running")
        return True
    message = _failure_message(api, result, "request failed")
    track_event(run_id, "error", node_id=node_id, node_type="http_request", message=message, run_status="running")
    if not flow_id or not _has_error_path(db, flow_id, node_id): raise RuntimeError(f"{message}; no Error path is connected")
    return False


async def _whatsapp_http(db, conversation, config):
    from app.services import flow_runtime as runtime
    session = runtime._session(db, conversation.id)
    node_id = session.current_node_id if session else None
    flow_id = session.flow_id if session else None
    run_id = latest_open_run(flow_id, "whatsapp", conversation.id) if flow_id else None
    aid = config.get("http_api_id")
    api = db.get(HttpApi, int(aid)) if aid else None
    if not api or not api.active:
        message = _failure_message(api, None, "saved API is missing or inactive")
        track_event(run_id, "error", node_id=node_id, node_type="http_request", message=message, run_status="running")
        if not flow_id or not _has_error_path(db, flow_id, node_id): raise RuntimeError(f"{message}; no Error path is connected")
        return False
    result = await execute_http_api(db, api, lambda value: runtime.render_whatsapp(db, conversation, value), channel="whatsapp", workspace_id=conversation.workspace_id, contact_id=conversation.contact_id, flow_run_id=run_id, apply_mappings=True)
    if result.get("success"):
        status = result.get("status_code")
        track_event(run_id, "success", node_id=node_id, node_type="http_request", message=f"{api.name} succeeded{f' (HTTP {status})' if status else ''}", run_status="running")
        return True
    message = _failure_message(api, result, "request failed")
    track_event(run_id, "error", node_id=node_id, node_type="http_request", message=message, run_status="running")
    if not flow_id or not _has_error_path(db, flow_id, node_id): raise RuntimeError(f"{message}; no Error path is connected")
    return False


def _whatsapp_choice_snapshot(runtime, db, conversation, node, by_id, out, config):
    rows = []
    list_nodes = runtime._choice_nodes(by_id, out, node.id, "list_messages")
    button_nodes = runtime._choice_nodes(by_id, out, node.id, "buttons")
    if str(config.get("row_generation") or "static").lower() == "dynamic":
        rows = runtime.build_dynamic_rows(db, "whatsapp", conversation.workspace_id, conversation.contact_id, config, 10)
    elif list_nodes:
        template = next((n for n in list_nodes if str(runtime._json(n.config_json).get("row_generation") or "static").lower() == "dynamic"), None)
        if template:
            cfg = runtime._json(template.config_json)
            rows = runtime.build_dynamic_rows(db, "whatsapp", conversation.workspace_id, conversation.contact_id, cfg, 10)
        else:
            for item in list_nodes[:10]:
                cfg = runtime._json(item.config_json)
                rows.append({"label": runtime.render_whatsapp(db, conversation, cfg.get("label") or item.title or "Option").strip(), "description": runtime.render_whatsapp(db, conversation, cfg.get("description") or "").strip()})
    elif button_nodes:
        for item in button_nodes[:3]:
            cfg = runtime._json(item.config_json)
            rows.append({"label": runtime.render_whatsapp(db, conversation, cfg.get("label") or item.title or "Button").strip(), "description": ""})
    return rows


def _make_whatsapp_interactive_wrapper(runtime, original):
    async def wrapped(db, conversation, node, by_id, out, config):
        rows = _whatsapp_choice_snapshot(runtime, db, conversation, node, by_id, out, config)
        result = await original(db, conversation, node, by_id, out, config)
        if result and rows:
            message = db.scalars(select(runtime.Message).where(runtime.Message.conversation_id == conversation.id, runtime.Message.direction == runtime.MessageDirection.OUTBOUND, runtime.Message.message_type == "interactive").order_by(runtime.Message.id.desc()).limit(1)).first()
            if message:
                prompt = str(message.body or runtime.render_whatsapp(db, conversation, config.get("text") or "Choose an option")).strip()
                options = []
                for row in rows:
                    label = str(row.get("label") or "Option").strip()
                    description = str(row.get("description") or "").strip()
                    options.append(f"• {label}" + (f" — {description}" if description else ""))
                message.body = prompt + "\n\nOptions shown:\n" + "\n".join(options)
                db.flush()
        return result
    return wrapped


def install() -> None:
    from app.services import flow_runtime, telegram_flow_runtime
    if getattr(flow_runtime, "_http_diagnostics_installed", False): return
    flow_runtime._http = _whatsapp_http
    telegram_flow_runtime._http = _telegram_http
    flow_runtime._send_interactive = _make_whatsapp_interactive_wrapper(flow_runtime, flow_runtime._send_interactive)
    flow_runtime._http_diagnostics_installed = True
    telegram_flow_runtime._http_diagnostics_installed = True
