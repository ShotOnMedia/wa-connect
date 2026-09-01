import json
import logging
import re
from datetime import datetime
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.flow_channel_models import FlowChannelTarget, TelegramFlowSession
from app.flow_models import Flow, FlowEdge, FlowNode, FlowNodeType, FlowStatus, FlowTriggerType
from app.models import ContactFieldDefinition
from app.services.flow_delay import schedule_delay
from app.services.flow_tracking import complete as track_complete, event as track_event, fail as track_fail, latest_open_run, start_run
from app.services.telegram import TelegramError, send_buttons, send_location, send_media, send_product_card, send_text
from app.services.telegram_flow_actions import assign_user, change_tag, condition_result, set_field, set_status
from app.telegram_models import TelegramContactFieldValue, TelegramConversation, TelegramMessage

logger=logging.getLogger(__name__)
def _json(value):
    if isinstance(value,dict):return value
    try:return json.loads(value or "{}")
    except (json.JSONDecodeError,TypeError):return {}
def _enum(value):return getattr(value,"value",value)
def _is(node,expected):return _enum(node.node_type)==expected.value
def _session(db,conversation_id):return db.scalar(select(TelegramFlowSession).where(TelegramFlowSession.conversation_id==conversation_id))
def _keyword(expected,body):return bool(expected and body and expected.strip().casefold()==body.strip().casefold())
def _matching_flows(db,conversation,inbound):
    flows=db.scalars(select(Flow).join(FlowChannelTarget,FlowChannelTarget.flow_id==Flow.id).where(Flow.workspace_id==conversation.workspace_id,Flow.status==FlowStatus.ACTIVE,FlowChannelTarget.channel=="telegram").order_by(Flow.id)).all();count=db.scalar(select(func.count(TelegramMessage.id)).where(TelegramMessage.conversation_id==conversation.id,TelegramMessage.direction=="inbound")) or 0
    return [f for f in flows if (_enum(f.trigger_type)==FlowTriggerType.KEYWORD.value and _keyword(f.trigger_value,inbound.body)) or (_enum(f.trigger_type)==FlowTriggerType.FIRST_MESSAGE.value and count==1)]
def _graph(db,flow_id):
    nodes=db.scalars(select(FlowNode).where(FlowNode.flow_id==flow_id)).all();edges=db.scalars(select(FlowEdge).where(FlowEdge.flow_id==flow_id).order_by(FlowEdge.sort_order,FlowEdge.id)).all();by_id={n.id:n for n in nodes};out={}
    for edge in edges:out.setdefault(edge.source_node_id,[]).append(edge)
    return nodes,by_id,out
def _next(by_id,out,node_id,handle="next"):
    edges=[e for e in out.get(node_id,[]) if e.source_handle==handle];return by_id.get(edges[0].target_node_id) if edges else None
def _choice_nodes(by_id,out,interactive_id,handle):
    result=[]
    for edge in out.get(interactive_id,[]):
        if edge.source_handle!=handle:continue
        node=by_id.get(edge.target_node_id)
        if node and _enum(node.node_type)==FlowNodeType.BUTTON.value:result.append(node)
    return result
def _all_choices(by_id,out,interactive_id):return _choice_nodes(by_id,out,interactive_id,"buttons")+_choice_nodes(by_id,out,interactive_id,"list_messages")
def _render(db,conversation,text):
    value=str(text or "");keys=set(re.findall(r"%([A-Za-z0-9_.-]+)%",value))
    if not keys:return value
    rows=db.execute(select(ContactFieldDefinition.key,TelegramContactFieldValue.value_text).outerjoin(TelegramContactFieldValue,(TelegramContactFieldValue.field_id==ContactFieldDefinition.id)&(TelegramContactFieldValue.contact_id==conversation.contact_id)).where(ContactFieldDefinition.workspace_id==conversation.workspace_id,ContactFieldDefinition.key.in_(keys))).all();values={str(k):(v or "") for k,v in rows}
    return re.sub(r"%([A-Za-z0-9_.-]+)%",lambda m:str(values.get(m.group(1),"")),value)
