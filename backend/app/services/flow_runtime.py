import json
import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.flow_models import Flow, FlowEdge, FlowNode, FlowNodeType, FlowSession, FlowSessionStatus, FlowStatus, FlowTriggerType
from app.models import (
    ContactFieldDefinition, ContactFieldValue, ContactTag, ContactTagLink, Conversation,
    ConversationStatus, Message, MessageDirection, MessageStatus, User,
)
from app.services.service_window import service_window_open
from app.services.whatsapp import WhatsAppError, send_text_message

logger = logging.getLogger(__name__)


def _json(value: str | None) -> dict:
    try: return json.loads(value or "{}")
    except (json.JSONDecodeError, TypeError): return {}


def _match_keyword(expected: str | None, body: str | None) -> bool:
    return bool(expected and body and expected.strip().casefold() == body.strip().casefold())


def _matching_flows(db: Session, conversation: Conversation, inbound_message: Message) -> list[Flow]:
    flows = db.scalars(select(Flow).options(selectinload(Flow.steps)).where(Flow.workspace_id == conversation.workspace_id, Flow.status == FlowStatus.ACTIVE).order_by(Flow.id)).all()
    inbound_count = db.scalar(select(func.count(Message.id)).where(Message.conversation_id == conversation.id, Message.direction == MessageDirection.INBOUND)) or 0
    return [f for f in flows if (f.trigger_type == FlowTriggerType.KEYWORD and _match_keyword(f.trigger_value, inbound_message.body)) or (f.trigger_type == FlowTriggerType.FIRST_MESSAGE and inbound_count == 1)]


def _session_for_conversation(db: Session, conversation_id: int) -> FlowSession | None:
    return db.scalar(select(FlowSession).where(FlowSession.conversation_id == conversation_id))


def _start_session(db: Session, conversation: Conversation, flow: Flow, inbound_message: Message) -> FlowSession:
    session = _session_for_conversation(db, conversation.id)
    now = datetime.utcnow()
    if not session:
        session = FlowSession(conversation_id=conversation.id, flow_id=flow.id)
        db.add(session)
    session.flow_id = flow.id
    session.current_node_id = None
    session.status = FlowSessionStatus.ACTIVE
    session.waiting_for = None
    session.last_inbound_message_id = inbound_message.id
    session.started_at = now
    session.updated_at = now
    session.ended_at = None
    session.reset_by_user_id = None
    db.flush()
    return session


def _finish_session(session: FlowSession, status: FlowSessionStatus = FlowSessionStatus.COMPLETED) -> None:
    session.status = status
    session.current_node_id = None
    session.waiting_for = None
    session.ended_at = datetime.utcnow()


