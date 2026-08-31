from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FlowChannelTarget(Base):
    __tablename__ = "flow_channel_targets"
    __table_args__ = (
        UniqueConstraint("flow_id", name="uq_flow_channel_target_flow"),
        Index("ix_flow_channel_targets_channel", "channel"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    flow_id: Mapped[int] = mapped_column(ForeignKey("flows.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(30), default="whatsapp", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TelegramFlowSession(Base):
    __tablename__ = "telegram_flow_sessions"
    __table_args__ = (
        UniqueConstraint("conversation_id", name="uq_telegram_flow_session_conversation"),
        Index("ix_telegram_flow_sessions_status_updated", "status", "updated_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("telegram_conversations.id", ondelete="CASCADE"), index=True)
    flow_id: Mapped[int] = mapped_column(ForeignKey("flows.id", ondelete="CASCADE"), index=True)
    current_node_id: Mapped[int | None] = mapped_column(ForeignKey("flow_nodes.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    waiting_for: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_inbound_message_id: Mapped[int | None] = mapped_column(ForeignKey("telegram_messages.id", ondelete="SET NULL"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
