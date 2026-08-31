import json
import logging
import re
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.flow_models import Flow, FlowEdge, FlowNode, FlowNodeType, FlowSession, FlowSessionStatus, FlowStatus, FlowTriggerType
from app.models import (
    ContactFieldDefinition, ContactFieldValue, ContactTag, ContactTagLink, Conversation,
    ConversationStatus, Message, MessageDirection, MessageStatus, User,
)
from app.services.flow_variables import render_whatsapp
from app.services.service_window import service_window_open
from app.services.whatsapp import WhatsAppError, send_media_message, send_text_message

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
    session = _session_for_conversation(db, conversation.id); now = datetime.utcnow()
    if not session:
        session = FlowSession(conversation_id=conversation.id, flow_id=flow.id); db.add(session)
    session.flow_id=flow.id; session.current_node_id=None; session.status=FlowSessionStatus.ACTIVE; session.waiting_for=None; session.last_inbound_message_id=inbound_message.id; session.started_at=now; session.updated_at=now; session.ended_at=None; session.reset_by_user_id=None; db.flush(); return session


def _finish_session(session: FlowSession, status: FlowSessionStatus = FlowSessionStatus.COMPLETED) -> None:
    session.status=status; session.current_node_id=None; session.waiting_for=None; session.ended_at=datetime.utcnow()


def _set_contact_field_value(db: Session, conversation: Conversation, field_id: int, value) -> bool:
    field=db.scalar(select(ContactFieldDefinition).where(ContactFieldDefinition.id==int(field_id),ContactFieldDefinition.workspace_id==conversation.workspace_id,ContactFieldDefinition.active.is_(True)))
    if not field: logger.warning("Custom field %s not found/active in workspace %s",field_id,conversation.workspace_id); return False
    text=None if value is None else str(value).strip(); existing=db.scalar(select(ContactFieldValue).where(ContactFieldValue.contact_id==conversation.contact_id,ContactFieldValue.field_id==field.id))
    if existing: existing.value_text=text; existing.updated_at=datetime.utcnow()
    else: db.add(ContactFieldValue(contact_id=conversation.contact_id,field_id=field.id,value_text=text))
    db.flush(); return True


def _message_payload(message: Message) -> dict:
    try: return json.loads(message.payload_json or "{}")
    except (json.JSONDecodeError,TypeError): return {}


def _media_value(message: Message) -> str:
    payload=_message_payload(message); media_type=message.message_type or "unknown"; media=payload.get(media_type) or {}; value={"type":media_type,"id":media.get("id"),"mime_type":media.get("mime_type"),"sha256":media.get("sha256"),"caption":media.get("caption"),"filename":media.get("filename")}; return json.dumps({k:v for k,v in value.items() if v is not None},ensure_ascii=False)


def _validate_reply(config: dict, inbound_message: Message) -> tuple[bool,str|None,str|None]:
    reply_type=str(config.get("reply_type") or config.get("input_type") or "text").strip().lower(); actual_type=(inbound_message.message_type or "text").strip().lower(); custom_error=str(config.get("validation_error") or "").strip(); media_types={"image","audio","video","document","sticker"}; expected_types={"photo":"image","image":"image","audio":"audio","voice":"audio","video":"video","document":"document","file":"document","sticker":"sticker"}
    if reply_type in expected_types:
        expected=expected_types[reply_type]
        if actual_type!=expected: return False,None,custom_error or f"Please reply with a {{'image':'photo','audio':'audio/voice note','video':'video','document':'document','sticker':'sticker'}[expected]}."
        return True,_media_value(inbound_message),None
    if reply_type=="media":
        if actual_type not in media_types:return False,None,custom_error or "Please reply with a photo, audio, video or document."
        return True,_media_value(inbound_message),None
    if actual_type not in {"text","button","interactive"}:return False,None,custom_error or "Please reply with text."
    value=(inbound_message.body or "").strip()
    if actual_type in {"button","interactive"}:return True,value,None
    if config.get("required",True) is not False and not value:return False,None,custom_error or "Please enter a reply."
    if reply_type in {"number","integer","decimal"}:
        try:
            number=float(value.replace(",","."))
            if reply_type=="integer" and not number.is_integer():raise ValueError
        except ValueError:return False,None,custom_error or ("Please enter a whole number." if reply_type=="integer" else "Please enter a valid number.")
        minimum=config.get("min_value"); maximum=config.get("max_value")
        if minimum not in (None,"") and number<float(minimum):return False,None,custom_error or f"Please enter a value of at least {minimum}."
        if maximum not in (None,"") and number>float(maximum):return False,None,custom_error or f"Please enter a value no greater than {maximum}."
        return True,str(int(number)) if reply_type=="integer" else str(number),None
    if reply_type=="email" and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",value):return False,None,custom_error or "Please enter a valid email address."
    elif reply_type in {"phone","telephone"}:
        if not re.fullmatch(r"\+?\d{7,15}",re.sub(r"[\s().-]","",value)):return False,None,custom_error or "Please enter a valid phone number."
    elif reply_type=="date":
        try:datetime.strptime(value,str(config.get("date_format") or "%Y-%m-%d"))
        except ValueError:return False,None,custom_error or "Please enter a valid date in YYYY-MM-DD format."
    min_length=config.get("min_length"); max_length=config.get("max_length")
    if min_length not in (None,"") and len(value)<int(min_length):return False,None,custom_error or f"Please enter at least {min_length} characters."
    if max_length not in (None,"") and len(value)>int(max_length):return False,None,custom_error or f"Please enter no more than {max_length} characters."
    pattern=str(config.get("pattern") or "").strip()
    if pattern:
        try:
            if not re.fullmatch(pattern,value):return False,None,custom_error or "That reply is not in the expected format."
        except re.error:logger.warning("Invalid validation regex on flow question node: %s",pattern)
    return True,value,None


