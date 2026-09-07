from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_user
from app.flow_channel_models import FlowChannelTarget
from app.flow_models import Flow, FlowEdge, FlowNode, FlowStatus, FlowStep
from app.models import User

router = APIRouter(prefix="/flows", tags=["flows"])


def _require_manager(user: User) -> None:
    if user.role.value not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="Only admins and managers can manage flows")


def _copy_name(db: Session, flow: Flow) -> str:
    base = f"{flow.name} (Copy)"
    candidate = base
    number = 2
    while db.scalar(select(Flow.id).where(Flow.workspace_id == flow.workspace_id, func.lower(Flow.name) == candidate.lower())):
        candidate = f"{base} {number}"
        number += 1
    return candidate


@router.post("/{flow_id}/duplicate", status_code=status.HTTP_201_CREATED)
def duplicate_flow(flow_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Clone a complete flow definition as a safe draft, without copying run/session history."""
    _require_manager(user)
    source = db.get(Flow, flow_id)
    if not source:
        raise HTTPException(status_code=404, detail="Flow not found")

    clone = Flow(
        workspace_id=source.workspace_id,
        name=_copy_name(db, source),
        description=source.description,
        status=FlowStatus.DRAFT,
        trigger_type=source.trigger_type,
        trigger_value=source.trigger_value,
        stop_on_reply=source.stop_on_reply,
        created_by_user_id=user.id,
    )
    db.add(clone)
    db.flush()

    channel = db.scalar(select(FlowChannelTarget.channel).where(FlowChannelTarget.flow_id == source.id)) or "whatsapp"
    db.add(FlowChannelTarget(flow_id=clone.id, channel=channel))

    steps = db.scalars(select(FlowStep).where(FlowStep.flow_id == source.id).order_by(FlowStep.sort_order, FlowStep.id)).all()
    for step in steps:
        db.add(FlowStep(flow_id=clone.id, step_type=step.step_type, sort_order=step.sort_order, config_json=step.config_json))

    node_map = {}
    nodes = db.scalars(select(FlowNode).where(FlowNode.flow_id == source.id).order_by(FlowNode.id)).all()
    for node in nodes:
        copied = FlowNode(
            flow_id=clone.id,
            node_type=node.node_type,
            title=node.title,
            config_json=node.config_json,
            position_x=node.position_x,
            position_y=node.position_y,
        )
        db.add(copied)
        db.flush()
        node_map[node.id] = copied.id

    edges = db.scalars(select(FlowEdge).where(FlowEdge.flow_id == source.id).order_by(FlowEdge.sort_order, FlowEdge.id)).all()
    for edge in edges:
        db.add(FlowEdge(
            flow_id=clone.id,
            source_node_id=node_map[edge.source_node_id],
            source_handle=edge.source_handle,
            target_node_id=node_map[edge.target_node_id],
            target_handle=edge.target_handle,
            sort_order=edge.sort_order,
        ))

    db.commit()
    return {
        "id": clone.id,
        "name": clone.name,
        "status": clone.status.value,
        "channel": channel,
        "source_flow_id": source.id,
        "step_count": len(steps),
        "node_count": len(nodes),
        "edge_count": len(edges),
    }
