from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, Boolean, DateTime, Enum as SqlEnum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

class FlowStatus(str, Enum):
    DRAFT="draft"; ACTIVE="active"; PAUSED="paused"
class FlowTriggerType(str, Enum):
    MANUAL="manual"; KEYWORD="keyword"; FIRST_MESSAGE="first_message"
class FlowStepType(str, Enum):
    SEND_MESSAGE="send_message"; ADD_TAG="add_tag"; REMOVE_TAG="remove_tag"; SET_FIELD="set_field"; ASSIGN_USER="assign_user"; SET_STATUS="set_status"; DELAY="delay"
class FlowNodeType(str, Enum):
    TRIGGER="trigger"; SEND_MESSAGE="send_message"; IMAGE="image"; VIDEO="video"; AUDIO="audio"; FILE="file"; QUESTION="question"; INTERACTIVE="interactive"; BUTTON="button"; COMMERCE="commerce"; TEMPLATE="template"; ADD_TAG="add_tag"; REMOVE_TAG="remove_tag"; SET_FIELD="set_field"; ASSIGN_USER="assign_user"; SET_STATUS="set_status"; CONDITION="condition"; DELAY="delay"; HTTP_REQUEST="http_request"
class FlowSessionStatus(str, Enum):
    ACTIVE="active"; WAITING="waiting"; COMPLETED="completed"; RESET="reset"; FAILED="failed"

class Flow(Base):
    __tablename__="flows"; __table_args__=(UniqueConstraint("workspace_id","name",name="uq_workspace_flow_name"),Index("ix_flows_workspace_status","workspace_id","status"),)
    id:Mapped[int]=mapped_column(BigInteger,primary_key=True,autoincrement=True); workspace_id:Mapped[int]=mapped_column(ForeignKey("workspaces.id",ondelete="CASCADE"),index=True); name:Mapped[str]=mapped_column(String(150)); description:Mapped[str|None]=mapped_column(Text,nullable=True); status:Mapped[FlowStatus]=mapped_column(SqlEnum(FlowStatus),default=FlowStatus.DRAFT,index=True); trigger_type:Mapped[FlowTriggerType]=mapped_column(SqlEnum(FlowTriggerType),default=FlowTriggerType.MANUAL); trigger_value:Mapped[str|None]=mapped_column(String(255),nullable=True); stop_on_reply:Mapped[bool]=mapped_column(Boolean,default=False); created_by_user_id:Mapped[int|None]=mapped_column(ForeignKey("users.id",ondelete="SET NULL"),nullable=True,index=True); created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow); updated_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow,onupdate=datetime.utcnow)
    steps:Mapped[list["FlowStep"]]=relationship(back_populates="flow",cascade="all, delete-orphan",order_by="FlowStep.sort_order"); nodes:Mapped[list["FlowNode"]]=relationship(back_populates="flow",cascade="all, delete-orphan"); edges:Mapped[list["FlowEdge"]]=relationship(back_populates="flow",cascade="all, delete-orphan")
class FlowStep(Base):
    __tablename__="flow_steps"; __table_args__=(UniqueConstraint("flow_id","sort_order",name="uq_flow_step_sort_order"),Index("ix_flow_steps_flow_sort","flow_id","sort_order"),)
    id:Mapped[int]=mapped_column(BigInteger,primary_key=True,autoincrement=True); flow_id:Mapped[int]=mapped_column(ForeignKey("flows.id",ondelete="CASCADE"),index=True); sort_order:Mapped[int]=mapped_column(Integer); step_type:Mapped[FlowStepType]=mapped_column(SqlEnum(FlowStepType)); config_json:Mapped[str|None]=mapped_column(Text,nullable=True); created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow); updated_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow,onupdate=datetime.utcnow); flow:Mapped[Flow]=relationship(back_populates="steps")
class FlowNode(Base):
    __tablename__="flow_nodes"; __table_args__=(Index("ix_flow_nodes_flow_type","flow_id","node_type"),)
    id:Mapped[int]=mapped_column(BigInteger,primary_key=True,autoincrement=True); flow_id:Mapped[int]=mapped_column(ForeignKey("flows.id",ondelete="CASCADE"),index=True); node_type:Mapped[FlowNodeType]=mapped_column(SqlEnum(FlowNodeType)); title:Mapped[str|None]=mapped_column(String(150),nullable=True); config_json:Mapped[str|None]=mapped_column(Text,nullable=True); position_x:Mapped[int]=mapped_column(Integer,default=0); position_y:Mapped[int]=mapped_column(Integer,default=0); created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow); updated_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow,onupdate=datetime.utcnow); flow:Mapped[Flow]=relationship(back_populates="nodes")
class FlowEdge(Base):
    __tablename__="flow_edges"; __table_args__=(Index("ix_flow_edges_flow_source","flow_id","source_node_id"),)
    id:Mapped[int]=mapped_column(BigInteger,primary_key=True,autoincrement=True); flow_id:Mapped[int]=mapped_column(ForeignKey("flows.id",ondelete="CASCADE"),index=True); source_node_id:Mapped[int]=mapped_column(ForeignKey("flow_nodes.id",ondelete="CASCADE")); target_node_id:Mapped[int]=mapped_column(ForeignKey("flow_nodes.id",ondelete="CASCADE")); source_handle:Mapped[str]=mapped_column(String(50),default="next"); target_handle:Mapped[str]=mapped_column(String(50),default="input"); sort_order:Mapped[int]=mapped_column(Integer,default=0); created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class FlowSession(Base):
    __tablename__="flow_sessions"; __table_args__=(UniqueConstraint("conversation_id",name="uq_flow_session_conversation"),Index("ix_flow_sessions_status_updated","status","updated_at"),)
    id:Mapped[int]=mapped_column(BigInteger,primary_key=True,autoincrement=True); conversation_id:Mapped[int]=mapped_column(ForeignKey("conversations.id",ondelete="CASCADE"),index=True); flow_id:Mapped[int]=mapped_column(ForeignKey("flows.id",ondelete="CASCADE"),index=True); current_node_id:Mapped[int|None]=mapped_column(ForeignKey("flow_nodes.id",ondelete="SET NULL"),nullable=True); status:Mapped[FlowSessionStatus]=mapped_column(SqlEnum(FlowSessionStatus),default=FlowSessionStatus.ACTIVE,index=True); waiting_for:Mapped[str|None]=mapped_column(String(50),nullable=True); last_inbound_message_id:Mapped[int|None]=mapped_column(ForeignKey("messages.id",ondelete="SET NULL"),nullable=True); started_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow); updated_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow,onupdate=datetime.utcnow); ended_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True); reset_by_user_id:Mapped[int|None]=mapped_column(ForeignKey("users.id",ondelete="SET NULL"),nullable=True)
