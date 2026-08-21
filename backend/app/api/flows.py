import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.core.security import require_user
from app.flow_models import Flow, FlowStatus, FlowStep
from app.flow_schemas import FlowCreate, FlowOut, FlowReorderRequest, FlowStepCreate, FlowStepOut, FlowStepUpdate, FlowUpdate
from app.models import User, Workspace

router = APIRouter(prefix="/flows", tags=["flows"])


def _require_manager(user: User) -> None:
    if user.role.value not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="Only admins and managers can manage flows")


def _workspace_id(db: Session) -> int:
    workspace_id = db.scalar(select(Workspace.id).where(Workspace.active.is_(True)).order_by(Workspace.id.asc()).limit(1))
    if workspace_id is None:
        raise HTTPException(status_code=400, detail="Connect a WhatsApp workspace before creating flows")
    return int(workspace_id)


def _step_out(step: FlowStep) -> FlowStepOut:
    try:
        config = json.loads(step.config_json or "{}")
    except json.JSONDecodeError:
        config = {}
    return FlowStepOut(
        id=step.id,
        step_type=step.step_type,
        sort_order=step.sort_order,
        config=config,
        created_at=step.created_at,
        updated_at=step.updated_at,
    )


def _flow_out(flow: Flow) -> FlowOut:
    steps = [_step_out(step) for step in sorted(flow.steps, key=lambda item: item.sort_order)]
    return FlowOut(
        id=flow.id,
        workspace_id=flow.workspace_id,
        name=flow.name,
        description=flow.description,
        status=flow.status,
        trigger_type=flow.trigger_type,
        trigger_value=flow.trigger_value,
        stop_on_reply=flow.stop_on_reply,
        step_count=len(steps),
        steps=steps,
        created_at=flow.created_at,
        updated_at=flow.updated_at,
    )


def _get_flow(flow_id: int, db: Session) -> Flow:
    flow = db.scalar(select(Flow).options(selectinload(Flow.steps)).where(Flow.id == flow_id))
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    return flow


@router.get("", response_model=list[FlowOut])
def list_flows(
    flow_status: FlowStatus | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
):
    stmt = select(Flow).options(selectinload(Flow.steps)).order_by(Flow.updated_at.desc(), Flow.name.asc())
    if flow_status is not None:
        stmt = stmt.where(Flow.status == flow_status)
    return [_flow_out(flow) for flow in db.scalars(stmt).all()]


@router.post("", response_model=FlowOut, status_code=status.HTTP_201_CREATED)
def create_flow(payload: FlowCreate, db: Session = Depends(get_db), user: User = Depends(require_user)):
    _require_manager(user)
    workspace_id = _workspace_id(db)
    duplicate = db.scalar(select(Flow.id).where(Flow.workspace_id == workspace_id, func.lower(Flow.name) == payload.name.lower()))
    if duplicate:
        raise HTTPException(status_code=409, detail="A flow with this name already exists")
    flow = Flow(
        workspace_id=workspace_id,
        name=payload.name,
        description=payload.description.strip() if payload.description else None,
        trigger_type=payload.trigger_type,
        trigger_value=payload.trigger_value.strip() if payload.trigger_value else None,
        stop_on_reply=payload.stop_on_reply,
        created_by_user_id=user.id,
    )
    db.add(flow)
    db.commit()
    return _flow_out(_get_flow(flow.id, db))


@router.get("/{flow_id}", response_model=FlowOut)
def get_flow(flow_id: int, db: Session = Depends(get_db)):
    return _flow_out(_get_flow(flow_id, db))


