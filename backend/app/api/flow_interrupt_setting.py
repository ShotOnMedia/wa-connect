from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_user
from app.flow_models import Flow
from app.models import User

router = APIRouter(prefix="/flows", tags=["flows"])


class InterruptSetting(BaseModel):
    interrupt_active_flow: bool


def _require_manager(user: User) -> None:
    if user.role.value not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="Only admins and managers can manage flows")


@router.get("/{flow_id}/interrupt-setting")
def get_interrupt_setting(flow_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    flow = db.get(Flow, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    return {"interrupt_active_flow": bool(flow.interrupt_active_flow)}


@router.put("/{flow_id}/interrupt-setting")
def set_interrupt_setting(payload: InterruptSetting, flow_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    _require_manager(user)
    flow = db.get(Flow, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    flow.interrupt_active_flow = bool(payload.interrupt_active_flow)
    db.commit()
    return {"interrupt_active_flow": bool(flow.interrupt_active_flow)}
