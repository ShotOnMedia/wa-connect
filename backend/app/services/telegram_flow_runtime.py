import json
import logging
import re
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.flow_channel_models import FlowChannelTarget, TelegramFlowSession
from app.flow_models import Flow, FlowEdge, FlowNode, FlowNodeType, FlowStatus, FlowTriggerType
from app.models import ContactFieldDefinition
from app.services.telegram import TelegramError, send_media, send_text
from app.services.telegram_flow_actions import assign_user, change_tag, condition_result, set_field, set_status
from app.telegram_models import TelegramContactFieldValue, TelegramConversation, TelegramMessage

logger = logging.getLogger(__name__)


def _json(value):
    if isinstance(value, dict): return value
    try: return json.loads(value or "{}")
    except (json.JSONDecodeError, TypeError): return {}


def _enum_value(value): return getattr(value, "value", value)
def _is_node_type(node, expected): return _enum_value(node.node_type) == expected.value
def _keyword_matches(expected, body): return bool(expected and body and expected.strip().casefold() == body.strip().casefold())
def _session_for_conversation(db, conversation_id): return db.scalar(select(TelegramFlowSession).where(TelegramFlowSession.conversation_id == conversation_id))


def _matching_flows(db, conversation, inbound):
    flows = db.scalars(select(Flow).join(FlowChannelTarget, FlowChannelTarget.flow_id == Flow.id).where(Flow.workspace_id == conversation.workspace_id, Flow.status == FlowStatus.ACTIVE, FlowChannelTarget.channel == "telegram").order_by(Flow.id)).all()
    inbound_count = db.scalar(select(func.count(TelegramMessage.id)).where(TelegramMessage.conversation_id == conversation.id, TelegramMessage.direction == "inbound")) or 0
    return [flow for flow in flows if (_enum_value(flow.trigger_type) == FlowTriggerType.KEYWORD.value and _keyword_matches(flow.trigger_value, inbound.body)) or (_enum_value(flow.trigger_type) == FlowTriggerType.FIRST_MESSAGE.value and inbound_count == 1)]


def _graph(db, flow_id):
    nodes = db.scalars(select(FlowNode).where(FlowNode.flow_id == flow_id)).all(); edges = db.scalars(select(FlowEdge).where(FlowEdge.flow_id == flow_id).order_by(FlowEdge.sort_order, FlowEdge.id)).all(); by_id = {n.id:n for n in nodes}; outgoing = {}
    for edge in edges: outgoing.setdefault(edge.source_node_id, []).append(edge)
    return nodes, by_id, outgoing


def _next(by_id, outgoing, node_id, handle="next"):
    matches = [e for e in outgoing.get(node_id, []) if e.source_handle == handle]
    return by_id.get(matches[0].target_node_id) if matches else None


def _render_text(db: Session, conversation: TelegramConversation, text) -> str:
    value = str(text or ""); keys = set(re.findall(r"%([A-Za-z0-9_.-]+)%", value))
    if not keys: return value
    rows = db.execute(select(ContactFieldDefinition.key, TelegramContactFieldValue.value_text).outerjoin(TelegramContactFieldValue,(TelegramContactFieldValue.field_id == ContactFieldDefinition.id) & (TelegramContactFieldValue.contact_id == conversation.contact_id)).where(ContactFieldDefinition.workspace_id == conversation.workspace_id,ContactFieldDefinition.key.in_(keys))).all()
    values = {str(key):(field_value or "") for key,field_value in rows}
    return re.sub(r"%([A-Za-z0-9_.-]+)%", lambda m:str(values.get(m.group(1), "")), value)


async def _send(db, conversation, text):
    text = _render_text(db, conversation, text).strip()
    if not text: return
    result = await send_text(conversation.bot.access_token, conversation.chat_id, text)
    timestamp = datetime.utcfromtimestamp(result["date"]) if result.get("date") else datetime.utcnow()
    db.add(TelegramMessage(conversation_id=conversation.id,telegram_message_id=int(result["message_id"]),direction="outbound",message_type="text",body=result.get("text") or text,payload_json=json.dumps(result,ensure_ascii=False),status="sent",telegram_timestamp=timestamp)); conversation.last_message_at=timestamp; db.flush()


