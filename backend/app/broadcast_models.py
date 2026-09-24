from datetime import datetime
from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

class Broadcast(Base):
    __tablename__="broadcasts"
    __table_args__=(Index("ix_broadcasts_workspace_created","workspace_id","created_at"),Index("ix_broadcasts_status_scheduled","status","scheduled_at"))
    id:Mapped[int]=mapped_column(BigInteger,primary_key=True,autoincrement=True)
    workspace_id:Mapped[int]=mapped_column(ForeignKey("workspaces.id",ondelete="CASCADE"),index=True)
    channel:Mapped[str]=mapped_column(String(20),nullable=False,index=True)
    channel_account_id:Mapped[int]=mapped_column(BigInteger,nullable=False,index=True)
    name:Mapped[str]=mapped_column(String(150),nullable=False)
    message_text:Mapped[str]=mapped_column(Text,nullable=False)
    message_mode:Mapped[str]=mapped_column(String(20),nullable=False,default="freeform")
    provider_template_json:Mapped[str|None]=mapped_column(Text,nullable=True)
    parse_mode:Mapped[str]=mapped_column(String(20),nullable=False,default="HTML")
    media_url:Mapped[str|None]=mapped_column(Text,nullable=True)
    media_type:Mapped[str|None]=mapped_column(String(20),nullable=True)
    stagger_seconds:Mapped[float]=mapped_column(Float,nullable=False,default=0.05)
    last_sent_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
    audience_type:Mapped[str]=mapped_column(String(30),nullable=False,default="all")
    audience_filter_json:Mapped[str|None]=mapped_column(Text,nullable=True)
    audience_segment_id:Mapped[int|None]=mapped_column(ForeignKey("audience_segments.id",ondelete="SET NULL"),nullable=True,index=True)
    status:Mapped[str]=mapped_column(String(20),nullable=False,default="draft",index=True)
    scheduled_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
    started_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
    completed_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
    created_by_user_id:Mapped[int]=mapped_column(ForeignKey("users.id"),nullable=False)
    total_recipients:Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    sent_count:Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    failed_count:Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    created_at:Mapped[datetime]=mapped_column(DateTime,nullable=False,default=datetime.utcnow)
    updated_at:Mapped[datetime]=mapped_column(DateTime,nullable=False,default=datetime.utcnow,onupdate=datetime.utcnow)
    recipients:Mapped[list["BroadcastRecipient"]]=relationship(back_populates="broadcast",cascade="all, delete-orphan")

class BroadcastRecipient(Base):
    __tablename__="broadcast_recipients"
    __table_args__=(UniqueConstraint("broadcast_id","channel_contact_id",name="uq_broadcast_channel_contact"),Index("ix_broadcast_recipients_work","status","broadcast_id","id"))
    id:Mapped[int]=mapped_column(BigInteger,primary_key=True,autoincrement=True)
    broadcast_id:Mapped[int]=mapped_column(ForeignKey("broadcasts.id",ondelete="CASCADE"),index=True)
    channel_contact_id:Mapped[int]=mapped_column(BigInteger,nullable=False,index=True)
    conversation_id:Mapped[int]=mapped_column(BigInteger,nullable=False,index=True)
    destination:Mapped[str]=mapped_column(String(100),nullable=False)
    display_name:Mapped[str|None]=mapped_column(String(200),nullable=True)
    rendered_text:Mapped[str]=mapped_column(Text,nullable=False)
    status:Mapped[str]=mapped_column(String(20),nullable=False,default="pending",index=True)
    provider_message_id:Mapped[str|None]=mapped_column(String(100),nullable=True)
    attempts:Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    last_error:Mapped[str|None]=mapped_column(Text,nullable=True)
    sent_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime,nullable=False,default=datetime.utcnow)
    updated_at:Mapped[datetime]=mapped_column(DateTime,nullable=False,default=datetime.utcnow,onupdate=datetime.utcnow)
    broadcast:Mapped[Broadcast]=relationship(back_populates="recipients")
