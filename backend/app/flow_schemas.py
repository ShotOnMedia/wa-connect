from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.flow_models import FlowStatus, FlowStepType, FlowTriggerType


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
