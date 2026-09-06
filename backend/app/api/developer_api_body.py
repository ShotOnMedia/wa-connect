"""Body-first Developer API convenience actions.

These routes intentionally sit in front of the REST-style subscriber routes.
They make automation clients simpler by allowing a fixed endpoint with the
channel/subscriber supplied in JSON while retaining all existing path routes.
"""
from typing import Any, Literal
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.developer_api import _assign_tag, _conversation_out, _log, _remove_tag, _set_fields, _tag_rows
from app.api.developer_api_external import _telegram_workspace_ids
from app.core.database import get_db
from app.models import Contact, ContactFieldDefinition, ContactTag, Conversation, ConversationStatus, User
from app.services.developer_api import DeveloperApiContext, require_scope
from app.telegram_models import TelegramContact, TelegramConversation

router = APIRouter(tags=["Developer API v1"])
Channel = Literal["whatsapp", "telegram"]


class BodySubscriberFields(BaseModel):
    channel: Channel | None = None
    subscriber: str
    fields: dict[str, Any] = Field(default_factory=dict)


class BodySubscriberConversation(BaseModel):
    channel: Channel | None = None
    subscriber: str
    status: Literal["open", "pending", "resolved"] | None = None
    assigned_user_id: int | None = None


class BodySubscriberTags(BaseModel):
    channel: Channel | None = None
    subscriber: str
    tags: list[str | int] = Field(default_factory=list)
    tag_id: int | None = None
    name: str | None = None


def _resolve_body_subscriber(db: Session, ctx: DeveloperApiContext, channel: Channel | None, subscriber: str):
    """Resolve canonical refs, internal IDs, then external channel IDs.

    With an explicit channel, a short numeric value such as ``1`` is first
    treated as the WA Connect contact ID. If no such contact exists it falls
    back to Telegram user ID / WhatsApp wa_id. A canonical ``telegram:1`` or
    ``whatsapp:1`` is always an internal WA Connect contact reference.
    """
    raw = str(subscriber).strip()
    if not raw:
        raise HTTPException(status_code=422, detail="subscriber is required")

    if ":" in raw:
        kind, ident_raw = raw.split(":", 1)
        if kind not in {"whatsapp", "telegram"}:
            raise HTTPException(status_code=422, detail="Subscriber reference must start with whatsapp: or telegram:")
        if channel and channel != kind:
            raise HTTPException(status_code=422, detail=f"channel is {channel}, but subscriber reference belongs to {kind}")
        try:
            ident = int(ident_raw)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid subscriber reference") from exc
        if kind == "telegram":
            workspace_ids = _telegram_workspace_ids(db)
            row = db.scalar(select(TelegramContact).where(TelegramContact.id == ident, TelegramContact.workspace_id.in_(workspace_ids))) if workspace_ids else None
        else:
            row = db.scalar(select(Contact).where(Contact.id == ident, Contact.workspace_id == ctx.workspace_id))
        if not row:
            raise HTTPException(status_code=404, detail="Subscriber not found")
        return kind, row

    if channel is None:
        raise HTTPException(status_code=422, detail="channel is required when subscriber is not a canonical whatsapp:<id> or telegram:<id> reference")

    try:
        numeric = int(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="subscriber must be a numeric ID or canonical channel:id reference") from exc

    if channel == "telegram":
        workspace_ids = _telegram_workspace_ids(db)
        if not workspace_ids:
            raise HTTPException(status_code=404, detail="Subscriber not found")
        row = db.scalar(select(TelegramContact).where(TelegramContact.id == numeric, TelegramContact.workspace_id.in_(workspace_ids)))
        if not row:
            row = db.scalar(select(TelegramContact).where(TelegramContact.telegram_user_id == numeric, TelegramContact.workspace_id.in_(workspace_ids)))
    else:
        row = db.scalar(select(Contact).where(Contact.id == numeric, Contact.workspace_id == ctx.workspace_id))
        if not row:
            wa_id = "".join(ch for ch in raw if ch.isdigit())
            row = db.scalar(select(Contact).where(Contact.wa_id == wa_id, Contact.workspace_id == ctx.workspace_id))

    if not row:
        raise HTTPException(status_code=404, detail="Subscriber not found")
    return channel, row


