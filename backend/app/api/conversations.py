from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_user
from app.flow_models import Flow, FlowNode, FlowSession, FlowSessionStatus
from app.models import Conversation, Message, MessageDirection, MessageStatus, User, UserRole, WhatsAppPhoneNumber
from app.schemas import ConversationAssignmentUpdate, ConversationOut, ConversationStatusUpdate, FlowSessionOut, MessageOut, SendTextRequest
from app.services.service_window import ServiceWindowClosed, require_service_window, service_window_open
from app.services.whatsapp import WhatsAppError, send_text_message

router = APIRouter(prefix="/conversations", tags=["Conversations"])


def _flow_session_out(db: Session, conversation_id: int) -> FlowSessionOut | None:
    session = db.scalar(select(FlowSession).where(FlowSession.conversation_id == conversation_id))
    if not session:
        return None
    flow = db.get(Flow, session.flow_id)
    node = db.get(FlowNode, session.current_node_id) if session.current_node_id else None
    return FlowSessionOut(
        id=session.id,
        flow_id=session.flow_id,
        flow_name=flow.name if flow else f"Flow {session.flow_id}",
        current_node_id=session.current_node_id,
        current_node_title=(node.title if node else None),
        status=session.status.value,
        waiting_for=session.waiting_for,
        started_at=session.started_at,
        updated_at=session.updated_at,
        ended_at=session.ended_at,
    )


def _conversation_out(db: Session, conversation: Conversation) -> ConversationOut:
    unread_stmt = select(func.count(Message.id)).where(Message.conversation_id == conversation.id, Message.direction == MessageDirection.INBOUND)
    if conversation.last_read_at:
        unread_stmt = unread_stmt.where(Message.created_at > conversation.last_read_at)
    unread_count = db.scalar(unread_stmt) or 0
    last_message = db.scalar(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at.desc()).limit(1))
    assigned_user = db.get(User, conversation.assigned_user_id) if conversation.assigned_user_id else None
    return ConversationOut(
        id=conversation.id,
        phone_number_id=conversation.phone_number_id,
        status=conversation.status,
        last_message_at=conversation.last_message_at,
        last_customer_message_at=conversation.last_customer_message_at,
        service_window_expires_at=conversation.service_window_expires_at,
        service_window_open=service_window_open(conversation),
        contact=conversation.contact,
        unread_count=unread_count,
        last_message_body=last_message.body if last_message else None,
        last_message_direction=last_message.direction if last_message else None,
        assigned_user_id=conversation.assigned_user_id,
        assigned_user=assigned_user,
        flow_session=_flow_session_out(db, conversation.id),
    )


@router.get("", response_model=list[ConversationOut])
def list_conversations(
    assignment: str = Query(default="all", pattern="^(all|mine|unassigned)$"),
    current: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    stmt = select(Conversation).options(selectinload(Conversation.contact)).order_by(Conversation.last_message_at.desc())
    if assignment == "mine":
        stmt = stmt.where(Conversation.assigned_user_id == current.id)
    elif assignment == "unassigned":
        stmt = stmt.where(Conversation.assigned_user_id.is_(None))
    return [_conversation_out(db, item) for item in db.scalars(stmt).all()]


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
def list_messages(conversation_id: int, db: Session = Depends(get_db)):
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    stmt = select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at.asc())
    return list(db.scalars(stmt).all())


@router.get("/{conversation_id}/flow-session", response_model=FlowSessionOut | None)
def get_flow_session(conversation_id: int, current: User = Depends(require_user), db: Session = Depends(get_db)):
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return _flow_session_out(db, conversation_id)


@router.post("/{conversation_id}/flow-session/reset", response_model=FlowSessionOut | None)
def reset_flow_session(conversation_id: int, current: User = Depends(require_user), db: Session = Depends(get_db)):
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    session = db.scalar(select(FlowSession).where(FlowSession.conversation_id == conversation_id))
    if not session:
        return None
    session.status = FlowSessionStatus.RESET
    session.current_node_id = None
    session.waiting_for = None
    session.ended_at = datetime.utcnow()
    session.reset_by_user_id = current.id
    db.commit()
    db.refresh(session)
    return _flow_session_out(db, conversation_id)