async def _send_flow_media(db, conversation, media_type, config):
    media = _render_text(db, conversation, config.get("media") or config.get("media_url") or config.get("url") or config.get("file_id")).strip()
    caption = _render_text(db, conversation, config.get("caption") or config.get("text") or "").strip()
    if not media:
        logger.warning("Telegram %s flow block has no media URL/file_id", media_type); return
    result = await send_media(conversation.bot.access_token, conversation.chat_id, media_type, media, caption or None)
    timestamp = datetime.utcfromtimestamp(result["date"]) if result.get("date") else datetime.utcnow()
    body = result.get("caption") or caption or None
    db.add(TelegramMessage(conversation_id=conversation.id,telegram_message_id=int(result["message_id"]),direction="outbound",message_type=media_type,body=body,payload_json=json.dumps(result,ensure_ascii=False),status="sent",telegram_timestamp=timestamp)); conversation.last_message_at=timestamp; db.flush()


def _validate_question_reply(config, inbound):
    reply_type=str(config.get("reply_type") or config.get("input_type") or "text").strip().lower(); actual_type=str(inbound.message_type or "text").strip().lower(); custom_error=str(config.get("validation_error") or "").strip(); expected_types={"photo":"photo","image":"photo","audio":"audio","voice":"voice","video":"video","document":"document","file":"document","sticker":"sticker"}
    if reply_type in expected_types:
        accepted={expected_types[reply_type]}
        if reply_type in {"audio","voice"}: accepted={"audio","voice"}
        if actual_type not in accepted:return False,None,custom_error or f"Please reply with a {reply_type}."
        return True,inbound.body or actual_type,None
    if actual_type!="text":return False,None,custom_error or "Please reply with text."
    value=str(inbound.body or "").strip()
    if config.get("required",True) is not False and not value:return False,None,custom_error or "Please enter a reply."
    if reply_type in {"number","integer","decimal"}:
        try:
            number=float(value.replace(",","."))
            if reply_type=="integer" and not number.is_integer():raise ValueError
        except ValueError:return False,None,custom_error or "Please enter a valid number."
        minimum,maximum=config.get("min_value"),config.get("max_value")
        if minimum not in (None,"") and number<float(minimum):return False,None,custom_error or f"Please enter a value of at least {minimum}."
        if maximum not in (None,"") and number>float(maximum):return False,None,custom_error or f"Please enter a value no greater than {maximum}."
        return True,str(int(number)) if reply_type=="integer" else str(number),None
    if reply_type=="email" and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",value):return False,None,custom_error or "Please enter a valid email address."
    if reply_type in {"phone","telephone"} and not re.fullmatch(r"\+?\d{7,15}",re.sub(r"[\s().-]","",value)):return False,None,custom_error or "Please enter a valid phone number."
    if reply_type=="date":
        try:datetime.strptime(value,str(config.get("date_format") or "%Y-%m-%d"))
        except ValueError:return False,None,custom_error or "Please enter a valid date."
    minimum,maximum=config.get("min_length"),config.get("max_length")
    if minimum not in (None,"") and len(value)<int(minimum):return False,None,custom_error or f"Please enter at least {minimum} characters."
    if maximum not in (None,"") and len(value)>int(maximum):return False,None,custom_error or f"Please enter no more than {maximum} characters."
    pattern=str(config.get("pattern") or "").strip()
    if pattern:
        try:
            if not re.fullmatch(pattern,value):return False,None,custom_error or "That reply is not in the expected format."
        except re.error:logger.warning("Invalid Telegram question regex: %s",pattern)
    return True,value,None


