from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_user
from app.flow_channel_models import TelegramFlowSession
from app.flow_models import Flow, FlowNode
from app.telegram_models import TelegramConversation

router = APIRouter(prefix="/telegram", tags=["Telegram"])


@router.get("/conversations/{conversation_id}/flow-session", dependencies=[Depends(require_user)])
def telegram_flow_session(conversation_id: int, db: Session = Depends(get_db)):
    conversation = db.get(TelegramConversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Telegram conversation not found")

    session = db.scalar(
        select(TelegramFlowSession).where(TelegramFlowSession.conversation_id == conversation_id)
    )
    if not session:
        return None

    flow = db.get(Flow, session.flow_id)
    node = db.get(FlowNode, session.current_node_id) if session.current_node_id else None
    node_type = None
    if node:
        node_type = node.node_type.value if hasattr(node.node_type, "value") else str(node.node_type)

    return {
        "id": session.id,
        "flow_id": session.flow_id,
        "flow_name": flow.name if flow else f"Flow {session.flow_id}",
        "current_node_id": session.current_node_id,
        "current_node_title": node.title if node else None,
        "current_node_type": node_type,
        "status": session.status,
        "waiting_for": session.waiting_for,
        "started_at": session.started_at,
        "updated_at": session.updated_at,
        "ended_at": session.ended_at,
    }
