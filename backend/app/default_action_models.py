from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DefaultAction(Base):
    __tablename__ = "default_actions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "channel", "action_type", name="uq_default_action_workspace_channel_type"),
        Index("ix_default_actions_workspace_channel", "workspace_id", "channel"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(20))
    action_type: Mapped[str] = mapped_column(String(40))
    flow_id: Mapped[int | None] = mapped_column(ForeignKey("flows.id", ondelete="SET NULL"), nullable=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