def _can_send_flow_message(conversation: Conversation) -> bool:
    contact=conversation.contact
    if contact.blocked_at:logger.warning("Flow send skipped: contact %s is blocked",contact.id);return False
    if not service_window_open(conversation):logger.warning("Flow send skipped: conversation %s is outside the 24-hour service window",conversation.id);return False
    return True


async def _send_flow_text(db: Session, conversation: Conversation, text: str) -> None:
    text=render_whatsapp(db,conversation,text).strip()
    if not text or not _can_send_flow_message(conversation):return
    phone=conversation.phone_number
    if not phone.access_token:raise RuntimeError("WhatsApp phone number has no access token")
    response=await send_text_message(phone.phone_number_id,phone.access_token,conversation.contact.wa_id,text); meta_id=(response.get("messages") or [{}])[0].get("id"); now=datetime.utcnow(); db.add(Message(conversation_id=conversation.id,meta_message_id=meta_id,direction=MessageDirection.OUTBOUND,message_type="text",body=text,payload_json=json.dumps(response,ensure_ascii=False),status=MessageStatus.SENT,created_at=now)); conversation.last_message_at=now; db.flush()


async def _send_flow_media(db: Session, conversation: Conversation, media_type: str, config: dict) -> None:
    media=render_whatsapp(db,conversation,config.get("media") or config.get("media_url") or config.get("url") or config.get("file_id") or "").strip(); caption=render_whatsapp(db,conversation,config.get("caption") or config.get("text") or "").strip(); filename=render_whatsapp(db,conversation,config.get("filename") or "").strip()
    if not media:logger.warning("WhatsApp %s flow block has no media URL/ID",media_type);return
    if not _can_send_flow_message(conversation):return
    phone=conversation.phone_number
    if not phone.access_token:raise RuntimeError("WhatsApp phone number has no access token")
    response=await send_media_message(phone.phone_number_id,phone.access_token,conversation.contact.wa_id,media_type,media,caption or None,filename or None); meta_id=(response.get("messages") or [{}])[0].get("id"); now=datetime.utcnow(); stored_type="document" if media_type=="file" else media_type; db.add(Message(conversation_id=conversation.id,meta_message_id=meta_id,direction=MessageDirection.OUTBOUND,message_type=stored_type,body=caption or None,payload_json=json.dumps(response,ensure_ascii=False),status=MessageStatus.SENT,created_at=now)); conversation.last_message_at=now; db.flush()


async def _capture_reply(db: Session, conversation: Conversation, waiting_node: FlowNode, inbound_message: Message) -> bool:
    config=_json(waiting_node.config_json)
    if waiting_node.node_type!=FlowNodeType.QUESTION:return True
    valid,value,validation_error=_validate_reply(config,inbound_message)
    if not valid:logger.info("Question node %s rejected reply type=%s",waiting_node.id,inbound_message.message_type);await _send_flow_text(db,conversation,validation_error or "Please try again.");return False
    field_id=config.get("capture_field_id") or config.get("save_reply_field_id") or config.get("field_id")
    if field_id and _set_contact_field_value(db,conversation,int(field_id),value):logger.info("Flow question node %s captured %s reply into custom field %s",waiting_node.id,config.get("reply_type","text"),field_id)
    return True


