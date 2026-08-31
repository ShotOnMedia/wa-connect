import json
import logging
import re
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.flow_models import Flow, FlowEdge, FlowNode, FlowNodeType, FlowSession, FlowSessionStatus, FlowStatus, FlowTriggerType
from app.models import ContactFieldDefinition, ContactFieldValue, ContactTag, ContactTagLink, Conversation, ConversationStatus, Message, MessageDirection, MessageStatus, User
from app.services.flow_variables import render_whatsapp
from app.services.service_window import service_window_open
from app.services.whatsapp import WhatsAppError, send_media_message, send_text_message

logger=logging.getLogger(__name__)

def _json(value):
    try:return json.loads(value or "{}")
    except (json.JSONDecodeError,TypeError):return {}

def _match_keyword(expected,body):return bool(expected and body and expected.strip().casefold()==body.strip().casefold())
def _session_for_conversation(db,conversation_id):return db.scalar(select(FlowSession).where(FlowSession.conversation_id==conversation_id))

def _matching_flows(db,conversation,inbound):
    flows=db.scalars(select(Flow).options(selectinload(Flow.steps)).where(Flow.workspace_id==conversation.workspace_id,Flow.status==FlowStatus.ACTIVE).order_by(Flow.id)).all();count=db.scalar(select(func.count(Message.id)).where(Message.conversation_id==conversation.id,Message.direction==MessageDirection.INBOUND)) or 0
    return [f for f in flows if (f.trigger_type==FlowTriggerType.KEYWORD and _match_keyword(f.trigger_value,inbound.body)) or (f.trigger_type==FlowTriggerType.FIRST_MESSAGE and count==1)]

def _start_session(db,conversation,flow,inbound):
    s=_session_for_conversation(db,conversation.id);now=datetime.utcnow()
    if not s:s=FlowSession(conversation_id=conversation.id,flow_id=flow.id);db.add(s)
    s.flow_id=flow.id;s.current_node_id=None;s.status=FlowSessionStatus.ACTIVE;s.waiting_for=None;s.last_inbound_message_id=inbound.id;s.started_at=now;s.updated_at=now;s.ended_at=None;s.reset_by_user_id=None;db.flush();return s

def _finish_session(s,status=FlowSessionStatus.COMPLETED):s.status=status;s.current_node_id=None;s.waiting_for=None;s.ended_at=datetime.utcnow()

def _set_contact_field_value(db,conversation,field_id,value):
    field=db.scalar(select(ContactFieldDefinition).where(ContactFieldDefinition.id==int(field_id),ContactFieldDefinition.workspace_id==conversation.workspace_id,ContactFieldDefinition.active.is_(True)))
    if not field:logger.warning("Custom field %s not found/active in workspace %s",field_id,conversation.workspace_id);return False
    text=None if value is None else str(value).strip();row=db.scalar(select(ContactFieldValue).where(ContactFieldValue.contact_id==conversation.contact_id,ContactFieldValue.field_id==field.id))
    if row:row.value_text=text;row.updated_at=datetime.utcnow()
    else:db.add(ContactFieldValue(contact_id=conversation.contact_id,field_id=field.id,value_text=text))
    db.flush();return True

def _media_value(message):
    try:payload=json.loads(message.payload_json or "{}")
    except (json.JSONDecodeError,TypeError):payload={}
    kind=message.message_type or "unknown";media=payload.get(kind) or {};value={"type":kind,"id":media.get("id"),"mime_type":media.get("mime_type"),"sha256":media.get("sha256"),"caption":media.get("caption"),"filename":media.get("filename")};return json.dumps({k:v for k,v in value.items() if v is not None},ensure_ascii=False)

