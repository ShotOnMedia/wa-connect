from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, Boolean, DateTime, Enum as SqlEnum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ConversationStatus(str, Enum):
    OPEN = "open"
    PENDING = "pending"
    RESOLVED = "resolved"


class MessageDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageStatus(str, Enum):
    RECEIVED = "received"
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150))
    slug: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    whatsapp_accounts: Mapped[list["WhatsAppAccount"]] = relationship(back_populates="workspace")


class WhatsAppAccount(Base):
    __tablename__ = "whatsapp_accounts"
    __table_args__ = (UniqueConstraint("workspace_id", "waba_id", name="uq_workspace_waba"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), index=True)
    waba_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    workspace: Mapped[Workspace] = relationship(back_populates="whatsapp_accounts")
    phone_numbers: Mapped[list["WhatsAppPhoneNumber"]] = relationship(back_populates="account")


class WhatsAppPhoneNumber(Base):
    __tablename__ = "whatsapp_phone_numbers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    whatsapp_account_id: Mapped[int] = mapped_column(ForeignKey("whatsapp_accounts.id"), index=True)
    phone_number_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_phone_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    verified_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    account: Mapped[WhatsAppAccount] = relationship(back_populates="phone_numbers")


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "wa_id", name="uq_workspace_contact_wa_id"),
        Index("ix_contacts_workspace_name", "workspace_id", "name"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), index=True)
    wa_id: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("phone_number_id", "contact_id", name="uq_phone_contact_conversation"),
        Index("ix_conversations_status_last_message", "status", "last_message_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), index=True)
    phone_number_id: Mapped[int] = mapped_column(ForeignKey("whatsapp_phone_numbers.id"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    status: Mapped[ConversationStatus] = mapped_column(SqlEnum(ConversationStatus), default=ConversationStatus.OPEN)
    assigned_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    contact: Mapped[Contact] = relationship()
    phone_number: Mapped[WhatsAppPhoneNumber] = relationship()
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    meta_message_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    direction: Mapped[MessageDirection] = mapped_column(SqlEnum(MessageDirection))
    message_type: Mapped[str] = mapped_column(String(50), default="text")
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[MessageStatus] = mapped_column(SqlEnum(MessageStatus), default=MessageStatus.RECEIVED)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    whatsapp_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
