"""Telegram-native phone sharing support for Question flow blocks.

This module applies a small runtime extension without duplicating the core flow
engine. Import it before processing Telegram flow updates.
"""
from contextvars import ContextVar

from app.services import telegram_flow_runtime as runtime
from app.services.telegram import request_phone_number

_current_config: ContextVar[dict] = ContextVar("telegram_flow_config", default={})
_original_json = runtime._json
_original_send = runtime._send
_original_validate = runtime._validate


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


def _validate(config, inbound):
    reply_type = str(config.get("reply_type") or config.get("input_type") or "text").strip().lower()
    if reply_type == "telegram_phone":
        if str(inbound.message_type or "").strip().lower() != "contact":
            return False, None, str(config.get("validation_error") or "").strip() or "Please use the Share phone number button."
        value = str(inbound.body or "").strip()
        if not value:
            return False, None, str(config.get("validation_error") or "").strip() or "Telegram did not provide a phone number. Please try again."
        return True, value, None
    return _original_validate(config, inbound)


def install():
    if getattr(runtime, "_telegram_phone_flow_installed", False):
        return
    runtime._json = _json
    runtime._send = _send
    runtime._validate = _validate
    runtime._telegram_phone_flow_installed = True


install()
run_telegram_flows_for_inbound = runtime.run_telegram_flows_for_inbound