def _validate_reply(config,inbound):
    reply_type=str(config.get("reply_type") or config.get("input_type") or "text").strip().lower();actual=(inbound.message_type or "text").strip().lower();err=str(config.get("validation_error") or "").strip();expected_types={"photo":"image","image":"image","audio":"audio","voice":"audio","video":"video","document":"document","file":"document","sticker":"sticker"};labels={"image":"photo","audio":"audio/voice note","video":"video","document":"document","sticker":"sticker"}
    if reply_type in expected_types:
        expected=expected_types[reply_type]
        if actual!=expected:return False,None,err or f"Please reply with a {labels[expected]}."
        return True,_media_value(inbound),None
    if reply_type=="media":
        if actual not in {"image","audio","video","document","sticker"}:return False,None,err or "Please reply with a photo, audio, video or document."
        return True,_media_value(inbound),None
    if actual not in {"text","button","interactive"}:return False,None,err or "Please reply with text."
    value=(inbound.body or "").strip()
    if actual in {"button","interactive"}:return True,value,None
    if config.get("required",True) is not False and not value:return False,None,err or "Please enter a reply."
    if reply_type in {"number","integer","decimal"}:
        try:
            number=float(value.replace(",","."))
            if reply_type=="integer" and not number.is_integer():raise ValueError
        except ValueError:return False,None,err or ("Please enter a whole number." if reply_type=="integer" else "Please enter a valid number.")
        lo,hi=config.get("min_value"),config.get("max_value")
        if lo not in (None,"") and number<float(lo):return False,None,err or f"Please enter a value of at least {lo}."
        if hi not in (None,"") and number>float(hi):return False,None,err or f"Please enter a value no greater than {hi}."
        return True,str(int(number)) if reply_type=="integer" else str(number),None
    if reply_type=="email" and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",value):return False,None,err or "Please enter a valid email address."
    if reply_type in {"phone","telephone"} and not re.fullmatch(r"\+?\d{7,15}",re.sub(r"[\s().-]","",value)):return False,None,err or "Please enter a valid phone number."
    if reply_type=="date":
        try:datetime.strptime(value,str(config.get("date_format") or "%Y-%m-%d"))
        except ValueError:return False,None,err or "Please enter a valid date in YYYY-MM-DD format."
    lo,hi=config.get("min_length"),config.get("max_length")
    if lo not in (None,"") and len(value)<int(lo):return False,None,err or f"Please enter at least {lo} characters."
    if hi not in (None,"") and len(value)>int(hi):return False,None,err or f"Please enter no more than {hi} characters."
    pattern=str(config.get("pattern") or "").strip()
    if pattern:
        try:
            if not re.fullmatch(pattern,value):return False,None,err or "That reply is not in the expected format."
        except re.error:logger.warning("Invalid validation regex on flow question node: %s",pattern)
    return True,value,None

def _can_send(conversation):
    if conversation.contact.blocked_at:logger.warning("Flow send skipped: contact %s is blocked",conversation.contact.id);return False
    if not service_window_open(conversation):logger.warning("Flow send skipped: conversation %s is outside the 24-hour service window",conversation.id);return False
    return True

async def _send_flow_text(db,conversation,text):
    text=render_whatsapp(db,conversation,text).strip()
    if not text or not _can_send(conversation):return
    phone=conversation.phone_number
    if not phone.access_token:raise RuntimeError("WhatsApp phone number has no access token")
    response=await send_text_message(phone.phone_number_id,phone.access_token,conversation.contact.wa_id,text);mid=(response.get("messages") or [{}])[0].get("id");now=datetime.utcnow();db.add(Message(conversation_id=conversation.id,meta_message_id=mid,direction=MessageDirection.OUTBOUND,message_type="text",body=text,payload_json=json.dumps(response,ensure_ascii=False),status=MessageStatus.SENT,created_at=now));conversation.last_message_at=now;db.flush()

async def _send_flow_media(db,conversation,media_type,config):
    media=render_whatsapp(db,conversation,config.get("media") or config.get("media_url") or config.get("url") or config.get("file_id") or "").strip();caption=render_whatsapp(db,conversation,config.get("caption") or config.get("text") or "").strip();filename=render_whatsapp(db,conversation,config.get("filename") or "").strip()
    if not media:logger.warning("WhatsApp %s flow block has no media URL/ID",media_type);return
    if not _can_send(conversation):return
    phone=conversation.phone_number
    if not phone.access_token:raise RuntimeError("WhatsApp phone number has no access token")
    response=await send_media_message(phone.phone_number_id,phone.access_token,conversation.contact.wa_id,media_type,media,caption or None,filename or None);mid=(response.get("messages") or [{}])[0].get("id");now=datetime.utcnow();kind="document" if media_type=="file" else media_type;db.add(Message(conversation_id=conversation.id,meta_message_id=mid,direction=MessageDirection.OUTBOUND,message_type=kind,body=caption or None,payload_json=json.dumps(response,ensure_ascii=False),status=MessageStatus.SENT,created_at=now));conversation.last_message_at=now;db.flush()

async def _capture_reply(db,conversation,node,inbound):
    config=_json(node.config_json)
    if node.node_type!=FlowNodeType.QUESTION:return True
    valid,value,error=_validate_reply(config,inbound)
    if not valid:await _send_flow_text(db,conversation,error or "Please try again.");return False
    field_id=config.get("capture_field_id") or config.get("save_reply_field_id") or config.get("field_id")
    if field_id:_set_contact_field_value(db,conversation,int(field_id),value)
    return True

async def _execute_action(db,conversation,action_type,config):
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
        if field_id:_set_contact_field_value(db,conversation,int(field_id),render_whatsapp(db,conversation,config.get("value")))
        return
    if action_type=="assign_user":
        uid=config.get("user_id")
        if uid in (None,"",0,"0"):conversation.assigned_user_id=None
        else:
            user=db.scalar(select(User).where(User.id==int(uid),User.active.is_(True)))
            if user:conversation.assigned_user_id=user.id
        db.flush();return
    if action_type=="set_status":
        if config.get("status"):conversation.status=ConversationStatus(config["status"]);db.flush()
        return
    if action_type=="delay":logger.info("Visual flow delay node skipped until scheduled resume support is implemented")

def _compare(actual,expected,operator):
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