async def _execute_action(db: Session, conversation: Conversation, action_type: str, config: dict) -> None:
    contact = conversation.contact
    if action_type in {"send_message", "question", "interactive"}:
        text = str(config.get("text") or "").strip()
        if not text: return
        if contact.blocked_at:
            logger.warning("Flow send skipped: contact %s is blocked", contact.id); return
        if not service_window_open(conversation):
            logger.warning("Flow send skipped: conversation %s is outside the 24-hour service window", conversation.id); return
        phone = conversation.phone_number
        if not phone.access_token: raise RuntimeError("WhatsApp phone number has no access token")
        response = await send_text_message(phone.phone_number_id, phone.access_token, contact.wa_id, text)
        meta_id = (response.get("messages") or [{}])[0].get("id")
        now = datetime.utcnow()
        db.add(Message(conversation_id=conversation.id, meta_message_id=meta_id, direction=MessageDirection.OUTBOUND, message_type="text", body=text, payload_json=json.dumps(response, ensure_ascii=False), status=MessageStatus.SENT, created_at=now))
        conversation.last_message_at = now; db.flush(); return

    if action_type in {"add_tag", "remove_tag"}:
        tag_id = config.get("tag_id")
        if not tag_id: return
        tag = db.scalar(select(ContactTag).where(ContactTag.id == int(tag_id), ContactTag.workspace_id == conversation.workspace_id))
        if not tag: return
        link = db.scalar(select(ContactTagLink).where(ContactTagLink.contact_id == contact.id, ContactTagLink.tag_id == tag.id))
        if action_type == "add_tag" and not link: db.add(ContactTagLink(contact_id=contact.id, tag_id=tag.id))
        elif action_type == "remove_tag" and link: db.delete(link)
        db.flush(); return

    if action_type == "set_field":
        field_id=config.get("field_id")
        if not field_id:return
        field=db.scalar(select(ContactFieldDefinition).where(ContactFieldDefinition.id==int(field_id),ContactFieldDefinition.workspace_id==conversation.workspace_id))
        if not field:return
        value=config.get("value")
        existing=db.scalar(select(ContactFieldValue).where(ContactFieldValue.contact_id==contact.id,ContactFieldValue.field_id==field.id))
        if existing: existing.value_text=None if value is None else str(value); existing.updated_at=datetime.utcnow()
        else: db.add(ContactFieldValue(contact_id=contact.id,field_id=field.id,value_text=None if value is None else str(value)))
        db.flush();return

    if action_type == "assign_user":
        user_id=config.get("user_id")
        if user_id in (None,"",0,"0"): conversation.assigned_user_id=None
        else:
            user=db.scalar(select(User).where(User.id==int(user_id),User.active.is_(True)))
            if user:conversation.assigned_user_id=user.id
        db.flush();return

    if action_type == "set_status":
        value=config.get("status")
        if value:conversation.status=ConversationStatus(value);db.flush()
        return

    if action_type == "delay":
        logger.info("Visual flow delay node skipped until scheduled resume support is implemented")
        return


def _compare(actual: str, expected: str, operator: str) -> bool:
    a=str(actual or "").strip(); e=str(expected or "").strip()
    if operator in {"equals","open"}: return a.casefold()==e.casefold()
    if operator in {"not_equals","closed"}: return a.casefold()!=e.casefold()
    if operator=="contains": return e.casefold() in a.casefold()
    if operator=="not_contains": return e.casefold() not in a.casefold()
    if operator=="starts_with": return a.casefold().startswith(e.casefold())
    if operator=="ends_with": return a.casefold().endswith(e.casefold())
    if operator=="empty": return not a
    if operator=="not_empty": return bool(a)
    return False


def _condition_result(db: Session, conversation: Conversation, config: dict) -> bool:
    field=str(config.get("field") or "service_window")
    operator=str(config.get("operator") or "open")
    expected=str(config.get("value") or "").strip()
    if field == "service_window":
        opened=service_window_open(conversation)
        if operator in {"open","equals"}: return opened
        if operator in {"closed","not_equals"}: return not opened
        return False
    if field == "conversation_status": return _compare(conversation.status.value, expected, operator)
    if field == "assigned_user": return _compare("" if conversation.assigned_user_id is None else str(conversation.assigned_user_id), expected, operator)
    if field == "tag":
        names=set(db.scalars(select(ContactTag.name).join(ContactTagLink,ContactTagLink.tag_id==ContactTag.id).where(ContactTagLink.contact_id==conversation.contact_id)).all())
        if operator=="empty": return not names
        if operator=="not_empty": return bool(names)
        matched=any(name.casefold()==expected.casefold() for name in names)
        return not matched if operator in {"not_equals","not_contains"} else matched
    if field == "custom_field":
        field_key=str(config.get("field_key") or config.get("key") or expected).strip()
        compare_value=str(config.get("compare_value") if "compare_value" in config else ("" if field_key==expected else expected)).strip()
        row=db.execute(select(ContactFieldValue.value_text).join(ContactFieldDefinition,ContactFieldDefinition.id==ContactFieldValue.field_id).where(ContactFieldValue.contact_id==conversation.contact_id,ContactFieldDefinition.key==field_key)).first()
        return _compare(((row[0] if row else "") or ""), compare_value, operator)
    return False


