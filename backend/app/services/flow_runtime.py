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
from app.services.whatsapp import WhatsAppError, send_media_message, send_reply_buttons, send_text_message

logger=logging.getLogger(__name__)


def _json(value):
    try:return json.loads(value or "{}")
    except (json.JSONDecodeError,TypeError):return {}


def _match_keyword(expected,body):return bool(expected and body and expected.strip().casefold()==body.strip().casefold())
def _session(db,conversation_id):return db.scalar(select(FlowSession).where(FlowSession.conversation_id==conversation_id))


def _matching_flows(db,conversation,inbound):
    flows=db.scalars(select(Flow).options(selectinload(Flow.steps)).where(Flow.workspace_id==conversation.workspace_id,Flow.status==FlowStatus.ACTIVE).order_by(Flow.id)).all();count=db.scalar(select(func.count(Message.id)).where(Message.conversation_id==conversation.id,Message.direction==MessageDirection.INBOUND)) or 0
    return [f for f in flows if (f.trigger_type==FlowTriggerType.KEYWORD and _match_keyword(f.trigger_value,inbound.body)) or (f.trigger_type==FlowTriggerType.FIRST_MESSAGE and count==1)]


def _start_session(db,conversation,flow,inbound):
    s=_session(db,conversation.id);now=datetime.utcnow()
    if not s:s=FlowSession(conversation_id=conversation.id,flow_id=flow.id);db.add(s)
    s.flow_id=flow.id;s.current_node_id=None;s.status=FlowSessionStatus.ACTIVE;s.waiting_for=None;s.last_inbound_message_id=inbound.id;s.started_at=now;s.updated_at=now;s.ended_at=None;s.reset_by_user_id=None;db.flush();return s


def _finish(s,status=FlowSessionStatus.COMPLETED):s.status=status;s.current_node_id=None;s.waiting_for=None;s.ended_at=datetime.utcnow()


def _set_field(db,conversation,field_id,value):
    field=db.scalar(select(ContactFieldDefinition).where(ContactFieldDefinition.id==int(field_id),ContactFieldDefinition.workspace_id==conversation.workspace_id,ContactFieldDefinition.active.is_(True)))
    if not field:return False
    text=None if value is None else str(value).strip();row=db.scalar(select(ContactFieldValue).where(ContactFieldValue.contact_id==conversation.contact_id,ContactFieldValue.field_id==field.id))
    if row:row.value_text=text;row.updated_at=datetime.utcnow()
    else:db.add(ContactFieldValue(contact_id=conversation.contact_id,field_id=field.id,value_text=text))
    db.flush();return True


def _media_value(message):
    try:payload=json.loads(message.payload_json or "{}")
    except (json.JSONDecodeError,TypeError):payload={}
    kind=message.message_type or "unknown";media=payload.get(kind) or {};value={"type":kind,"id":media.get("id"),"mime_type":media.get("mime_type"),"sha256":media.get("sha256"),"caption":media.get("caption"),"filename":media.get("filename")};return json.dumps({k:v for k,v in value.items() if v is not None},ensure_ascii=False)


def _validate(config,inbound):
    reply_type=str(config.get("reply_type") or config.get("input_type") or "text").strip().lower();actual=(inbound.message_type or "text").strip().lower();err=str(config.get("validation_error") or "").strip();expected={"photo":"image","image":"image","audio":"audio","voice":"audio","video":"video","document":"document","file":"document","sticker":"sticker"};labels={"image":"photo","audio":"audio/voice note","video":"video","document":"document","sticker":"sticker"}
    if reply_type in expected:
        kind=expected[reply_type]
        if actual!=kind:return False,None,err or f"Please reply with a {labels[kind]}."
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
            num=float(value.replace(",","."));
            if reply_type=="integer" and not num.is_integer():raise ValueError
        except ValueError:return False,None,err or ("Please enter a whole number." if reply_type=="integer" else "Please enter a valid number.")
        lo,hi=config.get("min_value"),config.get("max_value")
        if lo not in (None,"") and num<float(lo):return False,None,err or f"Please enter a value of at least {lo}."
        if hi not in (None,"") and num>float(hi):return False,None,err or f"Please enter a value no greater than {hi}."
        return True,str(int(num)) if reply_type=="integer" else str(num),None
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
    if conversation.contact.blocked_at:return False
    if not service_window_open(conversation):return False
    return True


def _store_outbound(db,conversation,response,kind,body=None):
    mid=(response.get("messages") or [{}])[0].get("id");now=datetime.utcnow();db.add(Message(conversation_id=conversation.id,meta_message_id=mid,direction=MessageDirection.OUTBOUND,message_type=kind,body=body,payload_json=json.dumps(response,ensure_ascii=False),status=MessageStatus.SENT,created_at=now));conversation.last_message_at=now;db.flush()