@router.post("/{conversation_id}/read", response_model=ConversationOut)
def mark_conversation_read(conversation_id: int, db: Session = Depends(get_db)):
    conversation = db.scalar(select(Conversation).options(selectinload(Conversation.contact)).where(Conversation.id == conversation_id))
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conversation.last_read_at = datetime.utcnow()
    db.commit()
    db.refresh(conversation)
    return _conversation_out(db, conversation)


@router.patch("/{conversation_id}/status", response_model=ConversationOut)
def update_conversation_status(conversation_id: int, request: ConversationStatusUpdate, db: Session = Depends(get_db)):
    conversation = db.scalar(select(Conversation).options(selectinload(Conversation.contact)).where(Conversation.id == conversation_id))
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conversation.status = request.status
    db.commit()
    db.refresh(conversation)
    return _conversation_out(db, conversation)


@router.patch("/{conversation_id}/assignment", response_model=ConversationOut)
def update_assignment(
    conversation_id: int,
    request: ConversationAssignmentUpdate,
    current: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    conversation = db.scalar(select(Conversation).options(selectinload(Conversation.contact)).where(Conversation.id == conversation_id))
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if request.user_id is None:
        if current.role == UserRole.AGENT and conversation.assigned_user_id not in {None, current.id}:
            raise HTTPException(status_code=403, detail="Agents can only unassign conversations assigned to themselves")
        conversation.assigned_user_id = None
    else:
        target = db.get(User, request.user_id)
        if not target or not target.active:
            raise HTTPException(status_code=400, detail="Assigned user is unavailable")
        if current.role == UserRole.AGENT and target.id != current.id:
            raise HTTPException(status_code=403, detail="Agents can only assign conversations to themselves")
        conversation.assigned_user_id = target.id

    db.commit()
    db.refresh(conversation)
    return _conversation_out(db, conversation)


@router.post("/{conversation_id}/messages", response_model=MessageOut)
async def send_message(conversation_id: int, request: SendTextRequest, current: User = Depends(require_user), db: Session = Depends(get_db)):
    conversation = db.scalar(select(Conversation).options(selectinload(Conversation.contact)).where(Conversation.id == conversation_id))
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if current.role == UserRole.AGENT and conversation.assigned_user_id not in {None, current.id}:
        raise HTTPException(status_code=403, detail="This conversation is assigned to another agent")
    try:
        require_service_window(conversation)
    except ServiceWindowClosed as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if conversation.contact.blocked_at:
        raise HTTPException(status_code=409, detail="This contact is blocked and cannot receive free-form messages")
    if conversation.assigned_user_id is None:
        conversation.assigned_user_id = current.id
    phone_number = db.get(WhatsAppPhoneNumber, conversation.phone_number_id)
    if not phone_number:
        raise HTTPException(status_code=503, detail="Conversation phone number is unavailable")
    access_token = phone_number.access_token or settings.meta_access_token
    if not access_token:
        raise HTTPException(status_code=503, detail="No WhatsApp access token configured")
    message = Message(conversation_id=conversation.id, direction=MessageDirection.OUTBOUND, message_type="text", body=request.text, status=MessageStatus.QUEUED)
    db.add(message)
    db.flush()
    try:
        result = await send_text_message(phone_number.phone_number_id, access_token, conversation.contact.wa_id, request.text)
        meta_messages = result.get("messages", [])
        message.meta_message_id = meta_messages[0].get("id") if meta_messages else None
        message.status = MessageStatus.SENT
        conversation.last_message_at = datetime.utcnow()
        conversation.last_read_at = datetime.utcnow()
        db.commit()
        db.refresh(message)
        return message
    except WhatsAppError as exc:
        message.status = MessageStatus.FAILED
        message.error_message = str(exc)
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
