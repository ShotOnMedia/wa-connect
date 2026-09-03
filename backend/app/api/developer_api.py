import json
import time
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_admin
from app.developer_api_models import DeveloperApiKey, DeveloperApiRequestLog
from app.flow_channel_models import FlowChannelTarget
from app.flow_models import Flow, FlowStatus
from app.models import (
    Contact,
    ContactFieldDefinition,
    ContactFieldValue,
    ContactTag,
    ContactTagLink,
    Conversation,
    ConversationStatus,
    User,
    WhatsAppPhoneNumber,
    Workspace,
)
from app.services.developer_api import ALL_SCOPES, DEFAULT_SCOPES, DeveloperApiContext, generate_api_key, log_request, require_scope
from app.services.external_flow_trigger import trigger_telegram_flow, trigger_whatsapp_flow
from app.telegram_models import (
    TelegramBot,
    TelegramContact,
    TelegramContactFieldValue,
    TelegramContactTagLink,
    TelegramConversation,
)

admin_router = APIRouter(prefix="/developer-api", tags=["Developer API"], dependencies=[Depends(require_admin)])
external_router = APIRouter(tags=["Developer API v1"])


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    workspace_id: int | None = None
    scopes: list[str] = Field(default_factory=lambda: list(DEFAULT_SCOPES))


class SubscriberCreate(BaseModel):
    channel: Literal["whatsapp", "telegram"] = "whatsapp"
    subscriber_id: str
    name: str | None = None
    connection_id: int | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class SubscriberUpdate(BaseModel):
    name: str | None = None
    fields: dict[str, Any] | None = None


class FieldsUpdate(BaseModel):
    fields: dict[str, Any]


class TagAssign(BaseModel):
    tag_id: int | None = None
    name: str | None = None


class ConversationUpdate(BaseModel):
    status: Literal["open", "pending", "resolved"] | None = None
    assigned_user_id: int | None = None


class FlowTriggerRequest(BaseModel):
    subscriber: str
    channel: Literal["whatsapp", "telegram"] | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    restart: bool = True
    connection_id: int | None = None


def _scope_list(raw: str) -> list[str]:
    try:
        return [str(v) for v in json.loads(raw or "[]")]
    except (TypeError, json.JSONDecodeError):
        return []


def _key_out(row: DeveloperApiKey) -> dict:
    return {"id": row.id, "workspace_id": row.workspace_id, "name": row.name, "prefix": row.key_prefix, "scopes": _scope_list(row.scopes_json), "active": row.active, "last_used_at": row.last_used_at, "expires_at": row.expires_at, "revoked_at": row.revoked_at, "created_at": row.created_at}


@admin_router.get("/workspaces")
def developer_workspaces(db: Session = Depends(get_db)):
    return [{"id": w.id, "name": w.name, "slug": w.slug, "active": w.active} for w in db.scalars(select(Workspace).order_by(Workspace.name)).all()]


@admin_router.get("/scopes")
def developer_scopes(): return sorted(ALL_SCOPES)


@admin_router.get("/keys")
def list_api_keys(db: Session = Depends(get_db)): return [_key_out(row) for row in db.scalars(select(DeveloperApiKey).order_by(DeveloperApiKey.created_at.desc())).all()]


