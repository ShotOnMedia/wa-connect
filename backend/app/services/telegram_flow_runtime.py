import json
import logging
import re
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.flow_channel_models import FlowChannelTarget, TelegramFlowSession
from app.flow_models import Flow, FlowEdge, FlowNode, FlowNodeType, FlowStatus, FlowTriggerType
from app.services.telegram import TelegramError, send_text
from app.telegram_models import TelegramConversation, TelegramMessage

logger = logging.getLogger(__name__)


def _json(value: str | dict | None) -> dict:
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}


def _enum_value(value):
    return getattr(value, "value", value)


def _is_node_type(node: FlowNode, expected: FlowNodeType) -> bool:
    return _enum_value(node.node_type) == expected.value


def _keyword_matches(expected: str | None, body: str | None) -> bool:
    return bool(expected and body and expected.strip().casefold() == body.strip().casefold())


def _session_for_conversation(db: Session, conversation_id: int) -> TelegramFlowSession | None:
    return db.scalar(select(TelegramFlowSession).where(TelegramFlowSession.conversation_id == conversation_id))


def _matching_flows(db: Session, conversation: TelegramConversation, inbound: TelegramMessage) -> list[Flow]:
    stmt = (
        select(Flow)
        .join(FlowChannelTarget, FlowChannelTarget.flow_id == Flow.id)
        .where(
            Flow.workspace_id == conversation.workspace_id,
            Flow.status == FlowStatus.ACTIVE,
            FlowChannelTarget.channel == "telegram",
        )
        .order_by(Flow.id)
    )
    flows = db.scalars(stmt).all()
    inbound_count = db.scalar(
        select(func.count(TelegramMessage.id)).where(
            TelegramMessage.conversation_id == conversation.id,
            TelegramMessage.direction == "inbound",
        )
    ) or 0
    matched = [
        flow for flow in flows
        if (_enum_value(flow.trigger_type) == FlowTriggerType.KEYWORD.value and _keyword_matches(flow.trigger_value, inbound.body))
        or (_enum_value(flow.trigger_type) == FlowTriggerType.FIRST_MESSAGE.value and inbound_count == 1)
    ]
    logger.info(
        "Telegram flow match workspace=%s conversation=%s inbound=%r active=%s matched=%s",
        conversation.workspace_id,
        conversation.id,
        inbound.body,
        [flow.id for flow in flows],
        [flow.id for flow in matched],
    )
    return matched


def _graph(db: Session, flow_id: int):
    nodes = db.scalars(select(FlowNode).where(FlowNode.flow_id == flow_id)).all()
    edges = db.scalars(select(FlowEdge).where(FlowEdge.flow_id == flow_id).order_by(FlowEdge.sort_order, FlowEdge.id)).all()
    by_id = {node.id: node for node in nodes}
    outgoing: dict[int, list[FlowEdge]] = {}
    for edge in edges:
        outgoing.setdefault(edge.source_node_id, []).append(edge)
    logger.info(
        "Telegram flow graph flow=%s nodes=%s edges=%s",
        flow_id,
        [(node.id, _enum_value(node.node_type)) for node in nodes],
        [(edge.id, edge.source_node_id, edge.source_handle, edge.target_node_id) for edge in edges],
    )
    return nodes, by_id, outgoing


def _next(by_id: dict, outgoing: dict, node_id: int, handle: str = "next") -> FlowNode | None:
    matches = [edge for edge in outgoing.get(node_id, []) if edge.source_handle == handle]
    return by_id.get(matches[0].target_node_id) if matches else None


async def _send(db: Session, conversation: TelegramConversation, text: str) -> None:
    text = str(text or "").strip()
    if not text:
        logger.warning("Telegram flow attempted to send an empty text conversation=%s", conversation.id)
        return
    result = await send_text(conversation.bot.access_token, conversation.chat_id, text)
    timestamp = datetime.utcfromtimestamp(result["date"]) if result.get("date") else datetime.utcnow()
    db.add(TelegramMessage(
        conversation_id=conversation.id,
        telegram_message_id=int(result["message_id"]),
        direction="outbound",
        message_type="text",
        body=result.get("text") or text,
        payload_json=json.dumps(result, ensure_ascii=False),
        status="sent",
        telegram_timestamp=timestamp,
    ))
    conversation.last_message_at = timestamp
    db.flush()
    logger.info("Telegram flow sent text conversation=%s message=%s", conversation.id, result.get("message_id"))


