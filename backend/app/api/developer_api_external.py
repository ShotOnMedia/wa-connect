"""Developer API external router compatibility layer.

The v0.2.0 application stores Telegram data in the workspace attached to the
Telegram bot, while the first Developer API key is attached to the primary
WhatsApp workspace. The channel UIs already resolve their data by channel.
Keep that same behaviour here for flows and subscribers, then fall through to
the existing Developer API router for routes that do not need compatibility.
"""

from datetime import datetime
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.developer_api import (
    ConversationUpdate,
    FieldsUpdate,
    FlowTriggerRequest,
    SubscriberUpdate,
    TagAssign,
    _assign_tag,
    _conversation_out,
    _field_rows,
    _flow_channel,
    _log,
    _remove_tag,
    _set_fields,
    _subscriber_out,
    external_router as legacy_external_router,
)
from app.core.database import get_db
from app.flow_models import Flow, FlowStatus
from app.models import Contact, Conversation, ConversationStatus, User, WhatsAppPhoneNumber
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


def _parse_subscriber_ref(ref: str, channel: str | None = None) -> tuple[str, int]:
    raw = str(ref).strip()
    if ":" in raw:
        kind, ident = raw.split(":", 1)
        if kind not in {"whatsapp", "telegram"}:
            raise HTTPException(status_code=422, detail="Subscriber reference must start with whatsapp: or telegram:")
    else:
        kind, ident = channel or "whatsapp", raw
    try:
        return kind, int(ident)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid subscriber reference") from exc


def _subscriber_for_api(db: Session, ctx: DeveloperApiContext, ref: str, channel: str | None = None):
    """Resolve a stable API subscriber reference against its channel workspace."""
    kind, ident = _parse_subscriber_ref(ref, channel)
    if kind == "telegram":
        workspace_ids = _telegram_workspace_ids(db)
        if not workspace_ids:
            raise HTTPException(status_code=404, detail="Subscriber not found")
        row = db.scalar(
            select(TelegramContact).where(
                TelegramContact.id == ident,
                TelegramContact.workspace_id.in_(workspace_ids),
            )
        )
    else:
        row = db.scalar(
            select(Contact).where(Contact.id == ident, Contact.workspace_id == ctx.workspace_id)
        )
    if not row:
        raise HTTPException(status_code=404, detail="Subscriber not found")
    return kind, row


@router.get("/subscribers")
def list_subscribers(
    request: Request,
    channel: str | None = None,
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    ctx: DeveloperApiContext = Depends(require_scope("subscribers:read")),
):
    if channel not in {None, "whatsapp", "telegram"}:
        raise HTTPException(status_code=422, detail="channel must be whatsapp or telegram")
    started = time.perf_counter()
    result = []

    if channel in (None, "whatsapp"):
        stmt = select(Contact).where(Contact.workspace_id == ctx.workspace_id)
        if q:
            term = f"%{q.strip()}%"
            stmt = stmt.where(or_(Contact.name.ilike(term), Contact.wa_id.ilike(term)))
        for row in db.scalars(stmt.order_by(Contact.updated_at.desc()).limit(limit)).all():
            result.append(_subscriber_out(db, "whatsapp", row))

    if channel in (None, "telegram") and len(result) < limit:
        workspace_ids = _telegram_workspace_ids(db)
        if workspace_ids:
            stmt = select(TelegramContact).where(TelegramContact.workspace_id.in_(workspace_ids))
            if q:
                term = f"%{q.strip()}%"
                stmt = stmt.where(
                    or_(
                        TelegramContact.first_name.ilike(term),
                        TelegramContact.last_name.ilike(term),
                        TelegramContact.username.ilike(term),
                    )
                )
            for row in db.scalars(
                stmt.order_by(TelegramContact.updated_at.desc()).limit(limit - len(result))
            ).all():
                result.append(_subscriber_out(db, "telegram", row))

    _log(db, ctx, request, started, channel=channel)
    return {"data": result, "count": len(result)}


@router.get("/subscribers/{subscriber_ref}")
def get_subscriber(
    request: Request,
    subscriber_ref: str,
    channel: str | None = None,
    db: Session = Depends(get_db),
    ctx: DeveloperApiContext = Depends(require_scope("subscribers:read")),
):
    started = time.perf_counter()
    kind, row = _subscriber_for_api(db, ctx, subscriber_ref, channel)
    result = _subscriber_out(db, kind, row)
    _log(db, ctx, request, started, channel=kind)
    return result


@router.patch("/subscribers/{subscriber_ref}")
def update_subscriber(
    request: Request,
    subscriber_ref: str,
    payload: SubscriberUpdate,
    db: Session = Depends(get_db),
    ctx: DeveloperApiContext = Depends(require_scope("subscribers:write")),
):
    started = time.perf_counter()
    kind, row = _subscriber_for_api(db, ctx, subscriber_ref)
    if payload.name is not None:
        if kind == "telegram":
            parts = payload.name.strip().split(" ", 1)
            row.first_name = parts[0] if parts else None
            row.last_name = parts[1] if len(parts) > 1 else None
        else:
            row.name = payload.name.strip() or None
    if payload.fields is not None:
        _set_fields(db, row.workspace_id, row.id, kind, payload.fields)
    row.updated_at = datetime.utcnow()
    db.commit()
    result = _subscriber_out(db, kind, row)
    _log(db, ctx, request, started, channel=kind)
    return result