async def _execute_action(db: Session, conversation: Conversation, action_type: str, config: dict) -> None:
    contact=conversation.contact
    if action_type in {"send_message","question","interactive"}:await _send_flow_text(db,conversation,config.get("text"));return
    if action_type in {"image","video","audio","file"}:await _send_flow_media(db,conversation,action_type,config);return
    if action_type in {"add_tag","remove_tag"}:
        tag_id=config.get("tag_id")
        if not tag_id:return
        tag=db.scalar(select(ContactTag).where(ContactTag.id==int(tag_id),ContactTag.workspace_id==conversation.workspace_id))
        if not tag:return
        link=db.scalar(select(ContactTagLink).where(ContactTagLink.contact_id==contact.id,ContactTagLink.tag_id==tag.id))
        if action_type=="add_tag" and not link:db.add(ContactTagLink(contact_id=contact.id,tag_id=tag.id))
        elif action_type=="remove_tag" and link:db.delete(link)
        db.flush();return
    if action_type=="set_field":
        field_id=config.get("field_id")
        if not field_id:return
        _set_contact_field_value(db,conversation,int(field_id),render_whatsapp(db,conversation,config.get("value")));return
    if action_type=="assign_user":
        user_id=config.get("user_id")
        if user_id in (None,"",0,"0"):conversation.assigned_user_id=None
        else:
            user=db.scalar(select(User).where(User.id==int(user_id),User.active.is_(True)))
            if user:conversation.assigned_user_id=user.id
        db.flush();return
    if action_type=="set_status":
        value=config.get("status")
        if value:conversation.status=ConversationStatus(value);db.flush()
        return
    if action_type=="delay":logger.info("Visual flow delay node skipped until scheduled resume support is implemented");return


def _compare(actual: str, expected: str, operator: str) -> bool:
    a=str(actual or "").strip();e=str(expected or "").strip()
    if operator in {"equals","open"}:return a.casefold()==e.casefold()
    if operator in {"not_equals","closed"}:return a.casefold()!=e.casefold()
    if operator=="contains":return e.casefold() in a.casefold()
    if operator=="not_contains":return e.casefold() not in a.casefold()
    if operator=="starts_with":return a.casefold().startswith(e.casefold())
    if operator=="ends_with":return a.casefold().endswith(e.casefold())
    if operator=="empty":return not a
    if operator=="not_empty":return bool(a)
    return False


def _condition_result(db: Session, conversation: Conversation, config: dict) -> bool:
    field=str(config.get("field") or "service_window");operator=str(config.get("operator") or "open");expected=str(config.get("value") or "").strip()
    if field=="service_window":
        opened=service_window_open(conversation)
        if operator in {"open","equals"}:return opened
        if operator in {"closed","not_equals"}:return not opened
        return False
    if field=="conversation_status":return _compare(conversation.status.value,expected,operator)
    if field=="assigned_user":return _compare("" if conversation.assigned_user_id is None else str(conversation.assigned_user_id),expected,operator)
    if field=="tag":
        names=set(db.scalars(select(ContactTag.name).join(ContactTagLink,ContactTagLink.tag_id==ContactTag.id).where(ContactTagLink.contact_id==conversation.contact_id)).all())
        if operator=="empty":return not names
        if operator=="not_empty":return bool(names)
        matched=any(name.casefold()==expected.casefold() for name in names);return not matched if operator in {"not_equals","not_contains"} else matched
    if field=="custom_field":
        field_key=str(config.get("field_key") or config.get("key") or expected).strip();compare_value=str(config.get("compare_value") if "compare_value" in config else ("" if field_key==expected else expected)).strip();row=db.execute(select(ContactFieldValue.value_text).join(ContactFieldDefinition,ContactFieldDefinition.id==ContactFieldValue.field_id).where(ContactFieldValue.contact_id==conversation.contact_id,ContactFieldDefinition.key==field_key)).first();return _compare(((row[0] if row else "") or ""),compare_value,operator)
    return False


