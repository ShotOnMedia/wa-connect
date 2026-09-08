"""Universal-selector Developer API bot-flow trigger route."""
import time
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.developer_api import FlowTriggerRequest, _flow_channel, _log, _set_fields
from app.api.developer_api_external import _visible
from app.core.database import get_db
from app.flow_models import Flow, FlowStatus
from app.models import Contact, Conversation, WhatsAppPhoneNumber
from app.services.developer_api import DeveloperApiContext, require_scope
from app.services.external_flow_trigger import trigger_telegram_flow, trigger_whatsapp_flow
from app.services.subscriber_resolver import resolve_subscriber
from app.telegram_models import TelegramConversation

router = APIRouter(tags=["Developer API v1"])


@router.post("/bot-flows/{flow_id}/trigger")
async def trigger_with_universal_subscriber(
    request: Request,
    flow_id: int,
    payload: FlowTriggerRequest,
    db: Session = Depends(get_db),
    ctx: DeveloperApiContext = Depends(require_scope("flows:trigger")),
):
    started = time.perf_counter()
    flow = db.get(Flow, flow_id)
    if not flow:
        raise HTTPException(404, "Flow not found")
    channel = _flow_channel(db, flow.id)
    if not _visible(db, ctx, flow, channel):
        raise HTTPException(404, "Flow not found")
    if flow.status != FlowStatus.ACTIVE:
        raise HTTPException(409, "Only active flows can be triggered")
    if payload.channel and payload.channel != channel:
        raise HTTPException(422, f"Flow belongs to {channel}, not {payload.channel}")

    kind, sub = resolve_subscriber(db, int(ctx.workspace_id), payload.subscriber, channel)
    if kind != channel:
        raise HTTPException(422, f"Flow belongs to {channel}, but subscriber belongs to {kind}")
    wid = int(flow.workspace_id)
    if int(sub.workspace_id) != wid:
        raise HTTPException(404, f"{channel.title()} subscriber not found in this flow workspace")

    if payload.fields:
        _set_fields(db, wid, sub.id, channel, payload.fields)
        db.flush()

    if channel == "telegram":
        conv = db.scalar(select(TelegramConversation).where(
            TelegramConversation.workspace_id == wid,
            TelegramConversation.contact_id == sub.id,
        ).order_by(TelegramConversation.last_message_at.desc(), TelegramConversation.id.desc()).limit(1))
        if not conv:
            raise HTTPException(409, "Telegram subscriber has no bot conversation to send through")
        try:
            _, session = await trigger_telegram_flow(db, flow, conv, payload.restart)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        db.commit()
        state = session.status if session else "unknown"
        waiting = session.waiting_for if session else None
    else:
        conv = db.scalar(select(Conversation).where(Conversation.contact_id == sub.id).order_by(
            Conversation.last_message_at.desc(), Conversation.id.desc()).limit(1))
        if payload.connection_id:
            conv = db.scalar(select(Conversation).where(
                Conversation.contact_id == sub.id,
                Conversation.phone_number_id == payload.connection_id,
            )) or conv
        if not conv:
            phone = db.scalar(select(WhatsAppPhoneNumber).join(WhatsAppPhoneNumber.account).where(
                WhatsAppPhoneNumber.active.is_(True),
                WhatsAppPhoneNumber.account.has(workspace_id=wid),
            ).order_by(WhatsAppPhoneNumber.id).limit(1))
            if not phone:
                raise HTTPException(409, "No active WhatsApp number is connected to this workspace")
            conv = Conversation(workspace_id=wid, phone_number_id=phone.id, contact_id=sub.id)
            db.add(conv)
            db.flush()
        try:
            _, session = await trigger_whatsapp_flow(db, flow, conv, payload.restart)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        db.commit()
        state = session.status.value if session else "unknown"
        waiting = session.waiting_for if session else None

    out = {"ok": True, "flow_id": flow.id, "flow": flow.name, "channel": channel,
           "subscriber": f"{channel}:{sub.id}", "status": state, "waiting_for": waiting}
    _log(db, ctx, request, started, channel=channel)
    return out
