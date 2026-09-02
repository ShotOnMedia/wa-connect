from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.flow_models import Flow, FlowStatus
from app.services.flow_tracking import complete as track_complete, event as track_event, fail as track_fail, start_run
from app.services.flow_runtime import _run as run_whatsapp_graph, _session as whatsapp_session, _start_session as start_whatsapp_session
from app.services.telegram_flow_runtime import _run_flow as run_telegram_graph, _session as telegram_session


async def trigger_whatsapp_flow(db: Session, flow: Flow, conversation, restart: bool = True):
    if flow.status != FlowStatus.ACTIVE:
        raise RuntimeError("Flow must be active before it can be triggered")
    existing = whatsapp_session(db, conversation.id)
    if existing and existing.status.value == "waiting" and not restart:
        raise RuntimeError("Subscriber already has a waiting flow session")
    synthetic = SimpleNamespace(id=None, body=None, message_type="api")
    session = start_whatsapp_session(db, conversation, flow, synthetic)
    run_id = start_run(flow.id, flow.workspace_id, "whatsapp", conversation.id, conversation.contact_id, None)
    try:
        result = await run_whatsapp_graph(db, flow, conversation, session)
        if session.status.value == "completed":
            track_complete(run_id)
        elif session.status.value == "waiting":
            state = "delayed" if session.waiting_for == "delay" else "waiting"
            track_event(run_id, state, node_id=session.current_node_id, status=state, message=f"Waiting for {session.waiting_for}", run_status=state)
        return result, session
    except Exception as exc:
        track_fail(run_id, exc, session.current_node_id)
        raise


async def trigger_telegram_flow(db: Session, flow: Flow, conversation, restart: bool = True):
    if flow.status != FlowStatus.ACTIVE:
        raise RuntimeError("Flow must be active before it can be triggered")
    existing = telegram_session(db, conversation.id)
    if existing and existing.status == "waiting" and not restart:
        raise RuntimeError("Subscriber already has a waiting flow session")
    synthetic = SimpleNamespace(id=None, body=None, message_type="api")
    run_id = start_run(flow.id, flow.workspace_id, "telegram", conversation.id, conversation.contact_id, None)
    try:
        result = await run_telegram_graph(db, flow, conversation, synthetic)
        session = telegram_session(db, conversation.id)
        if session and session.status == "completed":
            track_complete(run_id)
        elif session and session.status == "waiting":
            state = "delayed" if session.waiting_for == "delay" else "waiting"
            track_event(run_id, state, node_id=session.current_node_id, status=state, message=f"Waiting for {session.waiting_for}", run_status=state)
        return result, session
    except Exception as exc:
        session = telegram_session(db, conversation.id)
        track_fail(run_id, exc, session.current_node_id if session else None)
        raise