def _ensure_shared_fields(db: Session, ctx: DeveloperApiContext, target_workspace_id: int, keys) -> None:
    """Lazily mirror shared field definitions into the subscriber workspace."""
    wanted = {str(key).strip() for key in keys if str(key).strip()}
    if not wanted:
        return
    existing = {
        str(key)
        for key in db.scalars(
            select(ContactFieldDefinition.key).where(
                ContactFieldDefinition.workspace_id == target_workspace_id,
                ContactFieldDefinition.key.in_(wanted),
                ContactFieldDefinition.active.is_(True),
            )
        ).all()
    }
    missing = wanted - existing
    if not missing:
        return

    source_workspace_ids = [int(ctx.workspace_id)] + sorted(_telegram_workspace_ids(db) - {int(ctx.workspace_id)})
    for key in sorted(missing):
        source = None
        for workspace_id in source_workspace_ids:
            source = db.scalar(
                select(ContactFieldDefinition).where(
                    ContactFieldDefinition.workspace_id == workspace_id,
                    ContactFieldDefinition.key == key,
                    ContactFieldDefinition.active.is_(True),
                )
            )
            if source:
                break
        if not source:
            continue
        db.add(ContactFieldDefinition(
            workspace_id=target_workspace_id,
            key=source.key,
            label=source.label,
            field_type=source.field_type,
            options_json=source.options_json,
            required=source.required,
            active=True,
            sort_order=source.sort_order,
        ))
    db.flush()


def _write_fields(request: Request, payload: BodySubscriberFields, db: Session, ctx: DeveloperApiContext):
    started = time.perf_counter()
    channel, subscriber = _resolve_body_subscriber(db, ctx, payload.channel, payload.subscriber)
    _ensure_shared_fields(db, ctx, subscriber.workspace_id, payload.fields.keys())
    out = _set_fields(db, subscriber.workspace_id, subscriber.id, channel, payload.fields)
    db.commit()
    _log(db, ctx, request, started, channel=channel)
    return {"subscriber": f"{channel}:{subscriber.id}", "channel": channel, "fields": out}


@router.post("/subscribers/fields")
def post_subscriber_fields(request: Request, payload: BodySubscriberFields, db: Session = Depends(get_db), ctx: DeveloperApiContext = Depends(require_scope("fields:write"))):
    return _write_fields(request, payload, db, ctx)


@router.patch("/subscribers/fields")
def patch_subscriber_fields(request: Request, payload: BodySubscriberFields, db: Session = Depends(get_db), ctx: DeveloperApiContext = Depends(require_scope("fields:write"))):
    return _write_fields(request, payload, db, ctx)


def _tag_names(db: Session, ctx: DeveloperApiContext, target_workspace_id: int, payload: BodySubscriberTags) -> list[str]:
    """Resolve tag names from names or IDs and keep channel workspaces isolated."""
    names: list[str] = []
    values: list[str | int] = list(payload.tags)
    if payload.tag_id is not None:
        values.append(payload.tag_id)
    if payload.name and payload.name.strip():
        values.append(payload.name.strip())
    if not values:
        raise HTTPException(status_code=422, detail="Provide at least one tag in tags, tag_id, or name")

    visible_workspace_ids = {int(ctx.workspace_id), int(target_workspace_id)} | _telegram_workspace_ids(db)
    for value in values:
        if isinstance(value, int):
            tag = db.scalar(select(ContactTag).where(ContactTag.id == value, ContactTag.workspace_id.in_(visible_workspace_ids)))
            if not tag:
                raise HTTPException(status_code=404, detail=f"Tag {value} not found")
            name = tag.name
        else:
            name = str(value).strip()
            if not name:
                continue
        if name.lower() not in {item.lower() for item in names}:
            names.append(name)
    if not names:
        raise HTTPException(status_code=422, detail="Provide at least one non-empty tag")
    return names