def _validate_question_reply(config: dict, inbound: TelegramMessage) -> tuple[bool, str | None, str | None]:
    reply_type = str(config.get("reply_type") or config.get("input_type") or "text").strip().lower()
    actual_type = str(inbound.message_type or "text").strip().lower()
    custom_error = str(config.get("validation_error") or "").strip()

    expected_types = {
        "photo": "photo", "image": "photo", "audio": "audio", "voice": "voice",
        "video": "video", "document": "document", "file": "document", "sticker": "sticker",
    }
    if reply_type in expected_types:
        expected = expected_types[reply_type]
        accepted = {expected}
        if reply_type in {"audio", "voice"}:
            accepted = {"audio", "voice"}
        if actual_type not in accepted:
            return False, None, custom_error or f"Please reply with a {reply_type}."
        return True, inbound.body or actual_type, None

    if actual_type != "text":
        return False, None, custom_error or "Please reply with text."

    value = str(inbound.body or "").strip()
    required = config.get("required", True) is not False
    if required and not value:
        return False, None, custom_error or "Please enter a reply."

    if reply_type in {"number", "integer", "decimal"}:
        try:
            number = float(value.replace(",", "."))
            if reply_type == "integer" and not number.is_integer():
                raise ValueError
        except ValueError:
            return False, None, custom_error or ("Please enter a whole number." if reply_type == "integer" else "Please enter a valid number.")
        minimum = config.get("min_value")
        maximum = config.get("max_value")
        if minimum not in (None, "") and number < float(minimum):
            return False, None, custom_error or f"Please enter a value of at least {minimum}."
        if maximum not in (None, "") and number > float(maximum):
            return False, None, custom_error or f"Please enter a value no greater than {maximum}."
        return True, str(int(number)) if reply_type == "integer" else str(number), None

    if reply_type == "email" and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        return False, None, custom_error or "Please enter a valid email address."
    if reply_type in {"phone", "telephone"}:
        compact = re.sub(r"[\s().-]", "", value)
        if not re.fullmatch(r"\+?\d{7,15}", compact):
            return False, None, custom_error or "Please enter a valid phone number."
    if reply_type == "date":
        date_format = str(config.get("date_format") or "%Y-%m-%d")
        try:
            datetime.strptime(value, date_format)
        except ValueError:
            return False, None, custom_error or "Please enter a valid date."

    min_length = config.get("min_length")
    max_length = config.get("max_length")
    if min_length not in (None, "") and len(value) < int(min_length):
        return False, None, custom_error or f"Please enter at least {min_length} characters."
    if max_length not in (None, "") and len(value) > int(max_length):
        return False, None, custom_error or f"Please enter no more than {max_length} characters."
    pattern = str(config.get("pattern") or "").strip()
    if pattern:
        try:
            if not re.fullmatch(pattern, value):
                return False, None, custom_error or "That reply is not in the expected format."
        except re.error:
            logger.warning("Invalid Telegram question validation regex: %s", pattern)

    return True, value, None


async def _run_from_node(
    db: Session,
    flow: Flow,
    conversation: TelegramConversation,
    inbound: TelegramMessage,
    session: TelegramFlowSession,
    node: FlowNode | None,
    by_id: dict,
    outgoing: dict,
) -> bool:
    safety = 0
    while node and safety < 100:
        safety += 1
        session.current_node_id = node.id
        session.status = "active"
        session.waiting_for = None
        session.updated_at = datetime.utcnow()
        config = _json(node.config_json)
        node_type = _enum_value(node.node_type)
        logger.info("Telegram flow executing flow=%s node=%s type=%s config=%s", flow.id, node.id, node_type, config)

        if node_type == FlowNodeType.SEND_MESSAGE.value:
            await _send(db, conversation, config.get("text"))
            node = _next(by_id, outgoing, node.id)
            continue

        if node_type == FlowNodeType.QUESTION.value:
            await _send(db, conversation, config.get("text"))
            session.status = "waiting"
            session.waiting_for = "reply"
            session.current_node_id = node.id
            session.updated_at = datetime.utcnow()
            db.flush()
            logger.warning("TGTRACE Telegram flow waiting flow=%s session=%s node=%s", flow.id, session.id, node.id)
            return True

        logger.info("Telegram flow %s skipping unsupported node type %s", flow.id, node_type)
        node = _next(by_id, outgoing, node.id)

    if safety >= 100:
        raise RuntimeError("Telegram flow graph exceeded 100 nodes; possible loop detected")

    session.status = "completed"
    session.current_node_id = None
    session.waiting_for = None
    session.ended_at = datetime.utcnow()
    session.updated_at = datetime.utcnow()
    db.flush()
    return True


