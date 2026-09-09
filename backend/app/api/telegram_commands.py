import json
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_admin
from app.flow_channel_models import FlowChannelTarget
from app.flow_models import Flow, FlowNode, FlowNodeType, FlowStatus
from app.services.telegram import TelegramError, telegram_api
from app.telegram_models import TelegramBot

router = APIRouter(prefix="/telegram/bots", tags=["Telegram Commands"])
COMMAND_RE = re.compile(r"^[a-z0-9_]{1,32}$")

class CommandIn(BaseModel):
    command: str = Field(min_length=1, max_length=33)
    description: str = Field(min_length=1, max_length=256)
    flow_id: int | None = None
    enabled: bool = True

    @field_validator("command")
    @classmethod
    def clean_command(cls, value: str):
        value = value.strip().lstrip("/").lower()
        if not COMMAND_RE.fullmatch(value):
            raise ValueError("Use 1-32 lowercase letters, numbers or underscores")
        return value

class CommandsIn(BaseModel):
    commands: list[CommandIn] = Field(default_factory=list, max_length=100)


def _bot(db: Session, bot_db_id: int):
    bot = db.scalar(select(TelegramBot).where(TelegramBot.id == bot_db_id))
    if not bot:
        raise HTTPException(status_code=404, detail="Telegram bot not found")
    return bot


def _phrases(value):
    raw = str(value or "").strip()
    if not raw:
        return []
    for _ in range(2):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
            if isinstance(parsed, str) and parsed != raw:
                raw = parsed.strip(); continue
        except (TypeError, ValueError):
            pass
        break
    if "\n" in raw:
        return [x.strip() for x in raw.splitlines() if x.strip()]
    return [raw]


def _telegram_flows(db: Session, workspace_id: int):
    return db.scalars(
        select(Flow).join(FlowChannelTarget, FlowChannelTarget.flow_id == Flow.id)
        .where(Flow.workspace_id == workspace_id, FlowChannelTarget.channel == "telegram")
        .order_by(Flow.name.asc())
    ).all()


def _flow_commands(db: Session, workspace_id: int):
    result = {}
    for flow in _telegram_flows(db, workspace_id):
        trigger = db.scalar(select(FlowNode).where(FlowNode.flow_id == flow.id, FlowNode.node_type == FlowNodeType.TRIGGER).order_by(FlowNode.id.asc()))
        if not trigger:
            continue
        try: cfg = json.loads(trigger.config_json or "{}")
        except ValueError: cfg = {}
        if str(cfg.get("trigger_type") or "").lower() != "keyword":
            continue
        for phrase in _phrases(cfg.get("trigger_value")):
            if phrase.startswith("/"):
                result.setdefault(phrase[1:].lower(), flow.id)
    return result


@router.get("/{bot_db_id}/commands", dependencies=[Depends(require_admin)])
async def get_commands(bot_db_id: int, db: Session = Depends(get_db)):
    bot = _bot(db, bot_db_id)
    try:
        rows = await telegram_api(bot.access_token, "getMyCommands")
    except TelegramError as exc:
        raise HTTPException(status_code=502, detail=f"Could not read Telegram commands: {exc}") from exc
    flow_map = _flow_commands(db, bot.workspace_id)
    return [{"command": r.get("command"), "description": r.get("description"), "flow_id": flow_map.get(str(r.get("command") or "").lower()), "enabled": True} for r in (rows or [])]


@router.get("/{bot_db_id}/command-flows", dependencies=[Depends(require_admin)])
def command_flows(bot_db_id: int, db: Session = Depends(get_db)):
    bot = _bot(db, bot_db_id)
    return [{"id": f.id, "name": f.name, "status": getattr(f.status, "value", f.status)} for f in _telegram_flows(db, bot.workspace_id)]


@router.put("/{bot_db_id}/commands", dependencies=[Depends(require_admin)])
async def set_commands(bot_db_id: int, request: CommandsIn, db: Session = Depends(get_db)):
    bot = _bot(db, bot_db_id)
    enabled = [c for c in request.commands if c.enabled]
    names = [c.command for c in enabled]
    if len(names) != len(set(names)):
        raise HTTPException(status_code=400, detail="Each Telegram command may only appear once")

    flows = {f.id: f for f in _telegram_flows(db, bot.workspace_id)}
    assigned = {}
    for command in enabled:
        if command.flow_id is not None:
            if command.flow_id not in flows:
                raise HTTPException(status_code=400, detail=f"Flow {command.flow_id} is not a Telegram flow in this workspace")
            if command.flow_id in assigned:
                raise HTTPException(status_code=400, detail="Assign multiple commands to one flow in the flow's Trigger phrases editor instead")
            assigned[command.flow_id] = command.command

    # Reject a command that is already owned by a different active Telegram flow.
    existing = _flow_commands(db, bot.workspace_id)
    for command in enabled:
        owner = existing.get(command.command)
        if owner and command.flow_id and owner != command.flow_id:
            raise HTTPException(status_code=409, detail=f"/{command.command} is already a trigger on another Telegram flow")

    # Add the slash command to the selected flow's existing keyword phrases. We do
    # not remove unrelated phrases, so managing the bot menu cannot damage a flow.
    for flow_id, command_name in assigned.items():
        trigger = db.scalar(select(FlowNode).where(FlowNode.flow_id == flow_id, FlowNode.node_type == FlowNodeType.TRIGGER).order_by(FlowNode.id.asc()))
        if not trigger:
            raise HTTPException(status_code=400, detail=f"Flow {flow_id} has no Start Bot Flow node")
        try: cfg = json.loads(trigger.config_json or "{}")
        except ValueError: cfg = {}
        phrases = _phrases(cfg.get("trigger_value")) if str(cfg.get("trigger_type") or "").lower() == "keyword" else []
        slash = f"/{command_name}"
        if not any(p.lower() == slash.lower() for p in phrases):
            phrases.append(slash)
        cfg["trigger_type"] = "keyword"
        cfg["trigger_value"] = json.dumps(phrases, ensure_ascii=False)
        trigger.config_json = json.dumps(cfg, ensure_ascii=False)
        flow = flows[flow_id]
        flow.trigger_type = "keyword"
        flow.trigger_value = cfg["trigger_value"]

    payload = {"commands": [{"command": c.command, "description": c.description} for c in enabled]}
    try:
        if payload["commands"]:
            await telegram_api(bot.access_token, "setMyCommands", payload)
        else:
            await telegram_api(bot.access_token, "deleteMyCommands")
    except TelegramError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=f"Telegram command sync failed: {exc}") from exc
    db.commit()
    return {"ok": True, "count": len(enabled), "commands": [c.model_dump() for c in enabled]}
