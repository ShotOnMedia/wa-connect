"""Telegram-native Question flow extensions.

Adds Telegram contact sharing and stable media-answer capture without duplicating
the core Telegram flow runtime.
"""
import json
from contextvars import ContextVar

from app.services import telegram_flow_runtime as runtime
from app.services.telegram import request_phone_number

_current_config: ContextVar[dict] = ContextVar("telegram_flow_config", default={})
_original_json = runtime._json
_original_send = runtime._send
_original_validate = runtime._validate

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


def install():
    if getattr(runtime, "_telegram_phone_flow_installed", False):
        return
    runtime._json = _json
    runtime._send = _send
    runtime._validate = _validate
    runtime._telegram_phone_flow_installed = True


install()
run_telegram_flows_for_inbound = runtime.run_telegram_flows_for_inbound
