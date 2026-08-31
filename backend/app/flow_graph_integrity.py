import json

from sqlalchemy import delete, event, select
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.flow_models import Flow, FlowEdge, FlowNode


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
    connection.execute(FlowNode.__table__.insert().values(**values))


def repair_flow_start_nodes(db: Session) -> int:
    """Ensure every existing flow has exactly one Start Bot Flow node."""
    repaired = 0
    flows = db.scalars(select(Flow).order_by(Flow.id)).all()

    for flow in flows:
        triggers = db.scalars(
            select(FlowNode)
            .where(FlowNode.flow_id == flow.id, FlowNode.node_type == "trigger")
            .order_by(FlowNode.id)
        ).all()

        if not triggers:
            values = _trigger_values(flow)
            db.add(FlowNode(flow_id=flow.id, **values))
            repaired += 1
            continue

        primary = triggers[0]
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

        duplicate_ids = [node.id for node in triggers[1:]]
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
