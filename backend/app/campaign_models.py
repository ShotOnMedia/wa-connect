from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Campaign(Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_campaign_workspace_name"),
        Index("ix_campaign_workspace_status", "workspace_id", "status"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    channel_scope: Mapped[str] = mapped_column(String(20), default="both")
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    questions: Mapped[list["CampaignQuestion"]] = relationship(back_populates="campaign", cascade="all, delete-orphan", order_by="CampaignQuestion.sort_order")


class CampaignQuestion(Base):
    __tablename__ = "campaign_questions"
    __table_args__ = (
        UniqueConstraint("campaign_id", "sort_order", name="uq_campaign_question_order"),
        Index("ix_campaign_questions_campaign_order", "campaign_id", "sort_order"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(String(150), nullable=True)
    question_text: Mapped[str] = mapped_column(Text)
    answer_key: Mapped[str] = mapped_column(String(120))
    reply_type: Mapped[str] = mapped_column(String(40), default="text")
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    capture_field_id: Mapped[int | None] = mapped_column(ForeignKey("contact_field_definitions.id", ondelete="SET NULL"), nullable=True)
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    campaign: Mapped[Campaign] = relationship(back_populates="questions")
