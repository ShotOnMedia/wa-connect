from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FlowDelayJob(Base):
    __tablename__ = "flow_delay_jobs"
    __table_args__ = (
        Index("ix_flow_delay_jobs_due", "status", "run_at"),
        Index("ix_flow_delay_jobs_flow", "flow_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    flow_id: Mapped[int] = mapped_column(ForeignKey("flows.id", ondelete="CASCADE"), nullable=False)
    conversation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    delay_node_id: Mapped[int] = mapped_column(ForeignKey("flow_nodes.id", ondelete="CASCADE"), nullable=False)
    resume_node_id: Mapped[int | None] = mapped_column(ForeignKey("flow_nodes.id", ondelete="SET NULL"), nullable=True)
    run_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