@admin_router.post("/keys", status_code=status.HTTP_201_CREATED)
def create_api_key(payload: ApiKeyCreate, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    workspace_id = payload.workspace_id or db.scalar(select(Workspace.id).where(Workspace.active.is_(True)).order_by(Workspace.id).limit(1))
    if not workspace_id or not db.get(Workspace, workspace_id): raise HTTPException(status_code=400, detail="Create a workspace before generating an API key")
    scopes = sorted({s for s in payload.scopes if s in ALL_SCOPES})
    if not scopes: raise HTTPException(status_code=422, detail="Select at least one API scope")
    token, prefix, token_hash = generate_api_key(); row = DeveloperApiKey(workspace_id=workspace_id, name=payload.name.strip(), key_prefix=prefix, token_hash=token_hash, scopes_json=json.dumps(scopes), created_by_user_id=user.id)
    db.add(row); db.commit(); db.refresh(row); return {**_key_out(row), "token": token}


@admin_router.delete("/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_api_key(key_id: int, db: Session = Depends(get_db)):
    row = db.get(DeveloperApiKey, key_id)
    if not row: raise HTTPException(status_code=404, detail="API key not found")
    row.active = False; row.revoked_at = datetime.utcnow(); db.commit()


@admin_router.get("/logs")
def api_logs(limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)):
    rows = db.scalars(select(DeveloperApiRequestLog).order_by(DeveloperApiRequestLog.created_at.desc()).limit(limit)).all()
    return [{"id": r.id, "workspace_id": r.workspace_id, "api_key_id": r.api_key_id, "method": r.method, "path": r.path, "status_code": r.status_code, "duration_ms": r.duration_ms, "channel": r.channel, "remote_addr": r.remote_addr, "error_message": r.error_message, "created_at": r.created_at} for r in rows]


def _parse_ref(ref: str, channel: str | None = None) -> tuple[str, int]:
    raw = str(ref).strip()
    if ":" in raw:
        prefix, ident = raw.split(":", 1)
        if prefix not in {"whatsapp", "telegram"}: raise HTTPException(status_code=422, detail="Subscriber reference must start with whatsapp: or telegram:")
        try: return prefix, int(ident)
        except ValueError as exc: raise HTTPException(status_code=422, detail="Invalid subscriber reference") from exc
    try: return (channel or "whatsapp"), int(raw)
    except ValueError as exc: raise HTTPException(status_code=422, detail="Invalid subscriber reference") from exc


def _field_rows(db: Session, workspace_id: int, contact_id: int, channel: str) -> dict[str, str | None]:
    value_model = TelegramContactFieldValue if channel == "telegram" else ContactFieldValue
    rows = db.execute(select(ContactFieldDefinition.key, value_model.value_text).outerjoin(value_model, (value_model.field_id == ContactFieldDefinition.id) & (value_model.contact_id == contact_id)).where(ContactFieldDefinition.workspace_id == workspace_id, ContactFieldDefinition.active.is_(True)).order_by(ContactFieldDefinition.sort_order, ContactFieldDefinition.id)).all()
    return {str(key): value for key, value in rows}


def _tag_rows(db: Session, workspace_id: int, contact_id: int, channel: str) -> list[dict]:
    link_model = TelegramContactTagLink if channel == "telegram" else ContactTagLink
    rows = db.scalars(select(ContactTag).join(link_model, link_model.tag_id == ContactTag.id).where(link_model.contact_id == contact_id, ContactTag.workspace_id == workspace_id).order_by(ContactTag.name)).all()
    return [{"id": t.id, "name": t.name} for t in rows]


def _conversation_out(db: Session, channel: str, contact_id: int) -> dict | None:
    if channel == "telegram":
        row = db.scalar(select(TelegramConversation).where(TelegramConversation.contact_id == contact_id).order_by(TelegramConversation.last_message_at.desc(), TelegramConversation.id.desc()).limit(1)); return None if not row else {"id": row.id, "status": row.status, "assigned_user_id": row.assigned_user_id, "last_message_at": row.last_message_at}
    row = db.scalar(select(Conversation).where(Conversation.contact_id == contact_id).order_by(Conversation.last_message_at.desc(), Conversation.id.desc()).limit(1)); return None if not row else {"id": row.id, "status": row.status.value, "assigned_user_id": row.assigned_user_id, "last_message_at": row.last_message_at}


def _subscriber_out(db: Session, channel: str, row) -> dict:
    if channel == "telegram": name = " ".join(p for p in [row.first_name, row.last_name] if p).strip() or row.username; subscriber_id = str(row.telegram_user_id); username = row.username
    else: name = row.name; subscriber_id = row.wa_id; username = None
    return {"id": f"{channel}:{row.id}", "channel": channel, "subscriber_id": subscriber_id, "name": name, "username": username, "fields": _field_rows(db, row.workspace_id, row.id, channel), "tags": _tag_rows(db, row.workspace_id, row.id, channel), "conversation": _conversation_out(db, channel, row.id), "created_at": row.created_at, "updated_at": row.updated_at}


def _subscriber(db: Session, ctx: DeveloperApiContext, ref: str, channel: str | None = None):
    kind, ident = _parse_ref(ref, channel); model = TelegramContact if kind == "telegram" else Contact; row = db.scalar(select(model).where(model.id == ident, model.workspace_id == ctx.workspace_id))
    if not row: raise HTTPException(status_code=404, detail="Subscriber not found")
    return kind, row


def _subscriber_by_external_id(db: Session, ctx: DeveloperApiContext, channel: str, subscriber_id: str):
    raw = str(subscriber_id).strip()
    if ":" in raw:
        kind, ident = _parse_ref(raw)
        if kind != channel:
            raise HTTPException(status_code=422, detail=f"Flow belongs to {channel}, but subscriber reference belongs to {kind}")
        model = TelegramContact if channel == "telegram" else Contact
        return db.scalar(select(model).where(model.workspace_id == ctx.workspace_id, model.id == ident))
    if channel == "telegram":
        try: value = int(raw)
        except ValueError as exc: raise HTTPException(status_code=422, detail="Telegram subscriber must be a telegram:<id> reference or numeric Telegram user ID") from exc
        return db.scalar(select(TelegramContact).where(TelegramContact.workspace_id == ctx.workspace_id, TelegramContact.telegram_user_id == value))
    normalized = "".join(ch for ch in raw if ch.isdigit())
    return db.scalar(select(Contact).where(Contact.workspace_id == ctx.workspace_id, Contact.wa_id == normalized))


def _set_fields(db: Session, workspace_id: int, contact_id: int, channel: str, values: dict[str, Any]) -> dict[str, str | None]:
    value_model = TelegramContactFieldValue if channel == "telegram" else ContactFieldValue; definitions = {f.key: f for f in db.scalars(select(ContactFieldDefinition).where(ContactFieldDefinition.workspace_id == workspace_id, ContactFieldDefinition.active.is_(True))).all()}; unknown = sorted(k for k in values if k not in definitions)
    if unknown: raise HTTPException(status_code=422, detail=f"Unknown custom field key(s): {', '.join(unknown)}")
    for key, value in values.items():
        field = definitions[key]; existing = db.scalar(select(value_model).where(value_model.contact_id == contact_id, value_model.field_id == field.id)); text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else (None if value is None else str(value))
        if existing: existing.value_text = text; existing.updated_at = datetime.utcnow()
        else: db.add(value_model(contact_id=contact_id, field_id=field.id, value_text=text))
    db.flush(); return _field_rows(db, workspace_id, contact_id, channel)


def _assign_tag(db: Session, workspace_id: int, contact_id: int, channel: str, tag_id: int | None = None, name: str | None = None):
    tag = db.get(ContactTag, tag_id) if tag_id else None
    if not tag and name and name.strip():
        tag = db.scalar(select(ContactTag).where(ContactTag.workspace_id == workspace_id, func.lower(ContactTag.name) == name.strip().lower()))
        if not tag: tag = ContactTag(workspace_id=workspace_id, name=name.strip()); db.add(tag); db.flush()
    if not tag or tag.workspace_id != workspace_id: raise HTTPException(status_code=404, detail="Tag not found")
    link_model = TelegramContactTagLink if channel == "telegram" else ContactTagLink; exists = db.scalar(select(link_model.id).where(link_model.contact_id == contact_id, link_model.tag_id == tag.id))
    if not exists: db.add(link_model(contact_id=contact_id, tag_id=tag.id)); db.flush()
    return tag


def _remove_tag(db: Session, contact_id: int, channel: str, tag_id: int):
    link_model = TelegramContactTagLink if channel == "telegram" else ContactTagLink; db.execute(delete(link_model).where(link_model.contact_id == contact_id, link_model.tag_id == tag_id)); db.flush()


def _log(db, ctx, request, started, code=200, channel=None): log_request(db, ctx, request, code, started, channel=channel)


@external_router.get("/subscribers")
def list_subscribers(request: Request, channel: Literal["whatsapp", "telegram"] | None = None, q: str | None = Query(default=None, max_length=200), limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db), ctx: DeveloperApiContext = Depends(require_scope("subscribers:read"))):
    started = time.perf_counter(); result = []
    if channel in (None, "whatsapp"):
        stmt = select(Contact).where(Contact.workspace_id == ctx.workspace_id)
        if q: term = f"%{q.strip()}%"; stmt = stmt.where(or_(Contact.name.ilike(term), Contact.wa_id.ilike(term)))
        for row in db.scalars(stmt.order_by(Contact.updated_at.desc()).limit(limit)).all(): result.append(_subscriber_out(db, "whatsapp", row))
    if channel in (None, "telegram") and len(result) < limit:
        stmt = select(TelegramContact).where(TelegramContact.workspace_id == ctx.workspace_id)
        if q: term = f"%{q.strip()}%"; stmt = stmt.where(or_(TelegramContact.first_name.ilike(term), TelegramContact.last_name.ilike(term), TelegramContact.username.ilike(term)))
        for row in db.scalars(stmt.order_by(TelegramContact.updated_at.desc()).limit(limit - len(result))).all(): result.append(_subscriber_out(db, "telegram", row))
    _log(db, ctx, request, started, channel=channel); return {"data": result, "count": len(result)}


