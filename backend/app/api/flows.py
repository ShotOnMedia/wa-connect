import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.core.security import require_user
from app.flow_channel_models import FlowChannelTarget
from app.flow_models import Flow, FlowEdge, FlowNode, FlowStatus, FlowStep
from app.flow_run_models import FlowRun, FlowRunEvent
from app.flow_schemas import (
    FlowCreate, FlowEdgeCreate, FlowEdgeOut, FlowGraphOut, FlowNodeCreate, FlowNodeOut,
    FlowNodeUpdate, FlowOut, FlowReorderRequest, FlowStepCreate, FlowStepOut,
    FlowStepUpdate, FlowUpdate,
)
from app.models import User, Workspace
from app.telegram_models import TelegramBot

router = APIRouter(prefix="/flows", tags=["flows"])


def _require_manager(user: User) -> None:
    if user.role.value not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="Only admins and managers can manage flows")


def _workspace_id(db: Session, channel: str = "whatsapp") -> int:
    if channel == "telegram":
        workspace_id = db.scalar(select(TelegramBot.workspace_id).where(TelegramBot.active.is_(True)).order_by(TelegramBot.id.asc()).limit(1))
        if workspace_id is not None: return int(workspace_id)
        raise HTTPException(status_code=400, detail="Connect a Telegram bot before creating Telegram flows")
    workspace_id = db.scalar(select(Workspace.id).where(Workspace.active.is_(True)).order_by(Workspace.id.asc()).limit(1))
    if workspace_id is None: raise HTTPException(status_code=400, detail="Connect a workspace before creating flows")
    return int(workspace_id)


def _json(value: str | None) -> dict:
    try: return json.loads(value or "{}")
    except json.JSONDecodeError: return {}


def _step_out(step: FlowStep) -> FlowStepOut:
    return FlowStepOut(id=step.id, step_type=step.step_type, sort_order=step.sort_order, config=_json(step.config_json), created_at=step.created_at, updated_at=step.updated_at)


def _flow_out(flow: Flow) -> FlowOut:
    steps = [_step_out(step) for step in sorted(flow.steps, key=lambda item: item.sort_order)]
    return FlowOut(id=flow.id, workspace_id=flow.workspace_id, name=flow.name, description=flow.description, status=flow.status, trigger_type=flow.trigger_type, trigger_value=flow.trigger_value, stop_on_reply=flow.stop_on_reply, step_count=len(steps), steps=steps, created_at=flow.created_at, updated_at=flow.updated_at)


def _node_out(node: FlowNode) -> FlowNodeOut:
    return FlowNodeOut(id=node.id, node_type=node.node_type, title=node.title, config=_json(node.config_json), position_x=node.position_x, position_y=node.position_y)


def _edge_out(edge: FlowEdge) -> FlowEdgeOut:
    return FlowEdgeOut(id=edge.id, source_node_id=edge.source_node_id, source_handle=edge.source_handle, target_node_id=edge.target_node_id, target_handle=edge.target_handle, sort_order=edge.sort_order)


def _get_flow(flow_id: int, db: Session) -> Flow:
    flow = db.scalar(select(Flow).options(selectinload(Flow.steps)).where(Flow.id == flow_id))
    if not flow: raise HTTPException(status_code=404, detail="Flow not found")
    return flow


def _target_channel(db: Session, flow_id: int) -> str:
    target = db.scalar(select(FlowChannelTarget.channel).where(FlowChannelTarget.flow_id == flow_id))
    return target or "whatsapp"


@router.get("", response_model=list[FlowOut])
def list_flows(flow_status: FlowStatus | None = Query(default=None, alias="status"), channel: str = Query(default="whatsapp", pattern="^(whatsapp|telegram|all)$"), db: Session = Depends(get_db)):
    stmt = select(Flow).options(selectinload(Flow.steps)).order_by(Flow.updated_at.desc(), Flow.name.asc())
    if flow_status is not None: stmt = stmt.where(Flow.status == flow_status)
    flows = db.scalars(stmt).all()
    if channel != "all": flows = [flow for flow in flows if _target_channel(db, flow.id) == channel]
    return [_flow_out(flow) for flow in flows]