@router.patch("/{flow_id}", response_model=FlowOut)
def update_flow(flow_id: int, payload: FlowUpdate, db: Session = Depends(get_db), user: User = Depends(require_user)):
    _require_manager(user)
    flow = _get_flow(flow_id, db)
    values = payload.model_dump(exclude_unset=True)
    if "name" in values:
        name = values["name"].strip()
        duplicate = db.scalar(select(Flow.id).where(Flow.workspace_id == flow.workspace_id, func.lower(Flow.name) == name.lower(), Flow.id != flow.id))
        if duplicate:
            raise HTTPException(status_code=409, detail="A flow with this name already exists")
        flow.name = name
    if "description" in values:
        flow.description = values["description"].strip() if values["description"] else None
    if "status" in values:
        if values["status"] == FlowStatus.ACTIVE and not flow.steps:
            raise HTTPException(status_code=400, detail="Add at least one step before activating a flow")
        flow.status = values["status"]
    if "trigger_type" in values:
        flow.trigger_type = values["trigger_type"]
    if "trigger_value" in values:
        flow.trigger_value = values["trigger_value"].strip() if values["trigger_value"] else None
    if "stop_on_reply" in values:
        flow.stop_on_reply = values["stop_on_reply"]
    flow.updated_at = datetime.utcnow()
    db.commit()
    return _flow_out(_get_flow(flow.id, db))


@router.delete("/{flow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_flow(flow_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    _require_manager(user)
    flow = _get_flow(flow_id, db)
    db.delete(flow)
    db.commit()


@router.post("/{flow_id}/steps", response_model=FlowOut, status_code=status.HTTP_201_CREATED)
def add_step(flow_id: int, payload: FlowStepCreate, db: Session = Depends(get_db), user: User = Depends(require_user)):
    _require_manager(user)
    flow = _get_flow(flow_id, db)
    next_order = (max((step.sort_order for step in flow.steps), default=-1) + 1)
    db.add(FlowStep(flow_id=flow.id, step_type=payload.step_type, sort_order=next_order, config_json=json.dumps(payload.config, ensure_ascii=False)))
    flow.updated_at = datetime.utcnow()
    db.commit()
    return _flow_out(_get_flow(flow.id, db))


@router.patch("/{flow_id}/steps/{step_id}", response_model=FlowOut)
def update_step(flow_id: int, step_id: int, payload: FlowStepUpdate, db: Session = Depends(get_db), user: User = Depends(require_user)):
    _require_manager(user)
    flow = _get_flow(flow_id, db)
    step = next((item for item in flow.steps if item.id == step_id), None)
    if not step:
        raise HTTPException(status_code=404, detail="Flow step not found")
    values = payload.model_dump(exclude_unset=True)
    if "step_type" in values:
        step.step_type = values["step_type"]
    if "config" in values:
        step.config_json = json.dumps(values["config"] or {}, ensure_ascii=False)
    flow.updated_at = datetime.utcnow()
    db.commit()
    return _flow_out(_get_flow(flow.id, db))


@router.delete("/{flow_id}/steps/{step_id}", response_model=FlowOut)
def delete_step(flow_id: int, step_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    _require_manager(user)
    flow = _get_flow(flow_id, db)
    step = next((item for item in flow.steps if item.id == step_id), None)
    if not step:
        raise HTTPException(status_code=404, detail="Flow step not found")
    db.delete(step)
    db.flush()
    remaining = db.scalars(select(FlowStep).where(FlowStep.flow_id == flow.id).order_by(FlowStep.sort_order.asc())).all()
    for index, item in enumerate(remaining):
        item.sort_order = index
    flow.updated_at = datetime.utcnow()
    db.commit()
    return _flow_out(_get_flow(flow.id, db))


@router.post("/{flow_id}/steps/reorder", response_model=FlowOut)
def reorder_steps(flow_id: int, payload: FlowReorderRequest, db: Session = Depends(get_db), user: User = Depends(require_user)):
    _require_manager(user)
    flow = _get_flow(flow_id, db)
    existing_ids = {step.id for step in flow.steps}
    if len(payload.step_ids) != len(existing_ids) or set(payload.step_ids) != existing_ids:
        raise HTTPException(status_code=400, detail="step_ids must contain every flow step exactly once")
    # Avoid the unique(flow_id, sort_order) constraint while swapping positions.
    for index, step_id in enumerate(payload.step_ids):
        step = next(item for item in flow.steps if item.id == step_id)
        step.sort_order = 100000 + index
    db.flush()
    for index, step_id in enumerate(payload.step_ids):
        step = next(item for item in flow.steps if item.id == step_id)
        step.sort_order = index
    flow.updated_at = datetime.utcnow()
    db.commit()
    return _flow_out(_get_flow(flow.id, db))