@router.delete("/subscribers/{subscriber_ref}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subscriber(
    request: Request,
    subscriber_ref: str,
    db: Session = Depends(get_db),
    ctx: DeveloperApiContext = Depends(require_scope("subscribers:write")),
):
    started = time.perf_counter()
    kind, row = _subscriber_for_api(db, ctx, subscriber_ref)
    if kind == "whatsapp":
        row.archived_at = datetime.utcnow()
        row.updated_at = datetime.utcnow()
    else:
        db.delete(row)
    db.commit()
    _log(db, ctx, request, started, 204, kind)


@router.get("/subscribers/{subscriber_ref}/fields")
def subscriber_fields(
    request: Request,
    subscriber_ref: str,
    db: Session = Depends(get_db),
    ctx: DeveloperApiContext = Depends(require_scope("fields:read")),
):
    started = time.perf_counter()
    kind, row = _subscriber_for_api(db, ctx, subscriber_ref)
    result = _field_rows(db, row.workspace_id, row.id, kind)
    _log(db, ctx, request, started, channel=kind)
    return {"subscriber": f"{kind}:{row.id}", "fields": result}


@router.patch("/subscribers/{subscriber_ref}/fields")
def update_subscriber_fields(
    request: Request,
    subscriber_ref: str,
    payload: FieldsUpdate,
    db: Session = Depends(get_db),
    ctx: DeveloperApiContext = Depends(require_scope("fields:write")),
):
    started = time.perf_counter()
    kind, row = _subscriber_for_api(db, ctx, subscriber_ref)
    values = _set_fields(db, row.workspace_id, row.id, kind, payload.fields)
    db.commit()
    _log(db, ctx, request, started, channel=kind)
    return {"subscriber": f"{kind}:{row.id}", "fields": values}


@router.post("/subscribers/{subscriber_ref}/tags")
def add_subscriber_tag(
    request: Request,
    subscriber_ref: str,
    payload: TagAssign,
    db: Session = Depends(get_db),
    ctx: DeveloperApiContext = Depends(require_scope("tags:write")),
):
    started = time.perf_counter()
    kind, row = _subscriber_for_api(db, ctx, subscriber_ref)
    tag = _assign_tag(db, row.workspace_id, row.id, kind, payload.tag_id, payload.name)
    db.commit()
    _log(db, ctx, request, started, channel=kind)
    return {"id": tag.id, "name": tag.name}


@router.delete("/subscribers/{subscriber_ref}/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_subscriber_tag(
    request: Request,
    subscriber_ref: str,
    tag_id: int,
    db: Session = Depends(get_db),
    ctx: DeveloperApiContext = Depends(require_scope("tags:write")),
):
    started = time.perf_counter()
    kind, row = _subscriber_for_api(db, ctx, subscriber_ref)
    _remove_tag(db, row.id, kind, tag_id)
    db.commit()
    _log(db, ctx, request, started, 204, kind)


@router.patch("/subscribers/{subscriber_ref}/conversation")
def update_conversation(
    request: Request,
    subscriber_ref: str,
    payload: ConversationUpdate,
    db: Session = Depends(get_db),
    ctx: DeveloperApiContext = Depends(require_scope("conversations:write")),
):
    started = time.perf_counter()
    kind, row = _subscriber_for_api(db, ctx, subscriber_ref)
    if kind == "telegram":
        conversation = db.scalar(
            select(TelegramConversation)
            .where(
                TelegramConversation.workspace_id == row.workspace_id,
                TelegramConversation.contact_id == row.id,
            )
            .order_by(TelegramConversation.last_message_at.desc(), TelegramConversation.id.desc())
            .limit(1)
        )
    else:
        conversation = db.scalar(
            select(Conversation)
            .where(Conversation.workspace_id == row.workspace_id, Conversation.contact_id == row.id)
            .order_by(Conversation.last_message_at.desc(), Conversation.id.desc())
            .limit(1)
        )
    if not conversation:
        raise HTTPException(status_code=404, detail="Subscriber has no conversation")
    if payload.status is not None:
        conversation.status = payload.status if kind == "telegram" else ConversationStatus(payload.status)
    if "assigned_user_id" in payload.model_fields_set:
        if payload.assigned_user_id is not None and not db.scalar(
            select(User.id).where(User.id == payload.assigned_user_id, User.active.is_(True))
        ):
            raise HTTPException(status_code=422, detail="Assigned user not found or inactive")
        conversation.assigned_user_id = payload.assigned_user_id
    db.commit()
    result = _conversation_out(db, kind, row.id)
    _log(db, ctx, request, started, channel=kind)
    return result


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


# Compatibility routes are registered before the legacy router so FastAPI
# resolves these channel-aware implementations first.
router.include_router(legacy_external_router)