@external_router.post("/subscribers", status_code=status.HTTP_201_CREATED)
def create_subscriber(request: Request, payload: SubscriberCreate, db: Session = Depends(get_db), ctx: DeveloperApiContext = Depends(require_scope("subscribers:write"))):
    started = time.perf_counter()
    if payload.channel == "telegram": raise HTTPException(status_code=422, detail="Telegram subscribers are created when they first interact with a connected bot; update an existing Telegram subscriber instead")
    wa_id = "".join(ch for ch in payload.subscriber_id if ch.isdigit())
    if not wa_id: raise HTTPException(status_code=422, detail="subscriber_id must contain a WhatsApp phone number")
    row = db.scalar(select(Contact).where(Contact.workspace_id == ctx.workspace_id, Contact.wa_id == wa_id))
    if not row: row = Contact(workspace_id=ctx.workspace_id, wa_id=wa_id, name=(payload.name or "").strip() or None); db.add(row); db.flush()
    elif payload.name is not None: row.name = payload.name.strip() or None
    if payload.fields: _set_fields(db, ctx.workspace_id, row.id, "whatsapp", payload.fields)
    for tag_name in payload.tags: _assign_tag(db, ctx.workspace_id, row.id, "whatsapp", name=tag_name)
    phone = None
    if payload.connection_id:
        phone = db.scalar(select(WhatsAppPhoneNumber).join(WhatsAppPhoneNumber.account).where(WhatsAppPhoneNumber.id == payload.connection_id, WhatsAppPhoneNumber.active.is_(True)))
        if phone and phone.account.workspace_id != ctx.workspace_id: phone = None
    if not phone: phone = db.scalar(select(WhatsAppPhoneNumber).join(WhatsAppPhoneNumber.account).where(WhatsAppPhoneNumber.active.is_(True), WhatsAppPhoneNumber.account.has(workspace_id=ctx.workspace_id)).order_by(WhatsAppPhoneNumber.id).limit(1))
    if phone and not db.scalar(select(Conversation.id).where(Conversation.contact_id == row.id, Conversation.phone_number_id == phone.id)): db.add(Conversation(workspace_id=ctx.workspace_id, phone_number_id=phone.id, contact_id=row.id))
    db.commit(); db.refresh(row); result = _subscriber_out(db, "whatsapp", row); _log(db, ctx, request, started, 201, "whatsapp"); return result