async def _send_text(db,conversation,text):
    text=render_whatsapp(db,conversation,text).strip()
    if not text or not _can_send(conversation):return
    phone=conversation.phone_number
    if not phone.access_token:raise RuntimeError("WhatsApp phone number has no access token")
    response=await send_text_message(phone.phone_number_id,phone.access_token,conversation.contact.wa_id,text);_store_outbound(db,conversation,response,"text",text)


async def _send_media(db,conversation,kind,config):
    media=render_whatsapp(db,conversation,config.get("media") or config.get("media_url") or config.get("url") or config.get("file_id") or "").strip();caption=render_whatsapp(db,conversation,config.get("caption") or config.get("text") or "").strip();filename=render_whatsapp(db,conversation,config.get("filename") or "").strip()
    if not media or not _can_send(conversation):return
    phone=conversation.phone_number
    if not phone.access_token:raise RuntimeError("WhatsApp phone number has no access token")
    response=await send_media_message(phone.phone_number_id,phone.access_token,conversation.contact.wa_id,kind,media,caption or None,filename or None);_store_outbound(db,conversation,response,"document" if kind=="file" else kind,caption or None)


def _graph(db,flow_id):
    nodes=db.scalars(select(FlowNode).where(FlowNode.flow_id==flow_id)).all();edges=db.scalars(select(FlowEdge).where(FlowEdge.flow_id==flow_id).order_by(FlowEdge.sort_order,FlowEdge.id)).all();by_id={n.id:n for n in nodes};out={}
    for e in edges:out.setdefault(e.source_node_id,[]).append(e)
    return nodes,by_id,out


def _next(by_id,out,node_id,handle="next"):
    edges=[e for e in out.get(node_id,[]) if e.source_handle==handle];return by_id.get(edges[0].target_node_id) if edges else None


def _button_nodes(by_id,out,interactive_id):
    nodes=[]
    for e in out.get(interactive_id,[]):
        if e.source_handle!="buttons":continue
        n=by_id.get(e.target_node_id)
        if n and n.node_type==FlowNodeType.BUTTON:nodes.append(n)
    return nodes[:3]


async def _send_interactive(db,conversation,node,by_id,out,config):
    if not _can_send(conversation):return False
    text=render_whatsapp(db,conversation,config.get("text") or "Choose an option").strip() or "Choose an option";buttons=[]
    for n in _button_nodes(by_id,out,node.id):
        cfg=_json(n.config_json);label=render_whatsapp(db,conversation,cfg.get("label") or n.title or "Button").strip();buttons.append({"label":label,"value":f"wfbtn:{n.id}"})
    if not buttons:await _send_text(db,conversation,text);return False
    phone=conversation.phone_number
    if not phone.access_token:raise RuntimeError("WhatsApp phone number has no access token")
    response=await send_reply_buttons(phone.phone_number_id,phone.access_token,conversation.contact.wa_id,text,buttons);_store_outbound(db,conversation,response,"interactive",text);return True


async def _action(db,conversation,kind,config):
    contact=conversation.contact
    if kind in {"send_message","question"}:await _send_text(db,conversation,config.get("text"));return
    if kind in {"image","video","audio","file"}:await _send_media(db,conversation,kind,config);return
    if kind in {"add_tag","remove_tag"}:
        tid=config.get("tag_id")
        if not tid:return
        tag=db.scalar(select(ContactTag).where(ContactTag.id==int(tid),ContactTag.workspace_id==conversation.workspace_id))
        if not tag:return
        link=db.scalar(select(ContactTagLink).where(ContactTagLink.contact_id==contact.id,ContactTagLink.tag_id==tag.id))
        if kind=="add_tag" and not link:db.add(ContactTagLink(contact_id=contact.id,tag_id=tag.id))
        elif kind=="remove_tag" and link:db.delete(link)
        db.flush();return
    if kind=="set_field":
        if config.get("field_id"):_set_field(db,conversation,int(config["field_id"]),render_whatsapp(db,conversation,config.get("value")))
        return
    if kind=="assign_user":
        uid=config.get("user_id")
        if uid in (None,"",0,"0"):conversation.assigned_user_id=None
        else:
            user=db.scalar(select(User).where(User.id==int(uid),User.active.is_(True)))
            if user:conversation.assigned_user_id=user.id
        db.flush();return
    if kind=="set_status":
        if config.get("status"):conversation.status=ConversationStatus(config["status"]);db.flush()
        return
    if kind=="delay":logger.info("Visual flow delay node skipped until scheduled resume support is implemented")


