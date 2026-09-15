import logging
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError, TimeoutError as SATimeoutError

from app.core.database import SessionLocal, engine
from app.flow_run_models import FlowRun, FlowRunEvent

logger = logging.getLogger(__name__)

OPEN_STATUSES = {"running", "waiting", "delayed"}


def utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


def _prepare_tracking_session(db):
    try:
        db.execute(text("SET SESSION innodb_lock_wait_timeout = 1"))
    except Exception:
        pass


def _is_lock_timeout(exc: Exception) -> bool:
    message = str(exc).lower()
    return "1205" in message or "lock wait timeout" in message or "deadlock" in message


def _tracking_failed(action: str, run_id: int | None, exc: Exception):
    if isinstance(exc, SATimeoutError):
        logger.warning("Skipping flow tracking %s for run %s because the DB pool is busy: %s", action, run_id, exc)
    elif _is_lock_timeout(exc):
        logger.warning("Skipping flow tracking %s for run %s because the row is busy: %s", action, run_id, exc)
    else:
        logger.exception("Flow tracking %s failed for run %s", action, run_id)


def _pool_saturated() -> bool:
    """Avoid observability work competing with application traffic.

    QueuePool exposes checkedout()/size()/overflow(). Tracking is best-effort,
    so when every normal/overflow slot is already checked out we skip it rather
    than joining a 30-second checkout queue and making a webhook failure worse.
    """
    pool = engine.pool
    try:
        size = pool.size()
        overflow = max(0, pool.overflow())
        return pool.checkedout() >= size + overflow and pool.checkedout() >= size
    except Exception:
        return False


def start_run(flow_id:int, workspace_id:int, channel:str, conversation_id:int, contact_id:int|None, node_id:int|None=None)->int|None:
    if _pool_saturated():
        logger.warning("Skipping flow tracking start because the DB pool is saturated flow=%s conversation=%s", flow_id, conversation_id)
        return None
    try:
        with SessionLocal() as db:
            _prepare_tracking_session(db)
            run=FlowRun(flow_id=flow_id,workspace_id=workspace_id,channel=channel,conversation_id=conversation_id,contact_id=contact_id,status="running",current_node_id=node_id,started_at=utcnow(),updated_at=utcnow())
            db.add(run);db.flush();db.add(FlowRunEvent(run_id=run.id,node_id=node_id,status="started",message="Flow started",created_at=utcnow()));db.commit();return int(run.id)
    except Exception as exc:
        _tracking_failed("start", None, exc)
        return None


def latest_open_run(flow_id:int, channel:str, conversation_id:int)->int|None:
    if _pool_saturated():
        return None
    try:
        with SessionLocal() as db:
            run=db.scalar(select(FlowRun).where(FlowRun.flow_id==flow_id,FlowRun.channel==channel,FlowRun.conversation_id==conversation_id,FlowRun.status.in_(OPEN_STATUSES)).order_by(FlowRun.started_at.desc(),FlowRun.id.desc()).limit(1))
            return int(run.id) if run else None
    except SATimeoutError as exc:
        _tracking_failed("latest", None, exc)
        return None


def event(run_id:int|None, event_status:str, node_id:int|None=None, node_type:str|None=None, message:str|None=None, run_status:str|None=None, status:str|None=None):
    if not run_id or _pool_saturated():return
    event_state=status or event_status
    with SessionLocal() as db:
        _prepare_tracking_session(db)
        try:
            run=db.get(FlowRun,run_id)
            if not run:return
            if run_status and run_status != "running":
                run.current_node_id=node_id if node_id is not None else run.current_node_id
                run.updated_at=utcnow()
                run.status=run_status
            db.add(FlowRunEvent(run_id=run.id,node_id=node_id,node_type=node_type,status=event_state,message=(message or None),created_at=utcnow()))
            db.commit()
        except Exception as exc:
            db.rollback();_tracking_failed("event", run_id, exc)


def complete(run_id:int|None, message:str="Flow completed"):
    if not run_id or _pool_saturated():return
    with SessionLocal() as db:
        _prepare_tracking_session(db)
        try:
            run=db.get(FlowRun,run_id)
            if not run:return
            now=utcnow();run.status="completed";run.current_node_id=None;run.updated_at=now;run.completed_at=now;db.add(FlowRunEvent(run_id=run.id,status="completed",message=message,created_at=now));db.commit()
        except Exception as exc:
            db.rollback();_tracking_failed("complete", run_id, exc)


def fail(run_id:int|None, exc:Exception, node_id:int|None=None, node_type:str|None=None):
    if not run_id or _pool_saturated():return
    with SessionLocal() as db:
        _prepare_tracking_session(db)
        try:
            run=db.get(FlowRun,run_id)
            if not run:return
            now=utcnow();run.status="failed";run.current_node_id=node_id;run.error_type=type(exc).__name__;run.error_message=str(exc)[:8000];run.updated_at=now;run.completed_at=now;db.add(FlowRunEvent(run_id=run.id,node_id=node_id,node_type=node_type,status="failed",message=str(exc)[:8000],created_at=now));db.commit()
        except Exception as tracking_exc:
            db.rollback();_tracking_failed("fail", run_id, tracking_exc)
