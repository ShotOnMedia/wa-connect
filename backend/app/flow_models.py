from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, Boolean, DateTime, Enum as SqlEnum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class FlowStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"


class FlowTriggerType(str, Enum):
    MANUAL = "manual"
    KEYWORD = "keyword"
    FIRST_MESSAGE = "first_message"


class FlowStepType(str, Enum):
    SEND_MESSAGE = "send_message"
    ADD_TAG = "add_tag"
    REMOVE_TAG = "remove_tag"
    SET_FIELD = "set_field"
    ASSIGN_USER = "assign_user"
    SET_STATUS = "set_status"
    DELAY = "delay"


class Flow(Base):
    __tablename__ = "flows"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_workspace_flow_name"),
        Index("ix_flows_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[FlowStatus] = mapped_column(SqlEnum(FlowStatus), default=FlowStatus.DRAFT, index=True)
    trigger_type: Mapped[FlowTriggerType] = mapped_column(SqlEnum(FlowTriggerType), default=FlowTriggerType.MANUAL)
    trigger_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stop_on_reply: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    steps: Mapped[list["FlowStep"]] = relationship(
        back_populates="flow",
        cascade="all, delete-orphan",
        order_by="FlowStep.sort_order",
    )


class FlowStep(Base):
    __tablename__ = "flow_steps"
    __table_args__ = (
        UniqueConstraint("flow_id", "sort_order", name="uq_flow_step_sort_order"),
        Index("ix_flow_steps_flow_sort", "flow_id", "sort_order"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    flow_id: Mapped[int] = mapped_column(ForeignKey("flows.id", ondelete="CASCADE"), index=True)
    step_type: Mapped[FlowStepType] = mapped_column(SqlEnum(FlowStepType))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    flow: Mapped[Flow] = relationship(back_populates="steps")
