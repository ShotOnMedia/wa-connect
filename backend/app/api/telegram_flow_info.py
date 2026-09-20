from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.core.database import get_db
from app.core.security import require_user
from app.flow_channel_models import TelegramFlowSession
from app.flow_models import Flow, FlowNode
from app.telegram_models import TelegramConversation

router = APIRouter(prefix="/telegram", tags=["Telegram"])


@router.get("/conversations/{conversation_id}/flow-session", dependencies=[Depends(require_user)])
def telegram_flow_session(conversation_id: int, db: Session = Depends(get_db)):
    node_alias = aliased(FlowNode)
    row = db.execute(
        select(TelegramConversation.id, TelegramFlowSession, Flow.name, node_alias.title, node_alias.node_type)
        .outerjoin(TelegramFlowSession, TelegramFlowSession.conversation_id == TelegramConversation.id)
        .outerjoin(Flow, Flow.id == TelegramFlowSession.flow_id)
        .outerjoin(node_alias, node_alias.id == TelegramFlowSession.current_node_id)
        .where(TelegramConversation.id == conversation_id)
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Telegram conversation not found")

    _, session, flow_name, node_title, node_type_value = row
    if not session:
        return None

    node_type = node_type_value.value if hasattr(node_type_value, "value") else (str(node_type_value) if node_type_value is not None else None)
    return {
        "id": session.id,
        "flow_id": session.flow_id,
        "flow_name": flow_name or f"Flow {session.flow_id}",
        "current_node_id": session.current_node_id,
        "current_node_title": node_title,
        "current_node_type": node_type,
        "status": session.status,
        "waiting_for": session.waiting_for,
        "started_at": session.started_at,
        "updated_at": session.updated_at,
        "ended_at": session.ended_at,
    }
