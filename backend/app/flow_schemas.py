from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.flow_models import FlowNodeType, FlowStatus, FlowStepType, FlowTriggerType


class FlowStepCreate(BaseModel):
    step_type: FlowStepType
    config: dict[str, Any] = Field(default_factory=dict)


class FlowStepUpdate(BaseModel):
    step_type: FlowStepType | None = None
    config: dict[str, Any] | None = None


class FlowStepOut(BaseModel):
    id: int
    step_type: FlowStepType
    sort_order: int
    config: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class FlowCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    trigger_type: FlowTriggerType = FlowTriggerType.MANUAL
    trigger_value: str | None = Field(default=None, max_length=255)
    stop_on_reply: bool = False

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Flow name cannot be blank")
        return value


class FlowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    status: FlowStatus | None = None
    trigger_type: FlowTriggerType | None = None
    trigger_value: str | None = Field(default=None, max_length=255)
    stop_on_reply: bool | None = None


class FlowOut(BaseModel):
    id: int
    workspace_id: int
    name: str
    description: str | None
    status: FlowStatus
    trigger_type: FlowTriggerType
    trigger_value: str | None
    stop_on_reply: bool
    step_count: int
    steps: list[FlowStepOut]
    created_at: datetime
    updated_at: datetime


class FlowReorderRequest(BaseModel):
    step_ids: list[int] = Field(min_length=1)


class FlowNodeCreate(BaseModel):
    node_type: FlowNodeType
    title: str | None = Field(default=None, max_length=150)
    config: dict[str, Any] = Field(default_factory=dict)
    position_x: int = 80
    position_y: int = 80


class FlowNodeUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=150)
    config: dict[str, Any] | None = None
    position_x: int | None = None
    position_y: int | None = None


class FlowNodeOut(BaseModel):
    id: int
    node_type: FlowNodeType
    title: str | None
    config: dict[str, Any]
    position_x: int
    position_y: int


class FlowEdgeCreate(BaseModel):
    source_node_id: int
    source_handle: str = Field(default="next", min_length=1, max_length=50)
    target_node_id: int
    target_handle: str = Field(default="input", min_length=1, max_length=50)


class FlowEdgeOut(BaseModel):
    id: int
    source_node_id: int
    source_handle: str
    target_node_id: int
    target_handle: str
    sort_order: int


class FlowGraphOut(BaseModel):
    flow_id: int
    nodes: list[FlowNodeOut]
    edges: list[FlowEdgeOut]