async def _run_flow(db: Session, flow: Flow, conversation: TelegramConversation, inbound: TelegramMessage) -> bool:
    nodes, by_id, outgoing = _graph(db, flow.id)
    trigger = next((node for node in nodes if _is_node_type(node, FlowNodeType.TRIGGER)), None)
    if not trigger:
        logger.warning("Telegram flow %s has no trigger node", flow.id)
        return False

    session = _session_for_conversation(db, conversation.id)
    now = datetime.utcnow()
    if not session:
        session = TelegramFlowSession(conversation_id=conversation.id, flow_id=flow.id)
        db.add(session)
    session.flow_id = flow.id
    session.status = "active"
    session.current_node_id = trigger.id
    session.waiting_for = None
    session.last_inbound_message_id = inbound.id
    session.started_at = now
    session.updated_at = now
    session.ended_at = None
    db.flush()

    node = _next(by_id, outgoing, trigger.id)
    if not node:
        logger.warning("Telegram flow %s trigger node %s has no next edge", flow.id, trigger.id)
    return await _run_from_node(db, flow, conversation, inbound, session, node, by_id, outgoing)


async def _resume_waiting_session(
    db: Session,
    conversation: TelegramConversation,
    inbound: TelegramMessage,
    session: TelegramFlowSession,
) -> bool:
    flow = db.get(Flow, session.flow_id)
    if not flow or flow.status != FlowStatus.ACTIVE:
        session.status = "reset"
        session.current_node_id = None
        session.waiting_for = None
        session.ended_at = datetime.utcnow()
        db.flush()
        return False

    target = db.scalar(select(FlowChannelTarget).where(FlowChannelTarget.flow_id == flow.id))
    if not target or target.channel != "telegram" or flow.workspace_id != conversation.workspace_id:
        session.status = "reset"
        session.current_node_id = None
        session.waiting_for = None
        session.ended_at = datetime.utcnow()
        db.flush()
        return False

    nodes, by_id, outgoing = _graph(db, flow.id)
    waiting_node = by_id.get(session.current_node_id)
    if not waiting_node or not _is_node_type(waiting_node, FlowNodeType.QUESTION):
        session.status = "failed"
        session.waiting_for = None
        session.ended_at = datetime.utcnow()
        db.flush()
        return False

    config = _json(waiting_node.config_json)
    valid, value, validation_error = _validate_question_reply(config, inbound)
    session.last_inbound_message_id = inbound.id
    session.updated_at = datetime.utcnow()

    if not valid:
        session.status = "waiting"
        session.waiting_for = "reply"
        await _send(db, conversation, validation_error or "Please try again.")
        db.flush()
        logger.warning("TGTRACE Telegram question rejected session=%s node=%s body=%r", session.id, waiting_node.id, inbound.body)
        return True

    # Telegram contacts do not yet share WhatsApp custom-field storage, so retain the
    # captured value in the session trace for now and resume the graph immediately.
    logger.warning(
        "TGTRACE Telegram question captured session=%s node=%s field_id=%s value=%r",
        session.id,
        waiting_node.id,
        config.get("capture_field_id") or config.get("save_reply_field_id") or config.get("field_id"),
        value,
    )
    session.status = "active"
    session.waiting_for = None

    next_node = _next(by_id, outgoing, waiting_node.id, "next")
    if not next_node:
        session.status = "completed"
        session.current_node_id = None
        session.ended_at = datetime.utcnow()
        db.flush()
        return True

    return await _run_from_node(db, flow, conversation, inbound, session, next_node, by_id, outgoing)


async def run_telegram_flows_for_inbound(db: Session, conversation: TelegramConversation, inbound: TelegramMessage) -> int:
    existing = _session_for_conversation(db, conversation.id)
    if existing and existing.status == "waiting":
        try:
            if await _resume_waiting_session(db, conversation, inbound, existing):
                return 1
        except TelegramError:
            logger.exception("Telegram API error while resuming flow %s", existing.flow_id)
            raise
        except Exception:
            logger.exception("Telegram flow resume failed flow=%s conversation=%s", existing.flow_id, conversation.id)
            raise

    executed = 0
    for flow in _matching_flows(db, conversation, inbound):
        try:
            if await _run_flow(db, flow, conversation, inbound):
                executed += 1
        except TelegramError:
            logger.exception("Telegram API error while executing flow %s", flow.id)
            raise
        except Exception:
            logger.exception("Telegram flow execution failed flow=%s conversation=%s", flow.id, conversation.id)
    return executed