def _graph(db: Session, flow_id: int):
    nodes=db.scalars(select(FlowNode).where(FlowNode.flow_id==flow_id)).all();edges=db.scalars(select(FlowEdge).where(FlowEdge.flow_id==flow_id).order_by(FlowEdge.sort_order,FlowEdge.id)).all();by_id={n.id:n for n in nodes};outgoing={}
    for e in edges:outgoing.setdefault(e.source_node_id,[]).append(e)
    return nodes,by_id,outgoing


def _next_node(by_id: dict,outgoing: dict,node_id: int,handle: str="next") -> FlowNode|None:
    candidates=[e for e in outgoing.get(node_id,[]) if e.source_handle==handle]
    if len(candidates)>1:logger.warning("Node %s handle %s has %s outgoing edges; using first",node_id,handle,len(candidates))
    return by_id.get(candidates[0].target_node_id) if candidates else None


async def _run_graph(db: Session,flow: Flow,conversation: Conversation,session: FlowSession,start_node: FlowNode|None=None) -> bool:
    nodes,by_id,outgoing=_graph(db,flow.id)
    if not nodes:return False
    current=start_node or next((n for n in nodes if n.node_type==FlowNodeType.TRIGGER),None)
    if not current:return False
    visited=0
    while current and visited<100:
        visited+=1;session.current_node_id=current.id;session.status=FlowSessionStatus.ACTIVE;session.waiting_for=None;db.flush();config=_json(current.config_json);handle="next"
        if current.node_type==FlowNodeType.CONDITION:
            result=_condition_result(db,conversation,config);handle="yes" if result else "no";logger.info("Flow %s condition node %s evaluated %s -> %s",flow.id,current.id,result,handle)
        elif current.node_type!=FlowNodeType.TRIGGER:
            await _execute_action(db,conversation,current.node_type.value,config)
            if current.node_type in {FlowNodeType.QUESTION,FlowNodeType.INTERACTIVE}:session.status=FlowSessionStatus.WAITING;session.waiting_for="reply";db.flush();logger.info("Flow %s session %s waiting for reply at node %s",flow.id,session.id,current.id);return True
        current=_next_node(by_id,outgoing,current.id,handle)
    if visited>=100:raise RuntimeError("Flow graph exceeded 100 nodes; possible loop detected")
    _finish_session(session);return True


async def _resume_waiting_session(db: Session,conversation: Conversation,inbound_message: Message,session: FlowSession) -> bool:
    flow=db.get(Flow,session.flow_id)
    if not flow or flow.status!=FlowStatus.ACTIVE:_finish_session(session,FlowSessionStatus.RESET);return False
    nodes,by_id,outgoing=_graph(db,flow.id);waiting_node=by_id.get(session.current_node_id)
    if not waiting_node:_finish_session(session,FlowSessionStatus.FAILED);return False
    if not await _capture_reply(db,conversation,waiting_node,inbound_message):session.last_inbound_message_id=inbound_message.id;session.status=FlowSessionStatus.WAITING;session.waiting_for="reply";session.updated_at=datetime.utcnow();db.flush();return True
    session.last_inbound_message_id=inbound_message.id;session.status=FlowSessionStatus.ACTIVE;session.waiting_for=None;next_node=_next_node(by_id,outgoing,waiting_node.id,"next")
    if not next_node:_finish_session(session);return True
    return await _run_graph(db,flow,conversation,session,start_node=next_node)


async def run_flows_for_inbound(db: Session,conversation: Conversation,inbound_message: Message) -> int:
    existing=_session_for_conversation(db,conversation.id)
    if existing and existing.status==FlowSessionStatus.WAITING:
        try:
            if await _resume_waiting_session(db,conversation,inbound_message,existing):db.commit();return 1
        except (WhatsAppError,RuntimeError,ValueError):db.rollback();raise
    matched=_matching_flows(db,conversation,inbound_message);executed=0
    for flow in matched:
        try:
            session=_start_session(db,conversation,flow,inbound_message)
            if await _run_graph(db,flow,conversation,session):db.commit();executed+=1;continue
            for step in sorted(flow.steps,key=lambda item:item.sort_order):await _execute_action(db,conversation,step.step_type.value,_json(step.config_json))
            _finish_session(session);db.commit();executed+=1
        except (WhatsAppError,RuntimeError,ValueError):db.rollback();raise
    return executed
