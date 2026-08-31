import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_admin, require_user
from app.models import Workspace
from app.services.telegram import TelegramError, set_webhook, verify_bot, webhook_info
from app.telegram_models import TelegramBot, TelegramContact, TelegramConversation, TelegramMessage

router = APIRouter(prefix="/telegram", tags=["Telegram"])


class TelegramVerifyIn(BaseModel):
    bot_token: str = Field(min_length=20)


class TelegramConnectIn(BaseModel):
    workspace_name: str = Field(min_length=1, max_length=150)
    workspace_slug: str = Field(min_length=1, max_length=150)
    bot_token: str = Field(min_length=20)
    webhook_base_url: str = Field(min_length=8, max_length=500)

    @field_validator("webhook_base_url")
    @classmethod
    def validate_webhook_base_url(cls, value: str):
        value = value.strip().rstrip("/")
        if not value.startswith("https://"):
            raise ValueError("Telegram webhooks require an HTTPS public URL")
        return value


class TelegramBotOut(BaseModel):
    id: int
    workspace_id: int
    workspace_name: str
    workspace_slug: str
    bot_id: int
    username: str | None = None
    first_name: str | None = None
    active: bool
    webhook_url: str | None = None
    has_token: bool = True
    created_at: datetime


class TelegramStatsOut(BaseModel):
    bots: int
    contacts: int
    conversations: int
    messages: int
    unread: int


def bot_out(bot: TelegramBot, workspace: Workspace) -> TelegramBotOut:
    return TelegramBotOut(
        id=bot.id,
        workspace_id=workspace.id,
        workspace_name=workspace.name,
        workspace_slug=workspace.slug,
        bot_id=bot.bot_id,
        username=bot.username,
        first_name=bot.first_name,
        active=bot.active,
        webhook_url=bot.webhook_url,
        has_token=bool(bot.access_token),
        created_at=bot.created_at,
    )


@router.post("/verify", dependencies=[Depends(require_admin)])
async def verify_telegram_bot(request: TelegramVerifyIn):
    try:
        return {"connected": True, **await verify_bot(request.bot_token.strip())}
    except TelegramError as exc:
        raise HTTPException(status_code=502, detail=f"Telegram verification failed: {exc}") from exc


@router.get("/bots", response_model=list[TelegramBotOut], dependencies=[Depends(require_admin)])
def list_bots(db: Session = Depends(get_db)):
    rows = db.execute(
        select(TelegramBot, Workspace)
        .join(Workspace, Workspace.id == TelegramBot.workspace_id)
        .order_by(TelegramBot.created_at.asc())
    ).all()
    return [bot_out(bot, workspace) for bot, workspace in rows]


@router.post("/bots", response_model=TelegramBotOut, status_code=201, dependencies=[Depends(require_admin)])
async def connect_bot(request: TelegramConnectIn, db: Session = Depends(get_db)):
    token = request.bot_token.strip()
    try:
        verified = await verify_bot(token)
    except TelegramError as exc:
        raise HTTPException(status_code=502, detail=f"Telegram verification failed: {exc}") from exc

    workspace = db.scalar(select(Workspace).where(Workspace.slug == request.workspace_slug.strip()))
    if not workspace:
        workspace = Workspace(name=request.workspace_name.strip(), slug=request.workspace_slug.strip())
        db.add(workspace)
        db.flush()

    bot = db.scalar(select(TelegramBot).where(TelegramBot.bot_id == verified["bot_id"]))
    if bot and bot.workspace_id != workspace.id:
        raise HTTPException(status_code=409, detail="This Telegram bot is already connected to another workspace")

    if not bot:
        bot = TelegramBot(
            workspace_id=workspace.id,
            bot_id=verified["bot_id"],
            username=verified.get("username"),
            first_name=verified.get("first_name"),
            access_token=token,
            webhook_secret=secrets.token_urlsafe(32),
            active=True,
        )
        db.add(bot)
        db.flush()
    else:
        bot.username = verified.get("username")
        bot.first_name = verified.get("first_name")
        bot.access_token = token
        bot.active = True
        if not bot.webhook_secret:
            bot.webhook_secret = secrets.token_urlsafe(32)

    webhook_url = f"{request.webhook_base_url}{settings.api_prefix}/webhooks/telegram/{bot.bot_id}"
    try:
        await set_webhook(token, webhook_url, bot.webhook_secret)
    except TelegramError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=f"Bot verified, but webhook registration failed: {exc}") from exc

    bot.webhook_url = webhook_url
    db.commit()
    db.refresh(bot)
    return bot_out(bot, workspace)


@router.get("/bots/{bot_db_id}/health", dependencies=[Depends(require_admin)])
async def bot_health(bot_db_id: int, db: Session = Depends(get_db)):
    bot = db.scalar(select(TelegramBot).where(TelegramBot.id == bot_db_id))
    if not bot:
        raise HTTPException(status_code=404, detail="Telegram bot not found")
    try:
        identity = await verify_bot(bot.access_token)
        webhook = await webhook_info(bot.access_token)
        return {"connected": True, "identity": identity, "webhook": webhook}
    except TelegramError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/stats", response_model=TelegramStatsOut, dependencies=[Depends(require_user)])
def telegram_stats(db: Session = Depends(get_db)):
    bots = db.scalar(select(func.count()).select_from(TelegramBot).where(TelegramBot.active.is_(True))) or 0
    contacts = db.scalar(select(func.count()).select_from(TelegramContact)) or 0
    conversations = db.scalar(select(func.count()).select_from(TelegramConversation)) or 0
    messages = db.scalar(select(func.count()).select_from(TelegramMessage)) or 0
    unread = db.scalar(
        select(func.count()).select_from(TelegramConversation).where(
            TelegramConversation.last_message_at.is_not(None),
            (TelegramConversation.last_read_at.is_(None)) | (TelegramConversation.last_read_at < TelegramConversation.last_message_at),
        )
    ) or 0
    return TelegramStatsOut(bots=bots, contacts=contacts, conversations=conversations, messages=messages, unread=unread)
