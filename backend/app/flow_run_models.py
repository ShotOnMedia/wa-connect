from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FlowRun(Base):
    __tablename__ = "flow_runs"
    __table_args__ = (
        Index("ix_flow_runs_flow_started", "flow_id", "started_at"),
        Index("ix_flow_runs_channel_conversation", "channel", "conversation_id", "started_at"),
        Index("ix_flow_runs_status_updated", "status", "updated_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    flow_id: Mapped[int] = mapped_column(ForeignKey("flows.id", ondelete="CASCADE"), nullable=False)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    conversation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    contact_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    current_node_id: Mapped[int | None] = mapped_column(ForeignKey("flow_nodes.id", ondelete="SET NULL"), nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class FlowRunEvent(Base):
    __tablename__ = "flow_run_events"
    __table_args__ = (Index("ix_flow_run_events_run_created", "run_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("flow_runs.id", ondelete="CASCADE"), nullable=False)
    node_id: Mapped[int | None] = mapped_column(ForeignKey("flow_nodes.id", ondelete="SET NULL"), nullable=True)
    node_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
