"""Developer API external router compatibility layer.

The v0.2.0 application stores Telegram flows in the workspace attached to the
Telegram bot, while the first Developer API key is attached to the primary
WhatsApp workspace.  The normal Flows UI already resolves flows by channel,
not by the API-key workspace.  Keep that same behaviour here for flow listing
and triggering, then fall through to the existing Developer API router for all
other endpoints.
"""

import time

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.developer_api import (
    FlowTriggerRequest,
    _flow_channel,
    _log,
    _set_fields,
    external_router as legacy_external_router,
)
from app.core.database import get_db
from app.flow_channel_models import FlowChannelTarget
from app.flow_models import Flow, FlowStatus
from app.models import Contact, Conversation, WhatsAppPhoneNumber
from app.services.developer_api import DeveloperApiContext, require_scope
from app.services.external_flow_trigger import trigger_telegram_flow, trigger_whatsapp_flow
from app.telegram_models import TelegramBot, TelegramContact, TelegramConversation

router = APIRouter(tags=["Developer API v1"])


def _telegram_workspace_ids(db: Session) -> set[int]:
    """Return workspaces that are actually backed by an active Telegram bot."""
    return {
        int(workspace_id)
        for workspace_id in db.scalars(
            select(TelegramBot.workspace_id).where(TelegramBot.active.is_(True)).distinct()
        ).all()
    }


def _flow_is_visible(db: Session, ctx: DeveloperApiContext, flow: Flow, channel: str) -> bool:
    if channel == "telegram":
        return int(flow.workspace_id) in _telegram_workspace_ids(db)
    return int(flow.workspace_id) == int(ctx.workspace_id)


@router.get("/bot-flows")
def list_bot_flows(
    request: Request,
    channel: str | None = None,
    db: Session = Depends(get_db),
    ctx: DeveloperApiContext = Depends(require_scope("flows:read")),
):
    if channel not in {None, "whatsapp", "telegram"}:
        raise HTTPException(status_code=422, detail="channel must be whatsapp or telegram")

    started = time.perf_counter()
    rows = db.scalars(select(Flow).order_by(Flow.name)).all()
    result = []
    for flow in rows:
        flow_channel = _flow_channel(db, flow.id)
        if channel and flow_channel != channel:
            continue
        if not _flow_is_visible(db, ctx, flow, flow_channel):
            continue
        result.append(
            {
                "id": flow.id,
                "name": flow.name,
                "description": flow.description,
                "channel": flow_channel,
                "status": flow.status.value,
                "trigger_type": flow.trigger_type.value,
                "updated_at": flow.updated_at,
            }
        )

    _log(db, ctx, request, started, channel=channel)
    return {"data": result, "count": len(result)}


@router.post("/bot-flows/{flow_id}/trigger")
async def trigger_bot_flow(
    request: Request,
    flow_id: int,
    payload: FlowTriggerRequest,
    db: Session = Depends(get_db),
    ctx: DeveloperApiContext = Depends(require_scope("flows:trigger")),
):
    started = time.perf_counter()
    flow = db.get(Flow, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    channel = _flow_channel(db, flow.id)
    if not _flow_is_visible(db, ctx, flow, channel):
        raise HTTPException(status_code=404, detail="Flow not found")
    if flow.status != FlowStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Only active flows can be triggered")
    if payload.channel and payload.channel != channel:
        raise HTTPException(status_code=422, detail=f"Flow belongs to {channel}, not {payload.channel}")

    # Subscriber/contact data belongs to the channel workspace, which for
    # Telegram may intentionally differ from the primary WhatsApp workspace.
    channel_workspace_id = int(flow.workspace_id)
    if channel == "telegram":
        try:
            telegram_user_id = int(payload.subscriber)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Telegram subscriber must be the numeric Telegram user ID") from exc
        subscriber = db.scalar(
            select(TelegramContact).where(
                TelegramContact.workspace_id == channel_workspace_id,
                TelegramContact.telegram_user_id == telegram_user_id,
            )
        )
    else:
        wa_id = "".join(ch for ch in payload.subscriber if ch.isdigit())
        subscriber = db.scalar(
            select(Contact).where(Contact.workspace_id == channel_workspace_id, Contact.wa_id == wa_id)
        )

    if not subscriber:
        raise HTTPException(status_code=404, detail=f"{channel.title()} subscriber not found")

    if payload.fields:
        _set_fields(db, channel_workspace_id, subscriber.id, channel, payload.fields)
        db.flush()

    if channel == "telegram":
        conversation = db.scalar(
            select(TelegramConversation)
            .where(
                TelegramConversation.workspace_id == channel_workspace_id,
                TelegramConversation.contact_id == subscriber.id,
            )
            .order_by(TelegramConversation.last_message_at.desc(), TelegramConversation.id.desc())
            .limit(1)
        )
        if not conversation:
            raise HTTPException(status_code=409, detail="Telegram subscriber has no bot conversation to send through")
        try:
            _, session = await trigger_telegram_flow(db, flow, conversation, payload.restart)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        db.commit()
        state = session.status if session else "unknown"
        waiting_for = session.waiting_for if session else None
    else:
        conversation = None
        if payload.connection_id:
            conversation = db.scalar(
                select(Conversation).where(
                    Conversation.workspace_id == channel_workspace_id,
                    Conversation.contact_id == subscriber.id,
                    Conversation.phone_number_id == payload.connection_id,
                )
            )
        if not conversation:
            conversation = db.scalar(
                select(Conversation)
                .where(
                    Conversation.workspace_id == channel_workspace_id,
                    Conversation.contact_id == subscriber.id,
                )
                .order_by(Conversation.last_message_at.desc(), Conversation.id.desc())
                .limit(1)
            )
        if not conversation:
            phone = db.scalar(
                select(WhatsAppPhoneNumber)
                .join(WhatsAppPhoneNumber.account)
                .where(
                    WhatsAppPhoneNumber.active.is_(True),
                    WhatsAppPhoneNumber.account.has(workspace_id=channel_workspace_id),
                )
                .order_by(WhatsAppPhoneNumber.id)
                .limit(1)
            )
            if not phone:
                raise HTTPException(status_code=409, detail="No active WhatsApp number is connected to this workspace")
            conversation = Conversation(
                workspace_id=channel_workspace_id,
                phone_number_id=phone.id,
                contact_id=subscriber.id,
            )
            db.add(conversation)
            db.flush()
        try:
            _, session = await trigger_whatsapp_flow(db, flow, conversation, payload.restart)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        db.commit()
        state = session.status.value if session else "unknown"
        waiting_for = session.waiting_for if session else None

    result = {
        "ok": True,
        "flow_id": flow.id,
        "flow": flow.name,
        "channel": channel,
        "subscriber": f"{channel}:{subscriber.id}",
        "status": state,
        "waiting_for": waiting_for,
    }
    _log(db, ctx, request, started, channel=channel)
    return result


# Keep the rest of the already-proven Subscriber API unchanged.  These routes
# are included after the corrected flow routes so FastAPI resolves the two
# overrides above first.
router.include_router(legacy_external_router)