def _graph(db: Session, flow_id: int):
    nodes=db.scalars(select(FlowNode).where(FlowNode.flow_id==flow_id)).all()
    edges=db.scalars(select(FlowEdge).where(FlowEdge.flow_id==flow_id).order_by(FlowEdge.sort_order,FlowEdge.id)).all()
    by_id={n.id:n for n in nodes}; outgoing={}
    for e in edges: outgoing.setdefault(e.source_node_id,[]).append(e)
    return nodes, by_id, outgoing


def _next_node(by_id: dict, outgoing: dict, node_id: int, handle: str = "next") -> FlowNode | None:
    candidates=[e for e in outgoing.get(node_id,[]) if e.source_handle==handle]
    if len(candidates)>1: logger.warning("Node %s handle %s has %s outgoing edges; using first",node_id,handle,len(candidates))
    return by_id.get(candidates[0].target_node_id) if candidates else None


async def _run_graph(db: Session, flow: Flow, conversation: Conversation, session: FlowSession, start_node: FlowNode | None = None) -> bool:
    nodes,by_id,outgoing=_graph(db,flow.id)
    if not nodes:return False
    current=start_node or next((n for n in nodes if n.node_type==FlowNodeType.TRIGGER),None)
    if not current:return False
    visited=0
    while current and visited<100:
        visited+=1
        session.current_node_id=current.id;session.status=FlowSessionStatus.ACTIVE;session.waiting_for=None;db.flush()
        config=_json(current.config_json);handle="next"
        if current.node_type==FlowNodeType.CONDITION:
            result=_condition_result(db,conversation,config);handle="yes" if result else "no"
            logger.info("Flow %s condition node %s evaluated %s -> %s",flow.id,current.id,result,handle)
        elif current.node_type!=FlowNodeType.TRIGGER:
            await _execute_action(db,conversation,current.node_type.value,config)
            if current.node_type in {FlowNodeType.QUESTION,FlowNodeType.INTERACTIVE}:
                session.status=FlowSessionStatus.WAITING;session.waiting_for="reply";db.flush()
                logger.info("Flow %s session %s waiting for reply at node %s",flow.id,session.id,current.id)
                return True
        current=_next_node(by_id,outgoing,current.id,handle)
    if visited>=100: raise RuntimeError("Flow graph exceeded 100 nodes; possible loop detected")
    _finish_session(session)
    return True


async def _resume_waiting_session(db: Session, conversation: Conversation, inbound_message: Message, session: FlowSession) -> bool:
    flow=db.get(Flow,session.flow_id)
    if not flow or flow.status!=FlowStatus.ACTIVE:
        _finish_session(session,FlowSessionStatus.RESET);return False
    nodes,by_id,outgoing=_graph(db,flow.id)
    waiting_node=by_id.get(session.current_node_id)
    if not waiting_node:
        _finish_session(session,FlowSessionStatus.FAILED);return False
    session.last_inbound_message_id=inbound_message.id;session.status=FlowSessionStatus.ACTIVE;session.waiting_for=None
    next_node=_next_node(by_id,outgoing,waiting_node.id,"next")
    if not next_node:
        _finish_session(session);return True
    return await _run_graph(db,flow,conversation,session,start_node=next_node)


async def run_flows_for_inbound(db: Session, conversation: Conversation, inbound_message: Message) -> int:
    existing=_session_for_conversation(db,conversation.id)
    if existing and existing.status==FlowSessionStatus.WAITING:
        try:
            if await _resume_waiting_session(db,conversation,inbound_message,existing):db.commit();return 1
        except (WhatsAppError,RuntimeError,ValueError):
            db.rollback();raise

    matched=_matching_flows(db,conversation,inbound_message);executed=0
    for flow in matched:
        try:
            session=_start_session(db,conversation,flow,inbound_message)
            if await _run_graph(db,flow,conversation,session):db.commit();executed+=1;continue
            for step in sorted(flow.steps,key=lambda item:item.sort_order):await _execute_action(db,conversation,step.step_type.value,_json(step.config_json))
            _finish_session(session);db.commit();executed+=1
        except (WhatsAppError,RuntimeError,ValueError):
            db.rollback();raise
    return executed
