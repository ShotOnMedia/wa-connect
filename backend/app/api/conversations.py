from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.database import get_db
from app.models import Conversation, Message, MessageDirection, MessageStatus, WhatsAppPhoneNumber
from app.schemas import ConversationOut, MessageOut, SendTextRequest
from app.services.whatsapp import WhatsAppError, send_text_message

router = APIRouter(prefix="/conversations", tags=["Conversations"])


@router.get("", response_model=list[ConversationOut])
def list_conversations(db: Session = Depends(get_db)):
    stmt = (
        select(Conversation)
        .options(selectinload(Conversation.contact))
        .order_by(Conversation.last_message_at.desc())
    )
    return list(db.scalars(stmt).all())


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
def list_messages(conversation_id: int, db: Session = Depends(get_db)):
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    stmt = select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at.asc())
    return list(db.scalars(stmt).all())


@router.post("/{conversation_id}/messages", response_model=MessageOut)
async def send_message(conversation_id: int, request: SendTextRequest, db: Session = Depends(get_db)):
    conversation = db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    phone_number = db.get(WhatsAppPhoneNumber, request.phone_number_id)
    if not phone_number or phone_number.id != conversation.phone_number_id:
        raise HTTPException(status_code=400, detail="Phone number does not belong to this conversation")

    access_token = phone_number.access_token or settings.meta_access_token
    if not access_token:
        raise HTTPException(status_code=503, detail="No WhatsApp access token configured")

    message = Message(
        conversation_id=conversation.id,
        direction=MessageDirection.OUTBOUND,
        message_type="text",
        body=request.text,
        status=MessageStatus.QUEUED,
    )
    db.add(message)
    db.flush()

    try:
        result = await send_text_message(phone_number.phone_number_id, access_token, request.to, request.text)
        meta_messages = result.get("messages", [])
        message.meta_message_id = meta_messages[0].get("id") if meta_messages else None
        message.status = MessageStatus.SENT
        conversation.last_message_at = datetime.utcnow()
        db.commit()
        db.refresh(message)
        return message
    except WhatsAppError as exc:
        message.status = MessageStatus.FAILED
        message.error_message = str(exc)
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
