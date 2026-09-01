from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class HttpApi(Base):
    __tablename__ = "http_apis"
    __table_args__ = (Index("ix_http_apis_name", "name"), Index("ix_http_apis_active", "active"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    method: Mapped[str] = mapped_column(String(10), default="GET")
    endpoint_url: Mapped[str] = mapped_column(Text)
    headers_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    query_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    cookies_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_type: Mapped[str] = mapped_column(String(30), default="none")
    body_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_mappings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=15)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    total_calls: Mapped[int] = mapped_column(Integer, default=0)
    total_success: Mapped[int] = mapped_column(Integer, default=0)
    total_error: Mapped[int] = mapped_column(Integer, default=0)
    last_called_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class HttpApiCall(Base):
    __tablename__ = "http_api_calls"
    __table_args__ = (Index("ix_http_api_calls_api_created", "http_api_id", "created_at"), Index("ix_http_api_calls_success_created", "success", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    http_api_id: Mapped[int] = mapped_column(ForeignKey("http_apis.id", ondelete="CASCADE"), index=True)
    flow_run_id: Mapped[int | None] = mapped_column(ForeignKey("flow_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