def _store_outbound(db,conversation,result,message_type,body=None):
    ts=datetime.utcfromtimestamp(result["date"]) if result.get("date") else datetime.utcnow();db.add(TelegramMessage(conversation_id=conversation.id,telegram_message_id=int(result["message_id"]),direction="outbound",message_type=message_type,body=body,payload_json=json.dumps(result,ensure_ascii=False),status="sent",telegram_timestamp=ts));conversation.last_message_at=ts;db.flush()
async def _send(db,conversation,text):
    text=_render(db,conversation,text).strip()
    if not text:return
    result=await send_text(conversation.bot.access_token,conversation.chat_id,text);_store_outbound(db,conversation,result,"text",result.get("text") or text)
async def _send_media(db,conversation,kind,config):
    media=_render(db,conversation,config.get("media") or config.get("media_url") or config.get("url") or config.get("file_id") or "").strip();caption=_render(db,conversation,config.get("caption") or config.get("text") or "").strip()
    if not media:logger.warning("Telegram %s flow block has no media URL/file_id",kind);return
    result=await send_media(conversation.bot.access_token,conversation.chat_id,kind,media,caption or None);_store_outbound(db,conversation,result,kind,result.get("caption") or caption or None)
async def _send_location(db,conversation,config):
    latitude=_render(db,conversation,config.get("latitude") or "").strip();longitude=_render(db,conversation,config.get("longitude") or "").strip()
    if not latitude or not longitude:raise RuntimeError("Location block requires latitude and longitude")
    try:lat=float(latitude);lng=float(longitude)
    except ValueError as exc:raise RuntimeError("Location latitude/longitude must resolve to numeric values") from exc
    if not -90<=lat<=90 or not -180<=lng<=180:raise RuntimeError("Location coordinates are outside the valid latitude/longitude range")
    result=await send_location(conversation.bot.access_token,conversation.chat_id,lat,lng);_store_outbound(db,conversation,result,"location",f"{lat},{lng}")
async def _send_commerce(db,conversation,config):
    name=_render(db,conversation,config.get("product_name") or "Product").strip() or "Product";description=_render(db,conversation,config.get("product_description") or "").strip();price=_render(db,conversation,config.get("product_price") or "").strip();currency=_render(db,conversation,config.get("product_currency") or "").strip();image=_render(db,conversation,config.get("product_image") or "").strip();url=_render(db,conversation,config.get("product_url") or "").strip();button=_render(db,conversation,config.get("product_button_text") or "View product").strip() or "View product";result=await send_product_card(conversation.bot.access_token,conversation.chat_id,name,description,price,currency,image,url,button);_store_outbound(db,conversation,result,"commerce",result.get("caption") or result.get("text") or name)
async def _send_interactive(db,flow,conversation,node,by_id,out,config):
    text=_render(db,conversation,config.get("text") or "Choose an option").strip() or "Choose an option";list_nodes=_choice_nodes(by_id,out,node.id,"list_messages");button_nodes=_choice_nodes(by_id,out,node.id,"buttons");nodes=(list_nodes[:10] if list_nodes else button_nodes);buttons=[]
    for button_node in nodes:
        cfg=_json(button_node.config_json);action=str(cfg.get("action") or "next");label=_render(db,conversation,cfg.get("label") or button_node.title or "Option").strip();item={"label":label,"id":button_node.id,"value":f"wfbtn:{button_node.id}"}
        if not list_nodes and action=="url" and cfg.get("action_value"):item["url"]=_render(db,conversation,cfg.get("action_value")).strip()
        buttons.append(item)
    if not buttons:logger.warning("Telegram interactive node %s has no connected choice blocks",node.id);await _send(db,conversation,text);return False
    result=await send_buttons(conversation.bot.access_token,conversation.chat_id,text,buttons);_store_outbound(db,conversation,result,"interactive",text);return any(not b.get("url") for b in buttons)
