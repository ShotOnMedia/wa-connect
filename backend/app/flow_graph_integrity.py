import json

from sqlalchemy import delete, event, select
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.flow_models import Flow, FlowEdge, FlowNode, FlowNodeType


def _trigger_values(flow: Flow) -> dict:
    return {
        "node_type": "trigger",
        "title": "Start Bot Flow",
        "config_json": json.dumps(
            {
                "trigger_type": getattr(flow.trigger_type, "value", flow.trigger_type),
                "trigger_value": flow.trigger_value,
            },
            ensure_ascii=False,
        ),
        "position_x": 80,
        "position_y": 100,
    }


@event.listens_for(Flow, "after_insert")
def create_start_node_for_new_flow(mapper, connection: Connection, target: Flow) -> None:
    """Every newly created flow starts life with its protected trigger node."""
    values = _trigger_values(target)
    values["flow_id"] = target.id
    # Core insert is intentional: it runs inside the Flow insert transaction and
    # does not invoke the FlowNode duplicate guard below.
    connection.execute(FlowNode.__table__.insert().values(**values))


@event.listens_for(FlowNode, "before_insert")
def prevent_duplicate_start_node(mapper, connection: Connection, target: FlowNode) -> None:
    """Reject accidental second trigger nodes created through the ORM/API.

    New-flow bootstrap uses the Core insert above, so this guard targets later
    builder/API inserts.  It prevents a stale or concurrent builder seed from
    corrupting an otherwise valid graph.
    """
    node_type = getattr(target.node_type, "value", target.node_type)
    if str(node_type).lower() != FlowNodeType.TRIGGER.value or not target.flow_id:
        return
    existing = connection.execute(
        select(FlowNode.id)
        .where(FlowNode.flow_id == target.flow_id, FlowNode.node_type == FlowNodeType.TRIGGER)
        .limit(1)
    ).scalar_one_or_none()
    if existing is not None:
        raise ValueError(f"Flow {target.flow_id} already has a Start Bot Flow node ({existing})")


def _pick_primary_trigger(db: Session, flow_id: int, triggers: list[FlowNode]) -> FlowNode:
    """Prefer the trigger that actually owns the flow path, then the oldest ID."""
    trigger_ids = {node.id for node in triggers}
    outgoing = db.scalars(
        select(FlowEdge).where(
            FlowEdge.flow_id == flow_id,
            FlowEdge.source_node_id.in_(trigger_ids),
        )
    ).all()
    outgoing_counts = {node.id: 0 for node in triggers}
    for edge in outgoing:
        # An edge to a non-trigger node is evidence that this is the real start.
        if edge.target_node_id not in trigger_ids:
            outgoing_counts[edge.source_node_id] = outgoing_counts.get(edge.source_node_id, 0) + 1
    return sorted(triggers, key=lambda node: (-outgoing_counts.get(node.id, 0), node.id))[0]


def repair_flow_start_nodes(db: Session) -> int:
    """Ensure every existing flow has exactly one usable Start Bot Flow node.

    Historical duplicate triggers are repaired conservatively: if one trigger is
    connected to the graph and another is orphaned, the connected trigger wins.
    This avoids the previous failure mode where keeping the oldest orphan trigger
    made a valid flow complete immediately without executing its first action.
    """
    repaired = 0
    flows = db.scalars(select(Flow).order_by(Flow.id)).all()

    for flow in flows:
        triggers = db.scalars(
            select(FlowNode)
            .where(FlowNode.flow_id == flow.id, FlowNode.node_type == FlowNodeType.TRIGGER)
            .order_by(FlowNode.id)
        ).all()

        if not triggers:
            values = _trigger_values(flow)
            db.add(FlowNode(flow_id=flow.id, **values))
            db.flush()
            repaired += 1
            continue

        primary = _pick_primary_trigger(db, flow.id, triggers)
        expected = _trigger_values(flow)
        changed = False
        if primary.title != expected["title"]:
            primary.title = expected["title"]
            changed = True
        if primary.config_json != expected["config_json"]:
            primary.config_json = expected["config_json"]
            changed = True
        if changed:
            repaired += 1

        duplicate_ids = [node.id for node in triggers if node.id != primary.id]
        if duplicate_ids:
            db.execute(
                delete(FlowEdge).where(
                    FlowEdge.flow_id == flow.id,
                    (FlowEdge.source_node_id.in_(duplicate_ids))
                    | (FlowEdge.target_node_id.in_(duplicate_ids)),
                )
            )
            db.execute(delete(FlowNode).where(FlowNode.id.in_(duplicate_ids)))
            repaired += len(duplicate_ids)

    if repaired:
        db.commit()
    return repaired