def _write_tags(request: Request, payload: BodySubscriberTags, db: Session, ctx: DeveloperApiContext):
    started = time.perf_counter()
    channel, subscriber = _resolve_body_subscriber(db, ctx, payload.channel, payload.subscriber)
    names = _tag_names(db, ctx, subscriber.workspace_id, payload)
    for name in names:
        _assign_tag(db, subscriber.workspace_id, subscriber.id, channel, name=name)
    db.commit()
    out = _tag_rows(db, subscriber.workspace_id, subscriber.id, channel)
    _log(db, ctx, request, started, channel=channel)
    return {"subscriber": f"{channel}:{subscriber.id}", "channel": channel, "tags": out}


def _delete_tags(request: Request, payload: BodySubscriberTags, db: Session, ctx: DeveloperApiContext):
    started = time.perf_counter()
    channel, subscriber = _resolve_body_subscriber(db, ctx, payload.channel, payload.subscriber)
    names = _tag_names(db, ctx, subscriber.workspace_id, payload)
    for name in names:
        tag = db.scalar(select(ContactTag).where(ContactTag.workspace_id == subscriber.workspace_id, ContactTag.name.ilike(name)))
        if tag:
            _remove_tag(db, subscriber.id, channel, tag.id)
    db.commit()
    out = _tag_rows(db, subscriber.workspace_id, subscriber.id, channel)
    _log(db, ctx, request, started, channel=channel)
    return {"subscriber": f"{channel}:{subscriber.id}", "channel": channel, "tags": out}


@router.post("/subscribers/tags")
def post_subscriber_tags(request: Request, payload: BodySubscriberTags, db: Session = Depends(get_db), ctx: DeveloperApiContext = Depends(require_scope("tags:write"))):
    return _write_tags(request, payload, db, ctx)


@router.patch("/subscribers/tags")
def patch_subscriber_tags(request: Request, payload: BodySubscriberTags, db: Session = Depends(get_db), ctx: DeveloperApiContext = Depends(require_scope("tags:write"))):
    return _write_tags(request, payload, db, ctx)


@router.delete("/subscribers/tags")
def delete_subscriber_tags(request: Request, payload: BodySubscriberTags, db: Session = Depends(get_db), ctx: DeveloperApiContext = Depends(require_scope("tags:write"))):
    return _delete_tags(request, payload, db, ctx)


@router.post("/subscribers/tags/remove")
def post_remove_subscriber_tags(request: Request, payload: BodySubscriberTags, db: Session = Depends(get_db), ctx: DeveloperApiContext = Depends(require_scope("tags:write"))):
    return _delete_tags(request, payload, db, ctx)


def _write_conversation(request: Request, payload: BodySubscriberConversation, db: Session, ctx: DeveloperApiContext):
    started = time.perf_counter()
    channel, subscriber = _resolve_body_subscriber(db, ctx, payload.channel, payload.subscriber)
    model = TelegramConversation if channel == "telegram" else Conversation
    conversation = db.scalar(
        select(model)
        .where(model.workspace_id == subscriber.workspace_id, model.contact_id == subscriber.id)
        .order_by(model.last_message_at.desc(), model.id.desc())
        .limit(1)
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Subscriber has no conversation")

    if payload.status is not None:
        conversation.status = payload.status if channel == "telegram" else ConversationStatus(payload.status)
    if "assigned_user_id" in payload.model_fields_set:
        if payload.assigned_user_id is not None and not db.scalar(select(User.id).where(User.id == payload.assigned_user_id, User.active.is_(True))):
            raise HTTPException(status_code=422, detail="Assigned user not found or inactive")
        conversation.assigned_user_id = payload.assigned_user_id

    db.commit()
    out = _conversation_out(db, channel, subscriber.id)
    _log(db, ctx, request, started, channel=channel)
    return {"subscriber": f"{channel}:{subscriber.id}", "channel": channel, "conversation": out}


@router.post("/subscribers/conversation")
def post_subscriber_conversation(request: Request, payload: BodySubscriberConversation, db: Session = Depends(get_db), ctx: DeveloperApiContext = Depends(require_scope("conversations:write"))):
    return _write_conversation(request, payload, db, ctx)


@router.patch("/subscribers/conversation")
def patch_subscriber_conversation(request: Request, payload: BodySubscriberConversation, db: Session = Depends(get_db), ctx: DeveloperApiContext = Depends(require_scope("conversations:write"))):
    return _write_conversation(request, payload, db, ctx)