@router.post("", response_model=FlowOut, status_code=status.HTTP_201_CREATED)
def create_flow(payload: FlowCreate, db: Session = Depends(get_db), user: User = Depends(require_user)):
    _require_manager(user); workspace_id = _workspace_id(db, payload.channel)
    duplicate = db.scalar(select(Flow.id).where(Flow.workspace_id == workspace_id, func.lower(Flow.name) == payload.name.lower()))
    if duplicate: raise HTTPException(status_code=409, detail="A flow with this name already exists")
    flow = Flow(workspace_id=workspace_id, name=payload.name, description=payload.description.strip() if payload.description else None, trigger_type=payload.trigger_type, trigger_value=payload.trigger_value.strip() if payload.trigger_value else None, stop_on_reply=payload.stop_on_reply, created_by_user_id=user.id)
    db.add(flow); db.flush(); db.add(FlowChannelTarget(flow_id=flow.id, channel=payload.channel)); db.commit(); return _flow_out(_get_flow(flow.id, db))


@router.get("/{flow_id}", response_model=FlowOut)
def get_flow(flow_id: int, db: Session = Depends(get_db)): return _flow_out(_get_flow(flow_id, db))


@router.patch("/{flow_id}", response_model=FlowOut)
def update_flow(flow_id: int, payload: FlowUpdate, db: Session = Depends(get_db), user: User = Depends(require_user)):
    _require_manager(user); flow = _get_flow(flow_id, db); values = payload.model_dump(exclude_unset=True)
    if "name" in values:
        name = values["name"].strip(); duplicate = db.scalar(select(Flow.id).where(Flow.workspace_id == flow.workspace_id, func.lower(Flow.name) == name.lower(), Flow.id != flow.id))
        if duplicate: raise HTTPException(status_code=409, detail="A flow with this name already exists")
        flow.name = name
    if "description" in values: flow.description = values["description"].strip() if values["description"] else None
    if "status" in values:
        if values["status"] == FlowStatus.ACTIVE and not flow.steps and not db.scalar(select(FlowNode.id).where(FlowNode.flow_id == flow.id).limit(1)): raise HTTPException(status_code=400, detail="Add at least one flow action before activating a flow")
        flow.status = values["status"]
    if "trigger_type" in values: flow.trigger_type = values["trigger_type"]
    if "trigger_value" in values: flow.trigger_value = values["trigger_value"].strip() if values["trigger_value"] else None
    if "stop_on_reply" in values: flow.stop_on_reply = values["stop_on_reply"]
    flow.updated_at = datetime.utcnow(); db.commit(); return _flow_out(_get_flow(flow.id, db))


