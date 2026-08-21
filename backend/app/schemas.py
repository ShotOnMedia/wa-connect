from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import ConversationStatus, MessageDirection, MessageStatus


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    wa_id: str
    name: str | None


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    phone_number_id: int
    status: ConversationStatus
    last_message_at: datetime | None
    contact: ContactOut
    unread_count: int = 0
    last_message_body: str | None = None
    last_message_direction: MessageDirection | None = None


class ConversationStatusUpdate(BaseModel):
    status: ConversationStatus


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
    text: str = Field(min_length=1, max_length=4096)


class WhatsAppConnectionCreate(BaseModel):
    workspace_name: str = Field(min_length=2, max_length=150)
    workspace_slug: str = Field(min_length=2, max_length=150, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    waba_id: str = Field(min_length=2, max_length=64)
    phone_number_id: str = Field(min_length=2, max_length=64)
    access_token: str = Field(min_length=10)

    @field_validator("workspace_name", "waba_id", "phone_number_id", "access_token")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Value cannot be blank")
        return value


class WhatsAppConnectionOut(BaseModel):
    id: int
    workspace_id: int
    workspace_name: str
    workspace_slug: str
    whatsapp_account_id: int
    waba_id: str
    account_name: str | None
    phone_number_id: str
    display_phone_number: str | None
    verified_name: str | None
    active: bool
    has_access_token: bool


class WhatsAppConnectionVerify(BaseModel):
    waba_id: str = Field(min_length=2, max_length=64)
    phone_number_id: str = Field(min_length=2, max_length=64)
    access_token: str = Field(min_length=10)


class WhatsAppConnectionHealth(BaseModel):
    connected: bool
    waba_id: str
    account_name: str | None = None
    phone_number_id: str
    display_phone_number: str | None = None
    verified_name: str | None = None
    quality_rating: str | None = None
    platform_type: str | None = None
    code_verification_status: str | None = None


class WebhookSetupOut(BaseModel):
    callback_path: str
    verify_token: str
    app_secret_configured: bool
