from datetime import UTC, datetime

from sqlalchemy import select

from app.core.database import SessionLocal
from app.flow_run_models import FlowRun, FlowRunEvent

OPEN_STATUSES = {"running", "waiting", "delayed"}


def utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


def start_run(flow_id:int, workspace_id:int, channel:str, conversation_id:int, contact_id:int|None, node_id:int|None=None)->int:
    with SessionLocal() as db:
        run=FlowRun(flow_id=flow_id,workspace_id=workspace_id,channel=channel,conversation_id=conversation_id,contact_id=contact_id,status="running",current_node_id=node_id,started_at=utcnow(),updated_at=utcnow())
        db.add(run);db.flush();db.add(FlowRunEvent(run_id=run.id,node_id=node_id,status="started",message="Flow started",created_at=utcnow()));db.commit();return int(run.id)


def latest_open_run(flow_id:int, channel:str, conversation_id:int)->int|None:
    with SessionLocal() as db:
        run=db.scalar(select(FlowRun).where(FlowRun.flow_id==flow_id,FlowRun.channel==channel,FlowRun.conversation_id==conversation_id,FlowRun.status.in_(OPEN_STATUSES)).order_by(FlowRun.started_at.desc(),FlowRun.id.desc()).limit(1))
        return int(run.id) if run else None


def event(run_id:int|None, event_status:str, node_id:int|None=None, node_type:str|None=None, message:str|None=None, run_status:str|None=None, status:str|None=None):
    if not run_id:return
    event_state=status or event_status
    with SessionLocal() as db:
        run=db.get(FlowRun,run_id)
        if not run:return
        run.current_node_id=node_id if node_id is not None else run.current_node_id
        run.updated_at=utcnow()
        if run_status:run.status=run_status
        db.add(FlowRunEvent(run_id=run.id,node_id=node_id,node_type=node_type,status=event_state,message=(message or None),created_at=utcnow()))
        db.commit()


def complete(run_id:int|None, message:str="Flow completed"):
    if not run_id:return
    with SessionLocal() as db:
        run=db.get(FlowRun,run_id)
        if not run:return
        now=utcnow();run.status="completed";run.current_node_id=None;run.updated_at=now;run.completed_at=now;db.add(FlowRunEvent(run_id=run.id,status="completed",message=message,created_at=now));db.commit()


def fail(run_id:int|None, exc:Exception, node_id:int|None=None, node_type:str|None=None):
    if not run_id:return
    with SessionLocal() as db:
        run=db.get(FlowRun,run_id)
        if not run:return
        now=utcnow();run.status="failed";run.current_node_id=node_id;run.error_type=type(exc).__name__;run.error_message=str(exc)[:8000];run.updated_at=now;run.completed_at=now;db.add(FlowRunEvent(run_id=run.id,node_id=node_id,node_type=node_type,status="failed",message=str(exc)[:8000],created_at=now));db.commit()
