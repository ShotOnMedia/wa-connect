import json
import logging
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


async def _run_flow(db: Session, flow: Flow, conversation: TelegramConversation, inbound: TelegramMessage) -> bool:
    nodes, by_id, outgoing = _graph(db, flow.id)
    trigger = next((node for node in nodes if _is_node_type(node, FlowNodeType.TRIGGER)), None)
    if not trigger:
        logger.warning("Telegram flow %s has no trigger node", flow.id)
        return False

    session = db.scalar(select(TelegramFlowSession).where(TelegramFlowSession.conversation_id == conversation.id))
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

    safety = 0
    while node and safety < 100:
        safety += 1
        session.current_node_id = node.id
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
            db.flush()
            return True

        logger.info("Telegram flow %s skipping unsupported node type %s", flow.id, node_type)
        node = _next(by_id, outgoing, node.id)

    session.status = "completed"
    session.current_node_id = None
    session.waiting_for = None
    session.ended_at = datetime.utcnow()
    db.flush()
    return True


async def run_telegram_flows_for_inbound(db: Session, conversation: TelegramConversation, inbound: TelegramMessage) -> int:
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
