"""HTTP Request flow diagnostics shared by WhatsApp and Telegram.

The visual runtimes intentionally route a failed HTTP Request through the node's
``error`` output.  This module adds the operational layer around that behaviour:
HTTP calls are linked to the active Flow Run, success/failure is written to the
run event log, and a failed request with no connected Error path becomes an
explicit flow failure instead of silently ending the graph.
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
    return bool(
        db.scalar(
            select(FlowEdge.id).where(
                FlowEdge.flow_id == flow_id,
                FlowEdge.source_node_id == node_id,
                FlowEdge.source_handle == "error",
            ).limit(1)
        )
    )


def _failure_message(api: HttpApi | None, result: dict | None, fallback: str) -> str:
    name = (getattr(api, "name", None) or "HTTP Request").strip()
    result = result or {}
    status = result.get("status_code")
    error = str(result.get("error") or "").strip()
    suffix = error or (f"HTTP {status}" if status else fallback)
    return f"{name} failed: {suffix}"


async def _telegram_http(db, conversation, config):
    # Import lazily so this module can be installed during app startup without
    # introducing a circular dependency between the two flow runtimes.
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
        if not flow_id or not _has_error_path(db, flow_id, node_id):
            raise RuntimeError(f"{message}; no Error path is connected")
        return False

    result = await execute_http_api(
        db,
        api,
        lambda value: runtime._render(db, conversation, value),
        channel="telegram",
        workspace_id=conversation.workspace_id,
        contact_id=conversation.contact_id,
        flow_run_id=run_id,
        apply_mappings=True,
    )
    if result.get("success"):
        status = result.get("status_code")
        track_event(run_id, "success", node_id=node_id, node_type="http_request", message=f"{api.name} succeeded{f' (HTTP {status})' if status else ''}", run_status="running")
        return True

    message = _failure_message(api, result, "request failed")
    track_event(run_id, "error", node_id=node_id, node_type="http_request", message=message, run_status="running")
    if not flow_id or not _has_error_path(db, flow_id, node_id):
        raise RuntimeError(f"{message}; no Error path is connected")
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
        if not flow_id or not _has_error_path(db, flow_id, node_id):
            raise RuntimeError(f"{message}; no Error path is connected")
        return False

    result = await execute_http_api(
        db,
        api,
        lambda value: runtime.render_whatsapp(db, conversation, value),
        channel="whatsapp",
        workspace_id=conversation.workspace_id,
        contact_id=conversation.contact_id,
        flow_run_id=run_id,
        apply_mappings=True,
    )
    if result.get("success"):
        status = result.get("status_code")
        track_event(run_id, "success", node_id=node_id, node_type="http_request", message=f"{api.name} succeeded{f' (HTTP {status})' if status else ''}", run_status="running")
        return True

    message = _failure_message(api, result, "request failed")
    track_event(run_id, "error", node_id=node_id, node_type="http_request", message=message, run_status="running")
    if not flow_id or not _has_error_path(db, flow_id, node_id):
        raise RuntimeError(f"{message}; no Error path is connected")
    return False


def install() -> None:
    from app.services import flow_runtime, telegram_flow_runtime

    if getattr(flow_runtime, "_http_diagnostics_installed", False):
        return
    flow_runtime._http = _whatsapp_http
    telegram_flow_runtime._http = _telegram_http
    flow_runtime._http_diagnostics_installed = True
    telegram_flow_runtime._http_diagnostics_installed = True
