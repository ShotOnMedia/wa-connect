from datetime import datetime
from sqlalchemy import BigInteger,DateTime,ForeignKey,Index,Integer,String,Text,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column,relationship
from app.core.database import Base

class MessagingCampaign(Base):
    __tablename__="messaging_campaigns"
    __table_args__=(Index("ix_msg_campaign_workspace_channel","workspace_id","channel"),Index("ix_msg_campaign_status","status"),)
    id:Mapped[int]=mapped_column(BigInteger,primary_key=True,autoincrement=True)
    workspace_id:Mapped[int]=mapped_column(ForeignKey("workspaces.id",ondelete="CASCADE"),nullable=False,index=True)
    channel:Mapped[str]=mapped_column(String(20),nullable=False,index=True)
    channel_account_id:Mapped[int]=mapped_column(BigInteger,nullable=False,index=True)
    name:Mapped[str]=mapped_column(String(150),nullable=False)
    description:Mapped[str|None]=mapped_column(Text,nullable=True)
    status:Mapped[str]=mapped_column(String(20),nullable=False,default="draft",index=True)
    audience_type:Mapped[str]=mapped_column(String(30),nullable=False,default="all")
    audience_filter_json:Mapped[str|None]=mapped_column(Text,nullable=True)
    audience_segment_id:Mapped[int|None]=mapped_column(ForeignKey("audience_segments.id",ondelete="SET NULL"),nullable=True,index=True)
    scheduled_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
    started_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
    completed_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
    created_by_user_id:Mapped[int]=mapped_column(ForeignKey("users.id"),nullable=False)
    created_at:Mapped[datetime]=mapped_column(DateTime,nullable=False,default=datetime.utcnow)
    updated_at:Mapped[datetime]=mapped_column(DateTime,nullable=False,default=datetime.utcnow,onupdate=datetime.utcnow)
    steps:Mapped[list["MessagingCampaignStep"]]=relationship(back_populates="campaign",cascade="all, delete-orphan",order_by="MessagingCampaignStep.position")

class MessagingCampaignStep(Base):
    __tablename__="messaging_campaign_steps"
    __table_args__=(UniqueConstraint("campaign_id","position",name="uq_msg_campaign_step_position"),)
    id:Mapped[int]=mapped_column(BigInteger,primary_key=True,autoincrement=True)
    campaign_id:Mapped[int]=mapped_column(ForeignKey("messaging_campaigns.id",ondelete="CASCADE"),nullable=False,index=True)
    position:Mapped[int]=mapped_column(Integer,nullable=False)
    name:Mapped[str]=mapped_column(String(150),nullable=False)
    delay_seconds:Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    message_mode:Mapped[str]=mapped_column(String(20),nullable=False,default="freeform")
    message_text:Mapped[str]=mapped_column(Text,nullable=False)
    provider_template_json:Mapped[str|None]=mapped_column(Text,nullable=True)
    parse_mode:Mapped[str]=mapped_column(String(20),nullable=False,default="HTML")
    media_url:Mapped[str|None]=mapped_column(Text,nullable=True)
    media_type:Mapped[str|None]=mapped_column(String(20),nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime,nullable=False,default=datetime.utcnow)
    updated_at:Mapped[datetime]=mapped_column(DateTime,nullable=False,default=datetime.utcnow,onupdate=datetime.utcnow)
    campaign:Mapped[MessagingCampaign]=relationship(back_populates="steps")