def _validate(config,inbound):
    reply_type=str(config.get("reply_type") or config.get("input_type") or "text").strip().lower();actual=str(inbound.message_type or "text").strip().lower();err=str(config.get("validation_error") or "").strip();expected={"photo":"photo","image":"photo","audio":"audio","voice":"voice","video":"video","document":"document","file":"document","sticker":"sticker"}
    if reply_type in expected:
        accepted={expected[reply_type]};accepted={"audio","voice"} if reply_type in {"audio","voice"} else accepted
        return (True,inbound.body or actual,None) if actual in accepted else (False,None,err or f"Please reply with a {reply_type}.")
    if actual!="text":return False,None,err or "Please reply with text."
    value=str(inbound.body or "").strip()
    if config.get("required",True) is not False and not value:return False,None,err or "Please enter a reply."
    if reply_type in {"number","integer","decimal"}:
        try:num=float(value.replace(",","."))
        except ValueError:return False,None,err or "Please enter a valid number."
        if reply_type=="integer" and not num.is_integer():return False,None,err or "Please enter a whole number."
        lo,hi=config.get("min_value"),config.get("max_value")
        if lo not in (None,"") and num<float(lo):return False,None,err or f"Please enter a value of at least {lo}."
        if hi not in (None,"") and num>float(hi):return False,None,err or f"Please enter a value no greater than {hi}."
        return True,str(int(num)) if reply_type=="integer" else str(num),None
    if reply_type=="email" and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",value):return False,None,err or "Please enter a valid email address."
    if reply_type in {"phone","telephone"} and not re.fullmatch(r"\+?\d{7,15}",re.sub(r"[\s().-]","",value)):return False,None,err or "Please enter a valid phone number."
    if reply_type=="date":
        try:datetime.strptime(value,str(config.get("date_format") or "%Y-%m-%d"))
        except ValueError:return False,None,err or "Please enter a valid date."
    lo,hi=config.get("min_length"),config.get("max_length")
    if lo not in (None,"") and len(value)<int(lo):return False,None,err or f"Please enter at least {lo} characters."
    if hi not in (None,"") and len(value)>int(hi):return False,None,err or f"Please enter no more than {hi} characters."
    pattern=str(config.get("pattern") or "").strip()
    if pattern:
        try:
            if not re.fullmatch(pattern,value):return False,None,err or "That reply is not in the expected format."
        except re.error:logger.warning("Invalid Telegram question regex: %s",pattern)
    return True,value,None
async def _run_from(db,flow,conversation,inbound,session,node,by_id,out):
    safety=0
    while node and safety<100:
        safety+=1;session.current_node_id=node.id;session.status="active";session.waiting_for=None;session.updated_at=datetime.utcnow();cfg=_json(node.config_json);kind=_enum(node.node_type)
        if kind==FlowNodeType.SEND_MESSAGE.value:await _send(db,conversation,cfg.get("text"));node=_next(by_id,out,node.id);continue
        if kind in {"image","video","audio","file"}:await _send_media(db,conversation,kind,cfg);node=_next(by_id,out,node.id);continue
        if kind==FlowNodeType.LOCATION.value:await _send_location(db,conversation,cfg);node=_next(by_id,out,node.id);continue
        if kind==FlowNodeType.COMMERCE.value:await _send_commerce(db,conversation,cfg);node=_next(by_id,out,node.id);continue
        if kind==FlowNodeType.QUESTION.value:await _send(db,conversation,cfg.get("text"));session.status="waiting";session.waiting_for="reply";db.flush();return True
        if kind==FlowNodeType.INTERACTIVE.value:
            ecommerce=_next(by_id,out,node.id,"ecommerce")
            if ecommerce and _enum(ecommerce.node_type)==FlowNodeType.COMMERCE.value:node=ecommerce;continue
            if await _send_interactive(db,flow,conversation,node,by_id,out,cfg):session.status="waiting";session.waiting_for="button";db.flush();return True
            node=_next(by_id,out,node.id);continue
        if kind==FlowNodeType.BUTTON.value:
            action=str(cfg.get("action") or "next")
            if action=="send_message" and cfg.get("action_value"):await _send(db,conversation,cfg.get("action_value"))
            node=_next(by_id,out,node.id);continue
        if kind==FlowNodeType.ADD_TAG.value:
            if cfg.get("tag_id"):change_tag(db,conversation,int(cfg["tag_id"]),True)
            node=_next(by_id,out,node.id);continue
        if kind==FlowNodeType.REMOVE_TAG.value:
            if cfg.get("tag_id"):change_tag(db,conversation,int(cfg["tag_id"]),False)
            node=_next(by_id,out,node.id);continue
        if kind==FlowNodeType.SET_FIELD.value:
            fid=cfg.get("field_id") or cfg.get("capture_field_id")
            if fid:set_field(db,conversation,int(fid),_render(db,conversation,cfg.get("value")))
            node=_next(by_id,out,node.id);continue
        if kind==FlowNodeType.ASSIGN_USER.value:assign_user(db,conversation,cfg.get("user_id"));node=_next(by_id,out,node.id);continue
        if kind==FlowNodeType.SET_STATUS.value:set_status(db,conversation,cfg.get("status"));node=_next(by_id,out,node.id);continue
        if kind==FlowNodeType.CONDITION.value:node=_next(by_id,out,node.id,"yes" if condition_result(db,conversation,cfg) else "no");continue
        if kind==FlowNodeType.DELAY.value:
            resume=_next(by_id,out,node.id);schedule_delay(db,"telegram",flow.id,conversation.id,node.id,resume.id if resume else None,cfg);session.status="waiting";session.waiting_for="delay";session.updated_at=datetime.utcnow();db.flush();return True
        logger.info("Telegram flow %s skipping unsupported node type %s",flow.id,kind);node=_next(by_id,out,node.id)
    if safety>=100:raise RuntimeError("Telegram flow graph exceeded 100 nodes; possible loop detected")
    session.status="completed";session.current_node_id=None;session.waiting_for=None;session.ended_at=datetime.utcnow();session.updated_at=datetime.utcnow();db.flush();return True