@external_router.get("/subscribers/{subscriber_ref}")
def get_subscriber(request: Request, subscriber_ref: str, channel: str | None = None, db: Session = Depends(get_db), ctx: DeveloperApiContext = Depends(require_scope("subscribers:read"))):
    started = time.perf_counter(); kind, row = _subscriber(db, ctx, subscriber_ref, channel); result = _subscriber_out(db, kind, row); _log(db, ctx, request, started, channel=kind); return result


@external_router.patch("/subscribers/{subscriber_ref}")
def update_subscriber(request: Request, subscriber_ref: str, payload: SubscriberUpdate, db: Session = Depends(get_db), ctx: DeveloperApiContext = Depends(require_scope("subscribers:write"))):
    started = time.perf_counter(); kind, row = _subscriber(db, ctx, subscriber_ref)
    if payload.name is not None:
        if kind == "telegram": parts = payload.name.strip().split(" ", 1); row.first_name = parts[0] if parts else None; row.last_name = parts[1] if len(parts) > 1 else None
        else: row.name = payload.name.strip() or None
    if payload.fields is not None: _set_fields(db, ctx.workspace_id, row.id, kind, payload.fields)
    row.updated_at = datetime.utcnow(); db.commit(); result = _subscriber_out(db, kind, row); _log(db, ctx, request, started, channel=kind); return result