def _compare(actual,expected,op):
    a=str(actual or "").strip();e=str(expected or "").strip()
    if op in {"equals","open"}:return a.casefold()==e.casefold()
    if op in {"not_equals","closed"}:return a.casefold()!=e.casefold()
    if op=="contains":return e.casefold() in a.casefold()
    if op=="not_contains":return e.casefold() not in a.casefold()
    if op=="starts_with":return a.casefold().startswith(e.casefold())
    if op=="ends_with":return a.casefold().endswith(e.casefold())
    if op=="empty":return not a
    if op=="not_empty":return bool(a)
    return False


def _condition(db,conversation,config):
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


async def _run(db,flow,conversation,session,start=None):
    nodes,by_id,out=_graph(db,flow.id);current=start or next((n for n in nodes if n.node_type==FlowNodeType.TRIGGER),None)
    if not current:return False
    visited=0
    while current and visited<100:
        visited+=1;session.current_node_id=current.id;session.status=FlowSessionStatus.ACTIVE;session.waiting_for=None;db.flush();cfg=_json(current.config_json);kind=current.node_type
        if kind==FlowNodeType.CONDITION:current=_next(by_id,out,current.id,"yes" if _condition(db,conversation,cfg) else "no");continue
        if kind==FlowNodeType.INTERACTIVE:
            waits=await _send_interactive(db,conversation,current,by_id,out,cfg)
            if waits:session.status=FlowSessionStatus.WAITING;session.waiting_for="button";db.flush();return True
            current=_next(by_id,out,current.id);continue
        if kind==FlowNodeType.BUTTON:
            action=str(cfg.get("action") or "next")
            if action in {"send_message","url"} and cfg.get("action_value"):await _send_text(db,conversation,cfg.get("action_value"))
            elif action=="start_flow":logger.info("Button start_flow action is not implemented yet")
            current=_next(by_id,out,current.id);continue
        if kind!=FlowNodeType.TRIGGER:
            await _action(db,conversation,kind.value,cfg)
            if kind==FlowNodeType.QUESTION:session.status=FlowSessionStatus.WAITING;session.waiting_for="reply";db.flush();return True
        current=_next(by_id,out,current.id)
    if visited>=100:raise RuntimeError("Flow graph exceeded 100 nodes; possible loop detected")
    _finish(session);return True


async def _resume(db,conversation,inbound,session):
    flow=db.get(Flow,session.flow_id)
    if not flow or flow.status!=FlowStatus.ACTIVE:_finish(session,FlowSessionStatus.RESET);return False
    nodes,by_id,out=_graph(db,flow.id);waiting=by_id.get(session.current_node_id)
    if not waiting:_finish(session,FlowSessionStatus.FAILED);return False
    session.last_inbound_message_id=inbound.id;session.updated_at=datetime.utcnow()
    if session.waiting_for=="button" and waiting.node_type==FlowNodeType.INTERACTIVE:
        match=re.fullmatch(r"wfbtn:(\d+)",str(inbound.body or "").strip());button=by_id.get(int(match.group(1))) if match else None;valid={n.id for n in _button_nodes(by_id,out,waiting.id)}
        if not button or button.id not in valid:session.status=FlowSessionStatus.WAITING;session.waiting_for="button";db.flush();return True
        session.status=FlowSessionStatus.ACTIVE;session.waiting_for=None;return await _run(db,flow,conversation,session,button)
    if waiting.node_type!=FlowNodeType.QUESTION:_finish(session,FlowSessionStatus.FAILED);return False
    cfg=_json(waiting.config_json);valid,value,error=_validate(cfg,inbound)
    if not valid:session.status=FlowSessionStatus.WAITING;session.waiting_for="reply";await _send_text(db,conversation,error or "Please try again.");db.flush();return True
    fid=cfg.get("capture_field_id") or cfg.get("save_reply_field_id") or cfg.get("field_id")
    if fid:_set_field(db,conversation,int(fid),value)
    session.status=FlowSessionStatus.ACTIVE;session.waiting_for=None;next_node=_next(by_id,out,waiting.id)
    if not next_node:_finish(session);return True
    return await _run(db,flow,conversation,session,next_node)


async def run_flows_for_inbound(db:Session,conversation:Conversation,inbound:Message)->int:
    existing=_session(db,conversation.id)
    if existing and existing.status==FlowSessionStatus.WAITING:
        try:
            if await _resume(db,conversation,inbound,existing):db.commit();return 1
        except (WhatsAppError,RuntimeError,ValueError):db.rollback();raise
    executed=0
    for flow in _matching_flows(db,conversation,inbound):
        try:
            session=_start_session(db,conversation,flow,inbound)
            if await _run(db,flow,conversation,session):db.commit();executed+=1
        except (WhatsAppError,RuntimeError,ValueError):db.rollback();raise
    return executed
