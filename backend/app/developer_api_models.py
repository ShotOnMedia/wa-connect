from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DeveloperApiKey(Base):
    __tablename__ = "developer_api_keys"
    __table_args__ = (
        Index("ix_developer_api_keys_workspace_active", "workspace_id", "active"),
        Index("ix_developer_api_keys_prefix", "key_prefix"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    key_prefix: Mapped[str] = mapped_column(String(24), unique=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    scopes_json: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DeveloperApiRequestLog(Base):
    __tablename__ = "developer_api_request_logs"
    __table_args__ = (
        Index("ix_developer_api_logs_workspace_created", "workspace_id", "created_at"),
        Index("ix_developer_api_logs_key_created", "api_key_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    api_key_id: Mapped[int | None] = mapped_column(ForeignKey("developer_api_keys.id", ondelete="SET NULL"), nullable=True, index=True)
    method: Mapped[str] = mapped_column(String(12))
    path: Mapped[str] = mapped_column(String(255))
    status_code: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    channel: Mapped[str | None] = mapped_column(String(20), nullable=True)
    remote_addr: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