@external_router.delete("/subscribers/{subscriber_ref}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subscriber(request: Request, subscriber_ref: str, db: Session = Depends(get_db), ctx: DeveloperApiContext = Depends(require_scope("subscribers:write"))):
    started = time.perf_counter(); kind, row = _subscriber(db, ctx, subscriber_ref)
    if kind == "whatsapp": row.archived_at = datetime.utcnow(); row.updated_at = datetime.utcnow()
    else: db.delete(row)
    db.commit(); _log(db, ctx, request, started, 204, kind)


@external_router.get("/custom-fields")
def list_custom_fields(request: Request, db: Session = Depends(get_db), ctx: DeveloperApiContext = Depends(require_scope("fields:read"))):
    started = time.perf_counter(); rows = db.scalars(select(ContactFieldDefinition).where(ContactFieldDefinition.workspace_id == ctx.workspace_id, ContactFieldDefinition.active.is_(True)).order_by(ContactFieldDefinition.sort_order, ContactFieldDefinition.id)).all(); result = [{"id": f.id, "key": f.key, "label": f.label, "type": f.field_type.value, "required": f.required} for f in rows]; _log(db, ctx, request, started); return {"data": result, "count": len(result)}


@external_router.get("/subscribers/{subscriber_ref}/fields")
def subscriber_fields(request: Request, subscriber_ref: str, db: Session = Depends(get_db), ctx: DeveloperApiContext = Depends(require_scope("fields:read"))):
    started = time.perf_counter(); kind, row = _subscriber(db, ctx, subscriber_ref); result = _field_rows(db, ctx.workspace_id, row.id, kind); _log(db, ctx, request, started, channel=kind); return {"subscriber": f"{kind}:{row.id}", "fields": result}


@external_router.patch("/subscribers/{subscriber_ref}/fields")
def update_subscriber_fields(request: Request, subscriber_ref: str, payload: FieldsUpdate, db: Session = Depends(get_db), ctx: DeveloperApiContext = Depends(require_scope("fields:write"))):
    started = time.perf_counter(); kind, row = _subscriber(db, ctx, subscriber_ref); values = _set_fields(db, ctx.workspace_id, row.id, kind, payload.fields); db.commit(); _log(db, ctx, request, started, channel=kind); return {"subscriber": f"{kind}:{row.id}", "fields": values}


@external_router.get("/tags")
def list_tags(request: Request, db: Session = Depends(get_db), ctx: DeveloperApiContext = Depends(require_scope("tags:read"))):
    started = time.perf_counter(); rows = db.scalars(select(ContactTag).where(ContactTag.workspace_id == ctx.workspace_id).order_by(ContactTag.name)).all(); result = [{"id": t.id, "name": t.name} for t in rows]; _log(db, ctx, request, started); return {"data": result, "count": len(result)}


@external_router.post("/subscribers/{subscriber_ref}/tags")
def add_subscriber_tag(request: Request, subscriber_ref: str, payload: TagAssign, db: Session = Depends(get_db), ctx: DeveloperApiContext = Depends(require_scope("tags:write"))):
    started = time.perf_counter(); kind, row = _subscriber(db, ctx, subscriber_ref); tag = _assign_tag(db, ctx.workspace_id, row.id, kind, payload.tag_id, payload.name); db.commit(); result = {"id": tag.id, "name": tag.name}; _log(db, ctx, request, started, channel=kind); return result


@external_router.delete("/subscribers/{subscriber_ref}/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_subscriber_tag(request: Request, subscriber_ref: str, tag_id: int, db: Session = Depends(get_db), ctx: DeveloperApiContext = Depends(require_scope("tags:write"))):
    started = time.perf_counter(); kind, row = _subscriber(db, ctx, subscriber_ref); _remove_tag(db, row.id, kind, tag_id); db.commit(); _log(db, ctx, request, started, 204, kind)


@external_router.patch("/subscribers/{subscriber_ref}/conversation")
def update_conversation(request: Request, subscriber_ref: str, payload: ConversationUpdate, db: Session = Depends(get_db), ctx: DeveloperApiContext = Depends(require_scope("conversations:write"))):
    started = time.perf_counter(); kind, row = _subscriber(db, ctx, subscriber_ref)
    if kind == "telegram": conversation = db.scalar(select(TelegramConversation).where(TelegramConversation.contact_id == row.id).order_by(TelegramConversation.last_message_at.desc(), TelegramConversation.id.desc()).limit(1))
    else: conversation = db.scalar(select(Conversation).where(Conversation.contact_id == row.id).order_by(Conversation.last_message_at.desc(), Conversation.id.desc()).limit(1))
    if not conversation: raise HTTPException(status_code=404, detail="Subscriber has no conversation")
    if payload.status is not None: conversation.status = payload.status if kind == "telegram" else ConversationStatus(payload.status)
    if "assigned_user_id" in payload.model_fields_set:
        if payload.assigned_user_id is not None and not db.scalar(select(User.id).where(User.id == payload.assigned_user_id, User.active.is_(True))): raise HTTPException(status_code=422, detail="Assigned user not found or inactive")
        conversation.assigned_user_id = payload.assigned_user_id
    db.commit(); result = _conversation_out(db, kind, row.id); _log(db, ctx, request, started, channel=kind); return result


def _flow_channel(db: Session, flow_id: int) -> str: return db.scalar(select(FlowChannelTarget.channel).where(FlowChannelTarget.flow_id == flow_id)) or "whatsapp"


@external_router.get("/bot-flows")
def list_bot_flows(request: Request, channel: Literal["whatsapp", "telegram"] | None = None, db: Session = Depends(get_db), ctx: DeveloperApiContext = Depends(require_scope("flows:read"))):
    started = time.perf_counter(); rows = db.scalars(select(Flow).where(Flow.workspace_id == ctx.workspace_id).order_by(Flow.name)).all(); result = []
    for f in rows:
        fchannel = _flow_channel(db, f.id)
        if channel and fchannel != channel: continue
        result.append({"id": f.id, "name": f.name, "description": f.description, "channel": fchannel, "status": f.status.value, "trigger_type": f.trigger_type.value, "updated_at": f.updated_at})
    _log(db, ctx, request, started, channel=channel); return {"data": result, "count": len(result)}


@external_router.post("/bot-flows/{flow_id}/trigger")
async def trigger_bot_flow(request: Request, flow_id: int, payload: FlowTriggerRequest, db: Session = Depends(get_db), ctx: DeveloperApiContext = Depends(require_scope("flows:trigger"))):
    started = time.perf_counter(); flow = db.scalar(select(Flow).where(Flow.id == flow_id, Flow.workspace_id == ctx.workspace_id))
    if not flow: raise HTTPException(status_code=404, detail="Flow not found")
    if flow.status != FlowStatus.ACTIVE: raise HTTPException(status_code=409, detail="Only active flows can be triggered")
    channel = _flow_channel(db, flow.id)
    if payload.channel and payload.channel != channel: raise HTTPException(status_code=422, detail=f"Flow belongs to {channel}, not {payload.channel}")
    subscriber = _subscriber_by_external_id(db, ctx, channel, payload.subscriber)
    if not subscriber: raise HTTPException(status_code=404, detail=f"{channel.title()} subscriber not found")
    if payload.fields: _set_fields(db, ctx.workspace_id, subscriber.id, channel, payload.fields); db.flush()
    if channel == "telegram":
        conversation = db.scalar(select(TelegramConversation).where(TelegramConversation.contact_id == subscriber.id).order_by(TelegramConversation.last_message_at.desc(), TelegramConversation.id.desc()).limit(1))
        if not conversation: raise HTTPException(status_code=409, detail="Telegram subscriber has no bot conversation to send through")
        try: _, session = await trigger_telegram_flow(db, flow, conversation, payload.restart)
        except RuntimeError as exc: raise HTTPException(status_code=409, detail=str(exc)) from exc
        db.commit(); state = session.status if session else "unknown"; waiting_for = session.waiting_for if session else None
    else:
        conversation = None
        if payload.connection_id: conversation = db.scalar(select(Conversation).where(Conversation.contact_id == subscriber.id, Conversation.phone_number_id == payload.connection_id))
        if not conversation: conversation = db.scalar(select(Conversation).where(Conversation.contact_id == subscriber.id).order_by(Conversation.last_message_at.desc(), Conversation.id.desc()).limit(1))
        if not conversation:
            phone = db.scalar(select(WhatsAppPhoneNumber).join(WhatsAppPhoneNumber.account).where(WhatsAppPhoneNumber.active.is_(True), WhatsAppPhoneNumber.account.has(workspace_id=ctx.workspace_id)).order_by(WhatsAppPhoneNumber.id).limit(1))
            if not phone: raise HTTPException(status_code=409, detail="No active WhatsApp number is connected to this workspace")
            conversation = Conversation(workspace_id=ctx.workspace_id, phone_number_id=phone.id, contact_id=subscriber.id); db.add(conversation); db.flush()
        try: _, session = await trigger_whatsapp_flow(db, flow, conversation, payload.restart)
        except RuntimeError as exc: raise HTTPException(status_code=409, detail=str(exc)) from exc
        db.commit(); state = session.status.value if session else "unknown"; waiting_for = session.waiting_for if session else None
    result = {"ok": True, "flow_id": flow.id, "flow": flow.name, "channel": channel, "subscriber": f"{channel}:{subscriber.id}", "status": state, "waiting_for": waiting_for}; _log(db, ctx, request, started, channel=channel); return result
