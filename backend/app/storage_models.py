from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class MediaStorageSetting(Base):
    __tablename__ = "media_storage_settings"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(20), default="local")
    local_path: Mapped[str] = mapped_column(String(500), default="/app/storage/inbound-media")
    public_base_url: Mapped[str|None] = mapped_column(String(1000), nullable=True)
    max_upload_mb: Mapped[int] = mapped_column(Integer, default=25)
    s3_endpoint_url: Mapped[str|None] = mapped_column(String(1000), nullable=True)
    s3_region: Mapped[str|None] = mapped_column(String(100), nullable=True)
    s3_bucket: Mapped[str|None] = mapped_column(String(255), nullable=True)
    s3_access_key_enc: Mapped[str|None] = mapped_column(Text, nullable=True)
    s3_secret_key_enc: Mapped[str|None] = mapped_column(Text, nullable=True)
    s3_prefix: Mapped[str|None] = mapped_column(String(500), nullable=True)
    s3_use_ssl: Mapped[bool] = mapped_column(Boolean, default=True)
    s3_path_style: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MediaAsset(Base):
    __tablename__ = "media_assets"
    __table_args__ = (Index("ix_media_assets_workspace_created","workspace_id","created_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id",ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(150), nullable=False)
    media_type: Mapped[str] = mapped_column(String(20), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
