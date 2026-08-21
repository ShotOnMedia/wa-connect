from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.database import get_db
from app.models import Conversation, Message, MessageDirection, MessageStatus, WhatsAppPhoneNumber
from app.schemas import ConversationOut, ConversationStatusUpdate, MessageOut, SendTextRequest
from app.services.whatsapp import WhatsAppError, send_text_message

router = APIRouter(prefix="/conversations", tags=["Conversations"])


def _conversation_out(db: Session, conversation: Conversation) -> ConversationOut:
    unread_stmt = select(func.count(Message.id)).where(
        Message.conversation_id == conversation.id,
        Message.direction == MessageDirection.INBOUND,
    )
    if conversation.last_read_at:
        unread_stmt = unread_stmt.where(Message.created_at > conversation.last_read_at)
    unread_count = db.scalar(unread_stmt) or 0
    last_message = db.scalar(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at.desc()).limit(1))
    return ConversationOut(
        id=conversation.id,
        phone_number_id=conversation.phone_number_id,
        status=conversation.status,
        last_message_at=conversation.last_message_at,
        contact=conversation.contact,
        unread_count=unread_count,
        last_message_body=last_message.body if last_message else None,
        last_message_direction=last_message.direction if last_message else None,
    )


@router.get("", response_model=list[ConversationOut])
def list_conversations(db: Session = Depends(get_db)):
    stmt = select(Conversation).options(selectinload(Conversation.contact)).order_by(Conversation.last_message_at.desc())
    return [_conversation_out(db, item) for item in db.scalars(stmt).all()]


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
def list_messages(conversation_id: int, db: Session = Depends(get_db)):
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    stmt = select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at.asc())
    return list(db.scalars(stmt).all())


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


@router.post("/{conversation_id}/messages", response_model=MessageOut)
async def send_message(conversation_id: int, request: SendTextRequest, db: Session = Depends(get_db)):
    conversation = db.scalar(select(Conversation).options(selectinload(Conversation.contact)).where(Conversation.id == conversation_id))
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
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
