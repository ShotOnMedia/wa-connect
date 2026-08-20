from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import ConversationStatus, MessageDirection, MessageStatus


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    wa_id: str
    name: str | None


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: ConversationStatus
    last_message_at: datetime | None
    contact: ContactOut


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    meta_message_id: str | None
    direction: MessageDirection
    message_type: str
    body: str | None
    status: MessageStatus
    whatsapp_timestamp: datetime | None
    created_at: datetime


class SendTextRequest(BaseModel):
    phone_number_id: int = Field(gt=0)
    to: str = Field(min_length=5, max_length=40)
    text: str = Field(min_length=1, max_length=4096)