async def _run_flow(db,flow,conversation,inbound):
    nodes,by_id,out=_graph(db,flow.id);trigger=next((n for n in nodes if _is(n,FlowNodeType.TRIGGER)),None)
    if not trigger:return False
    session=_session(db,conversation.id);now=datetime.utcnow()
    if not session:session=TelegramFlowSession(conversation_id=conversation.id,flow_id=flow.id);db.add(session)
    session.flow_id=flow.id;session.status="active";session.current_node_id=trigger.id;session.waiting_for=None;session.last_inbound_message_id=inbound.id;session.started_at=now;session.updated_at=now;session.ended_at=None;db.flush();return await _run_from(db,flow,conversation,inbound,session,_next(by_id,out,trigger.id),by_id,out)
async def _resume(db,conversation,inbound,session):
    flow=db.get(Flow,session.flow_id);target=db.scalar(select(FlowChannelTarget).where(FlowChannelTarget.flow_id==session.flow_id)) if flow else None
    if not flow or flow.status!=FlowStatus.ACTIVE or not target or target.channel!="telegram" or flow.workspace_id!=conversation.workspace_id:session.status="reset";session.current_node_id=None;session.waiting_for=None;session.ended_at=datetime.utcnow();db.flush();return False
    nodes,by_id,out=_graph(db,flow.id);waiting=by_id.get(session.current_node_id)
    if not waiting:session.status="failed";session.waiting_for=None;session.ended_at=datetime.utcnow();db.flush();return False
    session.last_inbound_message_id=inbound.id;session.updated_at=datetime.utcnow()
    if session.waiting_for=="delay":return False
    if session.waiting_for=="button" and _enum(waiting.node_type)==FlowNodeType.INTERACTIVE.value:
        match=re.fullmatch(r"wfbtn:(\d+)",str(inbound.body or "").strip());button=by_id.get(int(match.group(1))) if match else None;valid_ids={n.id for n in _all_choices(by_id,out,waiting.id)}
        if not button or button.id not in valid_ids:session.status="waiting";session.waiting_for="button";db.flush();return True
        session.status="active";session.waiting_for=None;return await _run_from(db,flow,conversation,inbound,session,button,by_id,out)
    if not _is(waiting,FlowNodeType.QUESTION):session.status="failed";session.waiting_for=None;session.ended_at=datetime.utcnow();db.flush();return False
    cfg=_json(waiting.config_json);valid,value,error=_validate(cfg,inbound)
    if not valid:session.status="waiting";session.waiting_for="reply";await _send(db,conversation,error or "Please try again.");db.flush();return True
    fid=cfg.get("capture_field_id") or cfg.get("save_reply_field_id") or cfg.get("field_id")
    if fid:set_field(db,conversation,int(fid),value)
    session.status="active";session.waiting_for=None;next_node=_next(by_id,out,waiting.id)
    if not next_node:session.status="completed";session.current_node_id=None;session.ended_at=datetime.utcnow();db.flush();return True
    return await _run_from(db,flow,conversation,inbound,session,next_node,by_id,out)