@router.delete("/{flow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_flow(flow_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    _require_manager(user); flow = _get_flow(flow_id, db); db.delete(flow); db.commit()


@router.get("/{flow_id}/runs")
def list_flow_runs(flow_id:int, limit:int=Query(default=50,ge=1,le=200), db:Session=Depends(get_db), user:User=Depends(require_user)):
    _get_flow(flow_id,db)
    runs=db.scalars(select(FlowRun).where(FlowRun.flow_id==flow_id).order_by(FlowRun.started_at.desc(),FlowRun.id.desc()).limit(limit)).all()
    return [{"id":r.id,"flow_id":r.flow_id,"channel":r.channel,"conversation_id":r.conversation_id,"contact_id":r.contact_id,"status":r.status,"current_node_id":r.current_node_id,"error_type":r.error_type,"error_message":r.error_message,"started_at":r.started_at,"updated_at":r.updated_at,"completed_at":r.completed_at} for r in runs]


@router.get("/{flow_id}/runs/{run_id}")
def get_flow_run(flow_id:int,run_id:int,db:Session=Depends(get_db),user:User=Depends(require_user)):
    _get_flow(flow_id,db);run=db.scalar(select(FlowRun).where(FlowRun.id==run_id,FlowRun.flow_id==flow_id))
    if not run:raise HTTPException(status_code=404,detail="Flow run not found")
    events=db.scalars(select(FlowRunEvent).where(FlowRunEvent.run_id==run.id).order_by(FlowRunEvent.created_at,FlowRunEvent.id)).all()
    return {"id":run.id,"flow_id":run.flow_id,"channel":run.channel,"conversation_id":run.conversation_id,"contact_id":run.contact_id,"status":run.status,"current_node_id":run.current_node_id,"error_type":run.error_type,"error_message":run.error_message,"started_at":run.started_at,"updated_at":run.updated_at,"completed_at":run.completed_at,"events":[{"id":e.id,"node_id":e.node_id,"node_type":e.node_type,"status":e.status,"message":e.message,"created_at":e.created_at} for e in events]}


@router.post("/{flow_id}/steps", response_model=FlowOut, status_code=status.HTTP_201_CREATED)
def add_step(flow_id: int, payload: FlowStepCreate, db: Session = Depends(get_db), user: User = Depends(require_user)):
    _require_manager(user); flow = _get_flow(flow_id, db); next_order = max((step.sort_order for step in flow.steps), default=-1) + 1; db.add(FlowStep(flow_id=flow.id, step_type=payload.step_type, sort_order=next_order, config_json=json.dumps(payload.config, ensure_ascii=False))); flow.updated_at = datetime.utcnow(); db.commit(); return _flow_out(_get_flow(flow.id, db))


@router.post("/{flow_id}/steps-order", response_model=FlowOut)
def reorder_steps(flow_id: int, payload: FlowReorderRequest, db: Session = Depends(get_db), user: User = Depends(require_user)):
    _require_manager(user); flow = _get_flow(flow_id, db); existing_ids = {step.id for step in flow.steps}
    if len(payload.step_ids) != len(existing_ids) or set(payload.step_ids) != existing_ids: raise HTTPException(status_code=400, detail="step_ids must contain every flow step exactly once")
    for index, step_id in enumerate(payload.step_ids): next(item for item in flow.steps if item.id == step_id).sort_order = 100000 + index
    db.flush()
    for index, step_id in enumerate(payload.step_ids): next(item for item in flow.steps if item.id == step_id).sort_order = index
    flow.updated_at = datetime.utcnow(); db.commit(); return _flow_out(_get_flow(flow.id, db))


@router.patch("/{flow_id}/steps/{step_id}", response_model=FlowOut)
def update_step(flow_id: int, step_id: int, payload: FlowStepUpdate, db: Session = Depends(get_db), user: User = Depends(require_user)):
    _require_manager(user); flow = _get_flow(flow_id, db); step = next((item for item in flow.steps if item.id == step_id), None)
    if not step: raise HTTPException(status_code=404, detail="Flow step not found")
    values = payload.model_dump(exclude_unset=True)
    if "step_type" in values: step.step_type = values["step_type"]
    if "config" in values: step.config_json = json.dumps(values["config"] or {}, ensure_ascii=False)
    flow.updated_at = datetime.utcnow(); db.commit(); return _flow_out(_get_flow(flow.id, db))


@router.delete("/{flow_id}/steps/{step_id}", response_model=FlowOut)
def delete_step(flow_id: int, step_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    _require_manager(user); flow = _get_flow(flow_id, db); step = next((item for item in flow.steps if item.id == step_id), None)
    if not step: raise HTTPException(status_code=404, detail="Flow step not found")
    db.delete(step); db.flush(); remaining = db.scalars(select(FlowStep).where(FlowStep.flow_id == flow.id).order_by(FlowStep.sort_order.asc())).all()
    for index, item in enumerate(remaining): item.sort_order=index
    flow.updated_at=datetime.utcnow(); db.commit(); return _flow_out(_get_flow(flow.id, db))


@router.get("/{flow_id}/graph", response_model=FlowGraphOut)
def get_graph(flow_id:int, db:Session=Depends(get_db)):
    _get_flow(flow_id,db); nodes=db.scalars(select(FlowNode).where(FlowNode.flow_id==flow_id).order_by(FlowNode.id)).all(); edges=db.scalars(select(FlowEdge).where(FlowEdge.flow_id==flow_id).order_by(FlowEdge.sort_order,FlowEdge.id)).all(); return FlowGraphOut(flow_id=flow_id,nodes=[_node_out(n) for n in nodes],edges=[_edge_out(e) for e in edges])


@router.post("/{flow_id}/nodes", response_model=FlowNodeOut, status_code=status.HTTP_201_CREATED)
def add_node(flow_id:int,payload:FlowNodeCreate,db:Session=Depends(get_db),user:User=Depends(require_user)):
    _require_manager(user); flow=_get_flow(flow_id,db); node=FlowNode(flow_id=flow.id,node_type=payload.node_type,title=payload.title,config_json=json.dumps(payload.config or {},ensure_ascii=False),position_x=payload.position_x,position_y=payload.position_y); db.add(node); flow.updated_at=datetime.utcnow(); db.commit(); db.refresh(node); return _node_out(node)


@router.patch("/{flow_id}/nodes/{node_id}", response_model=FlowNodeOut)
def update_node(flow_id:int,node_id:int,payload:FlowNodeUpdate,db:Session=Depends(get_db),user:User=Depends(require_user)):
    _require_manager(user); flow=_get_flow(flow_id,db); node=db.scalar(select(FlowNode).where(FlowNode.id==node_id,FlowNode.flow_id==flow_id))
    if not node: raise HTTPException(status_code=404,detail="Flow node not found")
    values=payload.model_dump(exclude_unset=True)
    if "title" in values: node.title=values["title"]
    if "config" in values: node.config_json=json.dumps(values["config"] or {},ensure_ascii=False)
    if "position_x" in values: node.position_x=values["position_x"]
    if "position_y" in values: node.position_y=values["position_y"]
    flow.updated_at=datetime.utcnow(); db.commit(); db.refresh(node); return _node_out(node)


@router.delete("/{flow_id}/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_node(flow_id:int,node_id:int,db:Session=Depends(get_db),user:User=Depends(require_user)):
    _require_manager(user); flow=_get_flow(flow_id,db); node=db.scalar(select(FlowNode).where(FlowNode.id==node_id,FlowNode.flow_id==flow_id))
    if not node: raise HTTPException(status_code=404,detail="Flow node not found")
    db.delete(node); flow.updated_at=datetime.utcnow(); db.commit()


@router.post("/{flow_id}/edges", response_model=FlowEdgeOut, status_code=status.HTTP_201_CREATED)
def add_edge(flow_id:int,payload:FlowEdgeCreate,db:Session=Depends(get_db),user:User=Depends(require_user)):
    _require_manager(user); flow=_get_flow(flow_id,db)
    if payload.source_node_id==payload.target_node_id: raise HTTPException(status_code=400,detail="A node cannot connect to itself")
    source=db.scalar(select(FlowNode.id).where(FlowNode.id==payload.source_node_id,FlowNode.flow_id==flow_id)); target=db.scalar(select(FlowNode.id).where(FlowNode.id==payload.target_node_id,FlowNode.flow_id==flow_id))
    if not source or not target: raise HTTPException(status_code=400,detail="Both nodes must belong to this flow")
    next_sort_order = db.scalar(select(func.coalesce(func.max(FlowEdge.sort_order), -1)).where(FlowEdge.flow_id == flow.id)) + 1; edge=FlowEdge(flow_id=flow.id,source_node_id=payload.source_node_id,source_handle=payload.source_handle,target_node_id=payload.target_node_id,target_handle=payload.target_handle,sort_order=next_sort_order); db.add(edge); flow.updated_at=datetime.utcnow(); db.commit(); db.refresh(edge); return _edge_out(edge)


@router.delete("/{flow_id}/edges/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_edge(flow_id:int,edge_id:int,db:Session=Depends(get_db),user:User=Depends(require_user)):
    _require_manager(user); flow=_get_flow(flow_id,db); edge=db.scalar(select(FlowEdge).where(FlowEdge.id==edge_id,FlowEdge.flow_id==flow_id))
    if not edge: raise HTTPException(status_code=404,detail="Flow edge not found")
    db.delete(edge); flow.updated_at=datetime.utcnow(); db.commit()
