"""Telegram-native Question flow extensions.

Adds Telegram contact sharing, stable media-answer capture and live-chat snapshots
of interactive choices without duplicating the core Telegram flow runtime.
"""
import json
import re
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
_original_interactive = runtime._interactive

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
        runtime._store(db, conversation, result, "phone_request", result.get("text") or prompt)
        return
    await _original_send(db, conversation, text)


def _message_from_payload(inbound):
    try:
        payload = json.loads(inbound.payload_json or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload.get("message") or {}


def _media_value(inbound):
    """Return portable Telegram media metadata for a Question answer."""
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


def _validation_error(config, fallback):
    return str(config.get("validation_error") or "").strip() or fallback


def _validate_text_value(config, reply_type, value):
    """Validate typed Question answers consistently with the WhatsApp runtime."""
    error = lambda fallback: _validation_error(config, fallback)
    required = config.get("required", True) is not False

    if not value:
        if required:
            return False, None, error("Please enter a reply.")
        return True, "", None

    if reply_type == "email":
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            return False, None, error("Please enter a valid email address.")

    if reply_type in {"phone", "telephone"}:
        normalised = re.sub(r"[\s().-]", "", value)
        if not re.fullmatch(r"\+?\d{7,15}", normalised):
            return False, None, error("Please enter a valid phone number.")

    if reply_type in {"number", "integer", "decimal"}:
        try:
            number = float(value.replace(",", "."))
        except ValueError:
            return False, None, error("Please enter a valid number.")
        if reply_type == "integer" and not number.is_integer():
            return False, None, error("Please enter a whole number.")
        minimum, maximum = config.get("min_value"), config.get("max_value")
        if minimum not in (None, "") and number < float(minimum):
            return False, None, error(f"Please enter a value of at least {minimum}.")
        if maximum not in (None, "") and number > float(maximum):
            return False, None, error(f"Please enter a value no greater than {maximum}.")
        value = str(int(number)) if reply_type == "integer" else str(number)

    if reply_type == "date":
        date_format = str(config.get("date_format") or "%Y-%m-%d")
        try:
            datetime.strptime(value, date_format)
        except ValueError:
            hint = "YYYY-MM-DD" if date_format == "%Y-%m-%d" else date_format
            return False, None, error(f"Please enter a valid date in {hint} format.")

    if reply_type in {"text", "email", "phone", "telephone"}:
        minimum, maximum = config.get("min_length"), config.get("max_length")
        if minimum not in (None, "") and len(value) < int(minimum):
            return False, None, error(f"Please enter at least {minimum} characters.")
        if maximum not in (None, "") and len(value) > int(maximum):
            return False, None, error(f"Please enter no more than {maximum} characters.")

    pattern = str(config.get("pattern") or "").strip()
    if pattern and reply_type in {"text", "email", "phone", "telephone"}:
        try:
            if not re.fullmatch(pattern, value):
                return False, None, error("That reply is not in the expected format.")
        except re.error:
            runtime.logger.warning("Invalid validation regex on Telegram flow question: %s", pattern)

    return True, value, None


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

    if reply_type == "media":
        if actual not in _MEDIA_TYPES:
            return False, None, error or "Please send a photo, video, audio/voice note, document or sticker."
        return True, _media_value(inbound), None

    media_expected = {
        "image": ({"photo"}, "Please send a photo or image."),
        "photo": ({"photo"}, "Please send a photo or image."),
        "audio": ({"audio", "voice"}, "Please send an audio file or voice note."),
        "voice": ({"audio", "voice"}, "Please send an audio file or voice note."),
        "video": ({"video"}, "Please send a video."),
        "document": ({"document"}, "Please send a document or file."),
        "file": ({"document"}, "Please send a document or file."),
        "sticker": ({"sticker"}, "Please send a sticker."),
    }
    if reply_type in media_expected:
        accepted, fallback = media_expected[reply_type]
        if actual not in accepted:
            return False, None, error or fallback
        captured_url = getattr(inbound, "_captured_image_url", None)
        if actual == "photo" and captured_url:
            return True, captured_url, None
        return True, _media_value(inbound), None

    if actual != "text":
        return False, None, error or "Please reply with text."

    return _validate_text_value(config, reply_type, str(inbound.body or "").strip())


def _matching_flows(db, conversation, inbound):
    """Match active Telegram flows across connected Telegram bot workspaces."""
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


def _interactive_choices(db, conversation, node, by, out, config):
    """Build the exact labels presented by an Interactive Message at send time."""
    list_nodes = runtime._choices(by, out, node.id, "list_messages")
    button_nodes = runtime._choices(by, out, node.id, "buttons")
    labels = []
    if str(config.get("row_generation") or "static").lower() == "dynamic":
        rows = runtime.build_dynamic_rows(db, "telegram", conversation.workspace_id, conversation.contact_id, config, 10)
        labels = [str(row.get("label") or "Option").strip() for row in rows]
    elif list_nodes:
        template = next((x for x in list_nodes if str(runtime._json(x.config_json).get("row_generation") or "static").lower() == "dynamic"), None)
        if template:
            tc = runtime._json(template.config_json)
            rows = runtime.build_dynamic_rows(db, "telegram", conversation.workspace_id, conversation.contact_id, tc, 10)
            labels = [str(row.get("label") or "Option").strip() for row in rows]
        else:
            for item in list_nodes[:10]:
                cfg = runtime._json(item.config_json)
                labels.append(runtime._render(db, conversation, cfg.get("label") or item.title or "Option").strip())
    else:
        for item in button_nodes:
            cfg = runtime._json(item.config_json)
            labels.append(runtime._render(db, conversation, cfg.get("label") or item.title or "Option").strip())
    return [label for label in labels if label]


async def _interactive(db, conversation, node, by, out, config):
    """Run the core sender, then snapshot the actual choices into chat history."""
    labels = _interactive_choices(db, conversation, node, by, out, config)
    result = await _original_interactive(db, conversation, node, by, out, config)
    if labels:
        message = db.scalars(
            runtime.select(runtime.TelegramMessage)
            .where(
                runtime.TelegramMessage.conversation_id == conversation.id,
                runtime.TelegramMessage.direction == "outbound",
                runtime.TelegramMessage.message_type == "interactive",
            )
            .order_by(runtime.TelegramMessage.id.desc())
            .limit(1)
        ).first()
        if message:
            prompt = str(message.body or runtime._render(db, conversation, config.get("text") or "Choose an option")).strip()
            message.body = prompt + "\n\nOptions shown:\n" + "\n".join(f"• {label}" for label in labels)
            db.flush()
    return result


async def run_telegram_flows_for_inbound(db, conversation, inbound):
    """Resume a valid waiting interaction before considering keyword restarts.

    A Question owns the next inbound message while it is waiting for a reply. This is
    essential for validation: wrong input must be rejected by that Question instead of
    being diverted into trigger matching. Keyword restart remains available only when
    the saved waiting session is stale or no longer points at the expected node type.
    """
    session = runtime._session(db, conversation.id)
    message_type = str(getattr(inbound, "message_type", "") or "").strip().lower()

    if session and session.status == "waiting":
        flow = db.get(runtime.Flow, session.flow_id)
        waiting_node = None
        if flow and session.current_node_id:
            waiting_node = db.get(runtime.FlowNode, session.current_node_id)

        valid_wait = (
            session.waiting_for == "reply"
            and waiting_node
            and runtime._is(waiting_node, runtime.FlowNodeType.QUESTION)
        ) or (
            session.waiting_for == "button"
            and waiting_node
            and runtime._is(waiting_node, runtime.FlowNodeType.INTERACTIVE)
        ) or (
            session.waiting_for == "location"
            and waiting_node
            and runtime._is(waiting_node, runtime.FlowNodeType.REQUEST_LOCATION)
        ) or session.waiting_for == "delay"

        if valid_wait:
            return await _original_run_inbound(db, conversation, inbound)

        if message_type == "text":
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

    return await _original_run_inbound(db, conversation, inbound)


def install():
    if getattr(runtime, "_telegram_phone_flow_installed", False):
        return
    runtime._json = _json
    runtime._send = _send
    runtime._validate = _validate
    runtime._matching_flows = _matching_flows
    runtime._interactive = _interactive
    runtime._telegram_phone_flow_installed = True


install()
