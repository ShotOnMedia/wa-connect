from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TelegramBot(Base):
    __tablename__ = "telegram_bots"
    __table_args__ = (UniqueConstraint("workspace_id", "bot_id", name="uq_workspace_telegram_bot"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    bot_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(150), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    access_token: Mapped[str] = mapped_column(Text)
    webhook_secret: Mapped[str] = mapped_column(String(128))
    webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversations: Mapped[list["TelegramConversation"]] = relationship(back_populates="bot", cascade="all, delete-orphan")


class TelegramContact(Base):
    __tablename__ = "telegram_contacts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "telegram_user_id", name="uq_workspace_telegram_contact"),
        Index("ix_telegram_contacts_workspace_username", "workspace_id", "username"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[str | None] = mapped_column(String(150), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    language_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversations: Mapped[list["TelegramConversation"]] = relationship(back_populates="contact")


class TelegramContactFieldValue(Base):
    __tablename__ = "telegram_contact_field_values"
    __table_args__ = (
        UniqueConstraint("contact_id", "field_id", name="uq_telegram_contact_field_value"),
        Index("ix_telegram_contact_field_values_contact", "contact_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("telegram_contacts.id", ondelete="CASCADE"), index=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("contact_field_definitions.id", ondelete="CASCADE"), index=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TelegramContactTagLink(Base):
    __tablename__ = "telegram_contact_tag_links"
    __table_args__ = (UniqueConstraint("contact_id", "tag_id", name="uq_telegram_contact_tag_link"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("telegram_contacts.id", ondelete="CASCADE"), index=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("contact_tags.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TelegramConversation(Base):
    __tablename__ = "telegram_conversations"
    __table_args__ = (
        UniqueConstraint("telegram_bot_id", "chat_id", name="uq_telegram_bot_chat"),
        Index("ix_telegram_conversations_status_last", "status", "last_message_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    telegram_bot_id: Mapped[int] = mapped_column(ForeignKey("telegram_bots.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("telegram_contacts.id", ondelete="CASCADE"), index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    chat_type: Mapped[str] = mapped_column(String(30), default="private")
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    assigned_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    bot: Mapped[TelegramBot] = relationship(back_populates="conversations")
    contact: Mapped[TelegramContact] = relationship(back_populates="conversations")
    messages: Mapped[list["TelegramMessage"]] = relationship(back_populates="conversation", cascade="all, delete-orphan", order_by="TelegramMessage.created_at")


class TelegramMessage(Base):
    __tablename__ = "telegram_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "telegram_message_id", name="uq_telegram_conversation_message"),
        Index("ix_telegram_messages_conversation_created", "conversation_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("telegram_conversations.id", ondelete="CASCADE"), index=True)
    telegram_message_id: Mapped[int] = mapped_column(BigInteger)
    direction: Mapped[str] = mapped_column(String(20), default="inbound")
    message_type: Mapped[str] = mapped_column(String(50), default="text")
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="received")
    telegram_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversation: Mapped[TelegramConversation] = relationship(back_populates="messages")
