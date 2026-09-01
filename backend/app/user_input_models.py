from datetime import datetime
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class UserInputSubmission(Base):
    __tablename__="user_input_submissions"
    __table_args__=(Index("ix_user_input_flow_channel_started","flow_id","channel","started_at"),)
    id:Mapped[int]=mapped_column(BigInteger,primary_key=True,autoincrement=True)
    workspace_id:Mapped[int]=mapped_column(ForeignKey("workspaces.id",ondelete="CASCADE"),index=True)
    flow_id:Mapped[int]=mapped_column(ForeignKey("flows.id",ondelete="CASCADE"),index=True)
    campaign_node_id:Mapped[int]=mapped_column(ForeignKey("flow_nodes.id",ondelete="CASCADE"),index=True)
    channel:Mapped[str]=mapped_column(String(20),index=True)
    conversation_id:Mapped[int]=mapped_column(BigInteger,index=True)
    contact_id:Mapped[int]=mapped_column(BigInteger,index=True)
    status:Mapped[str]=mapped_column(String(20),default="active",index=True)
    webhook_url:Mapped[str|None]=mapped_column(Text,nullable=True)
    started_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
    completed_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)

class UserInputAnswer(Base):
    __tablename__="user_input_answers"
    __table_args__=(Index("ix_user_input_answers_submission","submission_id","id"),)
    id:Mapped[int]=mapped_column(BigInteger,primary_key=True,autoincrement=True)
    submission_id:Mapped[int]=mapped_column(ForeignKey("user_input_submissions.id",ondelete="CASCADE"),index=True)
    question_node_id:Mapped[int]=mapped_column(ForeignKey("flow_nodes.id",ondelete="CASCADE"),index=True)
    answer_key:Mapped[str]=mapped_column(String(120))
    question_text:Mapped[str|None]=mapped_column(Text,nullable=True)
    value_text:Mapped[str|None]=mapped_column(Text,nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)