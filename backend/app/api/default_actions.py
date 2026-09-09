from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_manager
from app.default_action_models import DefaultAction
from app.flow_channel_models import FlowChannelTarget
from app.flow_models import Flow
from app.models import Workspace
from app.telegram_models import TelegramBot

router = APIRouter(prefix="/default-actions", tags=["Default Actions"], dependencies=[Depends(require_manager)])

ACTION_TYPES = ("location", "image", "video", "audio", "document", "contact", "unmatched_text")
CHANNELS = ("whatsapp", "telegram")


class DefaultActionIn(BaseModel):
    flow_id: int | None = None
    enabled: bool = True


def _workspace_id(db: Session, channel: str) -> int:
    # Flow creation already treats Telegram's connected bot as the authority for
    # its workspace. Default Actions must resolve the same workspace or the flow
    # selector can appear empty even though Telegram flows exist.
    if channel == "telegram":
        wid = db.scalar(
            select(TelegramBot.workspace_id)
            .where(TelegramBot.active.is_(True))
            .order_by(TelegramBot.id.asc())
            .limit(1)
        )
        if wid is not None:
            return int(wid)
        raise HTTPException(400, "Connect a Telegram bot before configuring Telegram Default Actions")

    wid = db.scalar(select(Workspace.id).where(Workspace.active.is_(True)).order_by(Workspace.id).limit(1))
    if wid is None:
        wid = db.scalar(select(Workspace.id).order_by(Workspace.id).limit(1))
    if wid is None:
        raise HTTPException(400, "No workspace is available yet")
    return int(wid)


def _validate(channel: str, action_type: str | None = None):
    if channel not in CHANNELS:
        raise HTTPException(400, "channel must be whatsapp or telegram")
    if action_type is not None and action_type not in ACTION_TYPES:
        raise HTTPException(400, f"Unsupported Default Action: {action_type}")


def _flow(db: Session, wid: int, channel: str, flow_id: int):
    flow = db.get(Flow, flow_id)
    if not flow or flow.workspace_id != wid:
        raise HTTPException(404, "Flow not found")
    target = db.scalar(
        select(FlowChannelTarget.id).where(
            FlowChannelTarget.flow_id == flow.id,
            FlowChannelTarget.channel == channel,
        )
    )
    if not target:
        raise HTTPException(400, f"Flow is not enabled for {channel}")
    return flow


def _item(row, flow=None):
    return {
        "id": row.id if row else None,
        "action_type": row.action_type if row else None,
        "flow_id": row.flow_id if row else None,
        "flow_name": flow.name if flow else None,
        "enabled": bool(row.enabled) if row else False,
    }


# Keep this static route before /{channel}/{action_type}; it also makes the API
# shape unambiguous to Starlette and to generated API documentation.
@router.get("/{channel}/available/flows")
def available_flows(channel: str, db: Session = Depends(get_db)):
    _validate(channel)
    wid = _workspace_id(db, channel)
    rows = db.scalars(
        select(Flow)
        .join(FlowChannelTarget, FlowChannelTarget.flow_id == Flow.id)
        .where(
            Flow.workspace_id == wid,
            FlowChannelTarget.channel == channel,
        )
        .order_by(Flow.name.asc())
    ).all()
    return [{"id": f.id, "name": f.name, "status": f.status.value if hasattr(f.status, "value") else str(f.status)} for f in rows]


@router.get("/{channel}")
def list_default_actions(channel: str, db: Session = Depends(get_db)):
    _validate(channel)
    wid = _workspace_id(db, channel)
    rows = db.scalars(
        select(DefaultAction).where(
            DefaultAction.workspace_id == wid,
            DefaultAction.channel == channel,
        )
    ).all()
    by = {r.action_type: r for r in rows}
    result = []
    for action_type in ACTION_TYPES:
        row = by.get(action_type)
        flow = db.get(Flow, row.flow_id) if row and row.flow_id else None
        item = _item(row, flow)
        item["action_type"] = action_type
        result.append(item)
    return result


@router.put("/{channel}/{action_type}")
def set_default_action(channel: str, action_type: str, body: DefaultActionIn, db: Session = Depends(get_db)):
    _validate(channel, action_type)
    wid = _workspace_id(db, channel)
    flow = _flow(db, wid, channel, body.flow_id) if body.flow_id else None
    row = db.scalar(
        select(DefaultAction).where(
            DefaultAction.workspace_id == wid,
            DefaultAction.channel == channel,
            DefaultAction.action_type == action_type,
        )
    )
    if not row:
        row = DefaultAction(workspace_id=wid, channel=channel, action_type=action_type)
        db.add(row)
    row.flow_id = body.flow_id
    row.enabled = bool(body.enabled and body.flow_id)
    db.commit()
    db.refresh(row)
    return _item(row, flow)