async def _run_from_node(db, flow, conversation, inbound, session, node, by_id, outgoing):
    safety=0
    while node and safety<100:
        safety+=1; session.current_node_id=node.id; session.status="active"; session.waiting_for=None; session.updated_at=datetime.utcnow(); config=_json(node.config_json); node_type=_enum_value(node.node_type)
        if node_type==FlowNodeType.SEND_MESSAGE.value:await _send(db,conversation,config.get("text"));node=_next(by_id,outgoing,node.id);continue
        if node_type in {"image","video","audio","file"}:await _send_flow_media(db,conversation,node_type,config);node=_next(by_id,outgoing,node.id);continue
        if node_type==FlowNodeType.QUESTION.value:await _send(db,conversation,config.get("text"));session.status="waiting";session.waiting_for="reply";db.flush();return True
        if node_type==FlowNodeType.ADD_TAG.value:
            if config.get("tag_id"):change_tag(db,conversation,int(config["tag_id"]),True)
            node=_next(by_id,outgoing,node.id);continue
        if node_type==FlowNodeType.REMOVE_TAG.value:
            if config.get("tag_id"):change_tag(db,conversation,int(config["tag_id"]),False)
            node=_next(by_id,outgoing,node.id);continue
        if node_type==FlowNodeType.SET_FIELD.value:
            field_id=config.get("field_id") or config.get("capture_field_id")
            if field_id:set_field(db,conversation,int(field_id),_render_text(db,conversation,config.get("value")))
            node=_next(by_id,outgoing,node.id);continue
        if node_type==FlowNodeType.ASSIGN_USER.value:assign_user(db,conversation,config.get("user_id"));node=_next(by_id,outgoing,node.id);continue
        if node_type==FlowNodeType.SET_STATUS.value:set_status(db,conversation,config.get("status"));node=_next(by_id,outgoing,node.id);continue
        if node_type==FlowNodeType.CONDITION.value:node=_next(by_id,outgoing,node.id,"yes" if condition_result(db,conversation,config) else "no");continue
        if node_type==FlowNodeType.DELAY.value:logger.info("Telegram delay node skipped until scheduled resume support is implemented");node=_next(by_id,outgoing,node.id);continue
        logger.info("Telegram flow %s skipping unsupported node type %s",flow.id,node_type);node=_next(by_id,outgoing,node.id)
    if safety>=100:raise RuntimeError("Telegram flow graph exceeded 100 nodes; possible loop detected")
    session.status="completed";session.current_node_id=None;session.waiting_for=None;session.ended_at=datetime.utcnow();session.updated_at=datetime.utcnow();db.flush();return True


async def _run_flow(db,flow,conversation,inbound):
    nodes,by_id,outgoing=_graph(db,flow.id);trigger=next((n for n in nodes if _is_node_type(n,FlowNodeType.TRIGGER)),None)
    if not trigger:return False
    session=_session_for_conversation(db,conversation.id);now=datetime.utcnow()
    if not session:session=TelegramFlowSession(conversation_id=conversation.id,flow_id=flow.id);db.add(session)
    session.flow_id=flow.id;session.status="active";session.current_node_id=trigger.id;session.waiting_for=None;session.last_inbound_message_id=inbound.id;session.started_at=now;session.updated_at=now;session.ended_at=None;db.flush()
    return await _run_from_node(db,flow,conversation,inbound,session,_next(by_id,outgoing,trigger.id),by_id,outgoing)


async def _resume_waiting_session(db,conversation,inbound,session):
    flow=db.get(Flow,session.flow_id);target=db.scalar(select(FlowChannelTarget).where(FlowChannelTarget.flow_id==session.flow_id)) if flow else None
    if not flow or flow.status!=FlowStatus.ACTIVE or not target or target.channel!="telegram" or flow.workspace_id!=conversation.workspace_id:session.status="reset";session.current_node_id=None;session.waiting_for=None;session.ended_at=datetime.utcnow();db.flush();return False
    nodes,by_id,outgoing=_graph(db,flow.id);waiting_node=by_id.get(session.current_node_id)
    if not waiting_node or not _is_node_type(waiting_node,FlowNodeType.QUESTION):session.status="failed";session.waiting_for=None;session.ended_at=datetime.utcnow();db.flush();return False
    config=_json(waiting_node.config_json);valid,value,error=_validate_question_reply(config,inbound);session.last_inbound_message_id=inbound.id;session.updated_at=datetime.utcnow()
    if not valid:session.status="waiting";session.waiting_for="reply";await _send(db,conversation,error or "Please try again.");db.flush();return True
    field_id=config.get("capture_field_id") or config.get("save_reply_field_id") or config.get("field_id")
    if field_id:set_field(db,conversation,int(field_id),value)
    session.status="active";session.waiting_for=None;next_node=_next(by_id,outgoing,waiting_node.id,"next")
    if not next_node:session.status="completed";session.current_node_id=None;session.ended_at=datetime.utcnow();db.flush();return True
    return await _run_from_node(db,flow,conversation,inbound,session,next_node,by_id,outgoing)


async def run_telegram_flows_for_inbound(db:Session,conversation:TelegramConversation,inbound:TelegramMessage)->int:
    existing=_session_for_conversation(db,conversation.id)
    if existing and existing.status=="waiting":
        try:
            if await _resume_waiting_session(db,conversation,inbound,existing):return 1
        except TelegramError:raise
        except Exception:logger.exception("Telegram flow resume failed flow=%s conversation=%s",existing.flow_id,conversation.id);raise
    executed=0
    for flow in _matching_flows(db,conversation,inbound):
        try:
            if await _run_flow(db,flow,conversation,inbound):executed+=1
        except TelegramError:raise
        except Exception:logger.exception("Telegram flow execution failed flow=%s conversation=%s",flow.id,conversation.id)
    return executed