def _condition_result(db,conversation,config):
    field=str(config.get("field") or "service_window");op=str(config.get("operator") or "open");expected=str(config.get("value") or "").strip()
    if field=="service_window":return service_window_open(conversation) if op in {"open","equals"} else not service_window_open(conversation) if op in {"closed","not_equals"} else False
    if field=="conversation_status":return _compare(conversation.status.value,expected,op)
    if field=="assigned_user":return _compare("" if conversation.assigned_user_id is None else str(conversation.assigned_user_id),expected,op)
    if field=="tag":
        names=set(db.scalars(select(ContactTag.name).join(ContactTagLink,ContactTagLink.tag_id==ContactTag.id).where(ContactTagLink.contact_id==conversation.contact_id)).all())
        if op=="empty":return not names
        if op=="not_empty":return bool(names)
        matched=any(n.casefold()==expected.casefold() for n in names);return not matched if op in {"not_equals","not_contains"} else matched
    if field=="custom_field":
        key=str(config.get("field_key") or config.get("key") or expected).strip();compare=str(config.get("compare_value") if "compare_value" in config else ("" if key==expected else expected)).strip();row=db.execute(select(ContactFieldValue.value_text).join(ContactFieldDefinition,ContactFieldDefinition.id==ContactFieldValue.field_id).where(ContactFieldValue.contact_id==conversation.contact_id,ContactFieldDefinition.key==key)).first();return _compare((row[0] if row else "") or "",compare,op)
    return False

def _graph(db,flow_id):
    nodes=db.scalars(select(FlowNode).where(FlowNode.flow_id==flow_id)).all();edges=db.scalars(select(FlowEdge).where(FlowEdge.flow_id==flow_id).order_by(FlowEdge.sort_order,FlowEdge.id)).all();by_id={n.id:n for n in nodes};out={}
    for e in edges:out.setdefault(e.source_node_id,[]).append(e)
    return nodes,by_id,out

def _next_node(by_id,out,node_id,handle="next"):
    edges=[e for e in out.get(node_id,[]) if e.source_handle==handle];return by_id.get(edges[0].target_node_id) if edges else None

async def _run_graph(db,flow,conversation,session,start_node=None):
    nodes,by_id,out=_graph(db,flow.id);current=start_node or next((n for n in nodes if n.node_type==FlowNodeType.TRIGGER),None)
    if not current:return False
    visited=0
    while current and visited<100:
        visited+=1;session.current_node_id=current.id;session.status=FlowSessionStatus.ACTIVE;session.waiting_for=None;db.flush();config=_json(current.config_json);handle="next"
        if current.node_type==FlowNodeType.CONDITION:handle="yes" if _condition_result(db,conversation,config) else "no"
        elif current.node_type!=FlowNodeType.TRIGGER:
            await _execute_action(db,conversation,current.node_type.value,config)
            if current.node_type in {FlowNodeType.QUESTION,FlowNodeType.INTERACTIVE}:session.status=FlowSessionStatus.WAITING;session.waiting_for="reply";db.flush();return True
        current=_next_node(by_id,out,current.id,handle)
    if visited>=100:raise RuntimeError("Flow graph exceeded 100 nodes; possible loop detected")
    _finish_session(session);return True

async def _resume_waiting_session(db,conversation,inbound,session):
    flow=db.get(Flow,session.flow_id)
    if not flow or flow.status!=FlowStatus.ACTIVE:_finish_session(session,FlowSessionStatus.RESET);return False
    nodes,by_id,out=_graph(db,flow.id);waiting=by_id.get(session.current_node_id)
    if not waiting:_finish_session(session,FlowSessionStatus.FAILED);return False
    if not await _capture_reply(db,conversation,waiting,inbound):session.last_inbound_message_id=inbound.id;session.status=FlowSessionStatus.WAITING;session.waiting_for="reply";session.updated_at=datetime.utcnow();db.flush();return True
    session.last_inbound_message_id=inbound.id;session.status=FlowSessionStatus.ACTIVE;session.waiting_for=None;next_node=_next_node(by_id,out,waiting.id,"next")
    if not next_node:_finish_session(session);return True
    return await _run_graph(db,flow,conversation,session,next_node)

async def run_flows_for_inbound(db,conversation,inbound):
    existing=_session_for_conversation(db,conversation.id)
    if existing and existing.status==FlowSessionStatus.WAITING:
        try:
            if await _resume_waiting_session(db,conversation,inbound,existing):db.commit();return 1
        except (WhatsAppError,RuntimeError,ValueError):db.rollback();raise
    executed=0
    for flow in _matching_flows(db,conversation,inbound):
        try:
            session=_start_session(db,conversation,flow,inbound)
            if await _run_graph(db,flow,conversation,session):db.commit();executed+=1;continue
            for step in sorted(flow.steps,key=lambda x:x.sort_order):await _execute_action(db,conversation,step.step_type.value,_json(step.config_json))
            _finish_session(session);db.commit();executed+=1
        except (WhatsAppError,RuntimeError,ValueError):db.rollback();raise
    return executed