def _track_state(run_id,session):
    if session.status=="completed":track_complete(run_id);return
    if session.status=="waiting":
        state="delayed" if session.waiting_for=="delay" else "waiting";track_event(run_id,state,node_id=session.current_node_id,status=state,message=f"Waiting for {session.waiting_for}",run_status=state)
async def resume_telegram_delay(db:Session,job)->bool:
    conversation=db.get(TelegramConversation,job.conversation_id);flow=db.get(Flow,job.flow_id);session=_session(db,job.conversation_id);target=db.scalar(select(FlowChannelTarget).where(FlowChannelTarget.flow_id==job.flow_id)) if flow else None
    if not conversation or not flow or flow.status!=FlowStatus.ACTIVE or not target or target.channel!="telegram" or not session or session.flow_id!=flow.id:return False
    if session.waiting_for!="delay" or session.current_node_id!=job.delay_node_id:return False
    run_id=latest_open_run(flow.id,"telegram",conversation.id);track_event(run_id,"resumed",node_id=job.delay_node_id,node_type="delay",message="Delay elapsed",run_status="running")
    session.status="active";session.waiting_for=None;session.updated_at=datetime.utcnow()
    try:
        if not job.resume_node_id:session.status="completed";session.current_node_id=None;session.ended_at=datetime.utcnow();db.flush();_track_state(run_id,session);return True
        nodes,by_id,out=_graph(db,flow.id);node=by_id.get(job.resume_node_id)
        if not node:session.status="failed";session.current_node_id=None;session.ended_at=datetime.utcnow();db.flush();raise RuntimeError("Delay resume node no longer exists")
        result=await _run_from(db,flow,conversation,None,session,node,by_id,out);_track_state(run_id,session);return result
    except Exception as exc:track_fail(run_id,exc,session.current_node_id);raise
async def run_telegram_flows_for_inbound(db:Session,conversation:TelegramConversation,inbound:TelegramMessage)->int:
    existing=_session(db,conversation.id)
    if existing and existing.status=="waiting":
        run_id=latest_open_run(existing.flow_id,"telegram",conversation.id)
        try:
            if existing.waiting_for=="delay":return 0
            track_event(run_id,"resumed",node_id=existing.current_node_id,message=f"Received {existing.waiting_for} reply",run_status="running")
            if await _resume(db,conversation,inbound,existing):_track_state(run_id,existing);return 1
        except TelegramError as exc:track_fail(run_id,exc,existing.current_node_id);raise
        except Exception as exc:track_fail(run_id,exc,existing.current_node_id);logger.exception("Telegram flow resume failed flow=%s conversation=%s",existing.flow_id,conversation.id);raise
    executed=0
    for flow in _matching_flows(db,conversation,inbound):
        run_id=None
        try:
            run_id=start_run(flow.id,flow.workspace_id,"telegram",conversation.id,conversation.contact_id,None)
            if await _run_flow(db,flow,conversation,inbound):
                session=_session(db,conversation.id);_track_state(run_id,session);executed+=1
        except TelegramError as exc:track_fail(run_id,exc,_session(db,conversation.id).current_node_id if _session(db,conversation.id) else None);raise
        except Exception as exc:
            session=_session(db,conversation.id);track_fail(run_id,exc,session.current_node_id if session else None);logger.exception("Telegram flow execution failed flow=%s conversation=%s",flow.id,conversation.id)
    return executed