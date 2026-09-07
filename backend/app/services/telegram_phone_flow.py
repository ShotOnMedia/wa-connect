"""Telegram-native Question flow extensions.

Adds Telegram contact sharing and stable media-answer capture without duplicating
the core Telegram flow runtime.
"""
import json
from contextvars import ContextVar
from datetime import datetime

from app.services import telegram_flow_runtime as runtime
from app.services.telegram import request_phone_number

_current_config: ContextVar[dict] = ContextVar("telegram_flow_config", default={})
_original_json = runtime._json
_original_send = runtime._send
_original_validate = runtime._validate
_original_matching_flows = runtime._matching_flows
_original_run_inbound = runtime.run_telegram_flows_for_inbound

_MEDIA_TYPES = {"photo", "video", "voice", "audio", "document", "sticker"}


def _json(value):
    config = _original_json(value)
    _current_config.set(config if isinstance(config, dict) else {})
    return config


async def _send(db, conversation, text):
    config = _current_config.get({})
    if str(config.get("reply_type") or "").strip().lower() == "telegram_phone":
        prompt = runtime._render(db, conversation, text).strip() or "Please share your phone number."
        button = str(config.get("telegram_phone_button_text") or "Share phone number").strip() or "Share phone number"
        result = await request_phone_number(conversation.bot.access_token, conversation.chat_id, prompt, button)
        runtime._store_outbound(db, conversation, result, "phone_request", result.get("text") or prompt)
        return
    await _original_send(db, conversation, text)


def _message_from_payload(inbound):
    try:
        payload = json.loads(inbound.payload_json or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload.get("message") or {}


def _media_value(inbound):
    """Return portable Telegram media metadata for a Question answer.

    We deliberately store Telegram's stable file_id/file_unique_id plus the local
    WA Connect message id. The bot token/file URL is never persisted in a custom
    field because Telegram download URLs are temporary and contain credentials.
    """
    kind = str(inbound.message_type or "").strip().lower()
    message = _message_from_payload(inbound)
    media = None
    if kind == "photo":
        photos = message.get("photo") or []
        media = photos[-1] if photos else {}
    else:
        media = message.get(kind) or {}
    if not isinstance(media, dict):
        media = {}
    value = {
        "channel": "telegram",
        "type": kind,
        "message_id": inbound.id,
        "telegram_message_id": inbound.telegram_message_id,
        "file_id": media.get("file_id"),
        "file_unique_id": media.get("file_unique_id"),
    }
    if media.get("file_name"):
        value["file_name"] = media.get("file_name")
    if media.get("mime_type"):
        value["mime_type"] = media.get("mime_type")
    if media.get("file_size") is not None:
        value["file_size"] = media.get("file_size")
    if message.get("caption"):
        value["caption"] = message.get("caption")
    if kind == "sticker" and media.get("emoji"):
        value["emoji"] = media.get("emoji")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _validate(config, inbound):
    reply_type = str(config.get("reply_type") or config.get("input_type") or "text").strip().lower()
    actual = str(inbound.message_type or "").strip().lower()
    error = str(config.get("validation_error") or "").strip()

    if reply_type == "telegram_phone":
        if actual != "contact":
            return False, None, error or "Please use the Share phone number button."
        value = str(inbound.body or "").strip()
        if not value:
            return False, None, error or "Telegram did not provide a phone number. Please try again."
        return True, value, None

    # "Any media" accepts all Telegram media types. Specific media reply types
    # retain the core validator's rules (including audio <-> voice compatibility).
    if reply_type == "media":
        if actual not in _MEDIA_TYPES:
            return False, None, error or "Please reply with a photo, video, audio, document or sticker."
        return True, _media_value(inbound), None

    result = _original_validate(config, inbound)
    if result[0] and actual in _MEDIA_TYPES:
        return True, _media_value(inbound), None
    return result


def _matching_flows(db, conversation, inbound):
    """Match active Telegram flows across connected Telegram bot workspaces.

    FlowChannelTarget is currently the authoritative channel discriminator. The
    visual builder can create a Telegram flow in one bot workspace while an inbound
    conversation belongs to another connected Telegram bot workspace, so an exact
    workspace-only lookup can otherwise miss a valid keyword flow.
    """
    matches = _original_matching_flows(db, conversation, inbound)
    if matches:
        return matches

    flows = db.scalars(
        runtime.select(runtime.Flow)
        .join(runtime.FlowChannelTarget, runtime.FlowChannelTarget.flow_id == runtime.Flow.id)
        .where(
            runtime.Flow.status == runtime.FlowStatus.ACTIVE,
            runtime.FlowChannelTarget.channel == "telegram",
        )
        .order_by(runtime.Flow.id)
    ).all()
    count = db.scalar(
        runtime.select(runtime.func.count(runtime.TelegramMessage.id)).where(
            runtime.TelegramMessage.conversation_id == conversation.id,
            runtime.TelegramMessage.direction == "inbound",
        )
    ) or 0
    matches = [
        flow for flow in flows
        if (
            runtime._enum(flow.trigger_type) == runtime.FlowTriggerType.KEYWORD.value
            and runtime._keyword(flow.trigger_value, inbound.body)
        ) or (
            runtime._enum(flow.trigger_type) == runtime.FlowTriggerType.FIRST_MESSAGE.value
            and count == 1
        )
    ]
    if matches:
        runtime.logger.info(
            "Telegram flow workspace fallback matched flow_ids=%s conversation=%s workspace=%s",
            [flow.id for flow in matches],
            conversation.id,
            conversation.workspace_id,
        )
    return matches


async def run_telegram_flows_for_inbound(db, conversation, inbound):
    """Give explicit keyword triggers priority over a stale waiting session."""
    session = runtime._session(db, conversation.id)
    message_type = str(getattr(inbound, "message_type", "") or "").strip().lower()

    # Important: call our cross-workspace matcher directly here. Calling
    # runtime._matching_flows made this wrapper dependent on install/monkey-patch
    # timing and could leave a waiting subscriber trapped in the old flow.
    if session and session.status == "waiting" and message_type == "text":
        matches = _matching_flows(db, conversation, inbound)
        if matches:
            runtime.logger.info(
                "Telegram keyword restart matched flow_ids=%s conversation=%s previous_flow=%s waiting_for=%s",
                [flow.id for flow in matches],
                conversation.id,
                session.flow_id,
                session.waiting_for,
            )
            session.status = "reset"
            session.current_node_id = None
            session.waiting_for = None
            session.ended_at = datetime.utcnow()
            session.updated_at = datetime.utcnow()
            db.flush()

    # The original runtime function reads runtime._matching_flows dynamically, so
    # after the waiting session is neutralised it will start the matching flow.
    return await _original_run_inbound(db, conversation, inbound)


def install():
    if getattr(runtime, "_telegram_phone_flow_installed", False):
        return
    runtime._json = _json
    runtime._send = _send
    runtime._validate = _validate
    runtime._matching_flows = _matching_flows
    runtime._telegram_phone_flow_installed = True


install()
