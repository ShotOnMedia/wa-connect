import json,logging,re
from datetime import datetime
from sqlalchemy import func,select
from sqlalchemy.orm import Session
from app.flow_channel_models import FlowChannelTarget,TelegramFlowSession
from app.flow_models import Flow,FlowEdge,FlowNode,FlowNodeType,FlowStatus,FlowTriggerType
from app.http_api_models import HttpApi
from app.models import ContactFieldDefinition
from app.services.dynamic_lists import build_dynamic_rows,save_dynamic_selection
from app.services.flow_delay import schedule_delay
from app.services.flow_tracking import complete as track_complete,event as track_event,fail as track_fail,latest_open_run,start_run
from app.services.http_api_executor import execute_http_api
from app.services.telegram import TelegramError,request_location,send_buttons,send_location,send_media,send_product_card,send_text
from app.services.telegram_flow_actions import assign_user,change_tag,condition_result,set_field,set_status
from app.services.user_input import active_submission,campaign_for_submission,complete_submission,record_answer,start_submission
from app.telegram_models import TelegramContactFieldValue,TelegramConversation,TelegramMessage
logger=logging.getLogger(__name__)
def _json(v):
    if isinstance(v,dict):return v
    try:return json.loads(v or '{}')
    except:return {}
def _enum(v):return getattr(v,'value',v)
def _is(n,t):return _enum(n.node_type)==t.value
def _session(db,cid):return db.scalar(select(TelegramFlowSession).where(TelegramFlowSession.conversation_id==cid))
def _keyword(a,b):return bool(a and b and a.strip().casefold()==b.strip().casefold())
def _matching_flows(db,c,i):
    fs=db.scalars(select(Flow).join(FlowChannelTarget,FlowChannelTarget.flow_id==Flow.id).where(Flow.workspace_id==c.workspace_id,Flow.status==FlowStatus.ACTIVE,FlowChannelTarget.channel=='telegram').order_by(Flow.id)).all();count=db.scalar(select(func.count(TelegramMessage.id)).where(TelegramMessage.conversation_id==c.id,TelegramMessage.direction=='inbound')) or 0;return[f for f in fs if (_enum(f.trigger_type)==FlowTriggerType.KEYWORD.value and _keyword(f.trigger_value,i.body)) or (_enum(f.trigger_type)==FlowTriggerType.FIRST_MESSAGE.value and count==1)]
def _graph(db,fid):
    ns=db.scalars(select(FlowNode).where(FlowNode.flow_id==fid)).all();es=db.scalars(select(FlowEdge).where(FlowEdge.flow_id==fid).order_by(FlowEdge.sort_order,FlowEdge.id)).all();by={n.id:n for n in ns};out={}
    for e in es:out.setdefault(e.source_node_id,[]).append(e)
    return ns,by,out
def _next(by,out,nid,h='next'):
    es=[e for e in out.get(nid,[]) if e.source_handle==h];return by.get(es[0].target_node_id) if es else None
def _choices(by,out,nid,h):return[by[e.target_node_id] for e in out.get(nid,[]) if e.source_handle==h and e.target_node_id in by and _enum(by[e.target_node_id].node_type)==FlowNodeType.BUTTON.value]
def _render(db,c,text):
    value=str(text or '');keys=set(re.findall(r'%([A-Za-z0-9_.-]+)%',value))
    if not keys:return value
    rows=db.execute(select(ContactFieldDefinition.key,TelegramContactFieldValue.value_text).outerjoin(TelegramContactFieldValue,(TelegramContactFieldValue.field_id==ContactFieldDefinition.id)&(TelegramContactFieldValue.contact_id==c.contact_id)).where(ContactFieldDefinition.workspace_id==c.workspace_id,ContactFieldDefinition.key.in_(keys))).all();vals={str(k):(v or '') for k,v in rows};return re.sub(r'%([A-Za-z0-9_.-]+)%',lambda m:str(vals.get(m.group(1),'')),value)
def _store(db,c,r,kind,body=None):
    ts=datetime.utcfromtimestamp(r['date']) if r.get('date') else datetime.utcnow();db.add(TelegramMessage(conversation_id=c.id,telegram_message_id=int(r['message_id']),direction='outbound',message_type=kind,body=body,payload_json=json.dumps(r,ensure_ascii=False),status='sent',telegram_timestamp=ts));c.last_message_at=ts;db.flush()
async def _send(db,c,text):
    text=_render(db,c,text).strip()
    if text:r=await send_text(c.bot.access_token,c.chat_id,text);_store(db,c,r,'text',r.get('text') or text)
async def _media(db,c,k,cfg):
    m=_render(db,c,cfg.get('media') or cfg.get('media_url') or cfg.get('url') or cfg.get('file_id') or '').strip();cap=_render(db,c,cfg.get('caption') or cfg.get('text') or '').strip()
    if m:r=await send_media(c.bot.access_token,c.chat_id,k,m,cap or None);_store(db,c,r,k,r.get('caption') or cap or None)
async def _location(db,c,cfg):
    lat=float(_render(db,c,cfg.get('latitude') or '').strip());lng=float(_render(db,c,cfg.get('longitude') or '').strip());r=await send_location(c.bot.access_token,c.chat_id,lat,lng);_store(db,c,r,'location',f'{lat},{lng}')
async def _request_location(db,c,cfg):
    text=_render(db,c,cfg.get('text') or 'Please share your current location.').strip();button=_render(db,c,cfg.get('location_button_text') or 'Share location').strip();r=await request_location(c.bot.access_token,c.chat_id,text,button);_store(db,c,r,'location_request',text)
async def _commerce(db,c,cfg):
    name=_render(db,c,cfg.get('product_name') or 'Product').strip() or 'Product';r=await send_product_card(c.bot.access_token,c.chat_id,name,_render(db,c,cfg.get('product_description')).strip(),_render(db,c,cfg.get('product_price')).strip(),_render(db,c,cfg.get('product_currency')).strip(),_render(db,c,cfg.get('product_image')).strip(),_render(db,c,cfg.get('product_url')).strip(),_render(db,c,cfg.get('product_button_text') or 'View product').strip());_store(db,c,r,'commerce',r.get('caption') or r.get('text') or name)
async def _http(db,c,cfg):
    aid=cfg.get('http_api_id')
    if not aid:return False
    api=db.get(HttpApi,int(aid))
    if not api or not api.active:return False
    result=await execute_http_api(db,api,lambda v:_render(db,c,v),channel='telegram',workspace_id=c.workspace_id,contact_id=c.contact_id,apply_mappings=True)
    return bool(result.get('success'))
async def _interactive(db,c,n,by,out,cfg):
    text=_render(db,c,cfg.get('text') or 'Choose an option').strip();ln=_choices(by,out,n.id,'list_messages');bn=_choices(by,out,n.id,'buttons');buttons=[]
    if str(cfg.get('row_generation') or 'static').lower()=='dynamic':
        for row in build_dynamic_rows(db,'telegram',c.workspace_id,c.contact_id,cfg,10):buttons.append({'label':row['label'],'id':n.id,'value':f'wfdyn:{n.id}:{row["index"]}'})
    elif ln:
        template=next((x for x in ln if str(_json(x.config_json).get('row_generation') or 'static').lower()=='dynamic'),None)
        if template:
            tc=_json(template.config_json);rows=build_dynamic_rows(db,'telegram',c.workspace_id,c.contact_id,tc,10)
            for row in rows:buttons.append({'label':row['label'],'id':template.id,'value':f'wfdyn:{template.id}:{row["index"]}'})
        else:
            for x in ln[:10]:
                q=_json(x.config_json);buttons.append({'label':_render(db,c,q.get('label') or x.title or 'Option').strip(),'id':x.id,'value':f'wfbtn:{x.id}'})
    else:
        for x in bn:
            q=_json(x.config_json);item={'label':_render(db,c,q.get('label') or x.title or 'Option').strip(),'id':x.id,'value':f'wfbtn:{x.id}'}
            if q.get('action')=='url' and q.get('action_value'):item['url']=_render(db,c,q['action_value']).strip()
            buttons.append(item)
    if not buttons:await _send(db,c,text);return False
    r=await send_buttons(c.bot.access_token,c.chat_id,text,buttons);_store(db,c,r,'interactive',text);return any(not b.get('url') for b in buttons)
def _validate(cfg,i):
    typ=str(cfg.get('reply_type') or 'text').lower();actual=str(i.message_type or 'text').lower();err=str(cfg.get('validation_error') or '').strip();expected={'image':'photo','photo':'photo','audio':'audio','voice':'voice','video':'video','document':'document','file':'document','sticker':'sticker'}
    if typ in expected:
        ok=actual in ({'audio','voice'} if typ in {'audio','voice'} else {expected[typ]});return (True,i.body or actual,None) if ok else (False,None,err or f'Please reply with a {typ}.')
    if actual!='text':return False,None,err or 'Please reply with text.'
    v=str(i.body or '').strip()
    if cfg.get('required',True) is not False and not v:return False,None,err or 'Please enter a reply.'
    if typ=='email' and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',v):return False,None,err or 'Please enter a valid email address.'
    if typ in {'number','integer','decimal'}:
        try:num=float(v.replace(',','.'))
        except:return False,None,err or 'Please enter a valid number.'
        if typ=='integer' and not num.is_integer():return False,None,err or 'Please enter a whole number.'
        v=str(int(num)) if typ=='integer' else str(num)
    return True,v,None
async def _run_from(db,f,c,i,s,n,by,out):
    safety=0
    while n and safety<100:
        safety+=1;s.current_node_id=n.id;s.status='active';s.waiting_for=None;s.updated_at=datetime.utcnow();cfg=_json(n.config_json);k=_enum(n.node_type)
        if k==FlowNodeType.SEND_MESSAGE.value:await _send(db,c,cfg.get('text'));n=_next(by,out,n.id);continue
        if k in {'image','video','audio','file'}:await _media(db,c,k,cfg);n=_next(by,out,n.id);continue
        if k==FlowNodeType.LOCATION.value:await _location(db,c,cfg);n=_next(by,out,n.id);continue
        if k==FlowNodeType.REQUEST_LOCATION.value:await _request_location(db,c,cfg);s.status='waiting';s.waiting_for='location';db.flush();return True
        if k==FlowNodeType.USER_INPUT_FLOW.value:start_submission(db,f,c,n,'telegram',cfg);n=_next(by,out,n.id);continue
        if k==FlowNodeType.COMMERCE.value:await _commerce(db,c,cfg);n=_next(by,out,n.id);continue
        if k==FlowNodeType.HTTP_REQUEST.value:n=_next(by,out,n.id,'success' if await _http(db,c,cfg) else 'error');continue
        if k==FlowNodeType.QUESTION.value:await _send(db,c,cfg.get('text'));s.status='waiting';s.waiting_for='reply';db.flush();return True
        if k==FlowNodeType.INTERACTIVE.value:
            ec=_next(by,out,n.id,'ecommerce')
            if ec and _enum(ec.node_type)==FlowNodeType.COMMERCE.value:n=ec;continue
            if await _interactive(db,c,n,by,out,cfg):s.status='waiting';s.waiting_for='button';db.flush();return True
            n=_next(by,out,n.id);continue
        if k==FlowNodeType.BUTTON.value:
            if cfg.get('action')=='send_message' and cfg.get('action_value'):await _send(db,c,cfg['action_value'])
            n=_next(by,out,n.id);continue
        if k==FlowNodeType.ADD_TAG.value:
            if cfg.get('tag_id'):change_tag(db,c,int(cfg['tag_id']),True)
        elif k==FlowNodeType.REMOVE_TAG.value:
            if cfg.get('tag_id'):change_tag(db,c,int(cfg['tag_id']),False)
        elif k==FlowNodeType.SET_FIELD.value:
            if cfg.get('field_id'):set_field(db,c,int(cfg['field_id']),_render(db,c,cfg.get('value')))
        elif k==FlowNodeType.ASSIGN_USER.value:assign_user(db,c,cfg.get('user_id'))
        elif k==FlowNodeType.SET_STATUS.value:set_status(db,c,cfg.get('status'))
        elif k==FlowNodeType.CONDITION.value:n=_next(by,out,n.id,'yes' if condition_result(db,c,cfg) else 'no');continue
        elif k==FlowNodeType.DELAY.value:
            resume=_next(by,out,n.id);schedule_delay(db,'telegram',f.id,c.id,n.id,resume.id if resume else None,cfg);s.status='waiting';s.waiting_for='delay';db.flush();return True
        n=_next(by,out,n.id)
    s.status='completed';s.current_node_id=None;s.waiting_for=None;s.ended_at=datetime.utcnow();db.flush();return True
async def _run_flow(db,f,c,i):
    ns,by,out=_graph(db,f.id);tr=next((n for n in ns if _is(n,FlowNodeType.TRIGGER)),None)
    if not tr:return False
    s=_session(db,c.id) or TelegramFlowSession(conversation_id=c.id,flow_id=f.id);db.add(s);s.flow_id=f.id;s.status='active';s.current_node_id=tr.id;s.waiting_for=None;s.last_inbound_message_id=i.id;s.started_at=datetime.utcnow();s.ended_at=None;db.flush();return await _run_from(db,f,c,i,s,_next(by,out,tr.id),by,out)
async def _resume(db,c,i,s):
    f=db.get(Flow,s.flow_id);ns,by,out=_graph(db,f.id);w=by.get(s.current_node_id);s.last_inbound_message_id=i.id
    if s.waiting_for=='location' and _is(w,FlowNodeType.REQUEST_LOCATION):
        if str(i.message_type or '').lower()!='location':await _send(db,c,'Please use the Share location button to send your current location.');return True
        return await _run_from(db,f,c,i,s,_next(by,out,w.id),by,out)
    if s.waiting_for=='button' and _is(w,FlowNodeType.INTERACTIVE):
        body=str(i.body or '').strip();dm=re.fullmatch(r'wfdyn:(\d+):(\d+)',body)
        if dm:
            owner=by.get(int(dm.group(1)));idx=int(dm.group(2))
            if owner and owner.id==w.id and _is(owner,FlowNodeType.INTERACTIVE):
                cfg=_json(owner.config_json);rows=build_dynamic_rows(db,'telegram',c.workspace_id,c.contact_id,cfg,10)
                if idx>=len(rows):return True
                save_dynamic_selection(db,'telegram',c.workspace_id,c.contact_id,cfg,rows[idx]);return await _run_from(db,f,c,i,s,_next(by,out,w.id),by,out)
            valid={x.id for x in _choices(by,out,w.id,'list_messages')}
            if not owner or owner.id not in valid:return True
            cfg=_json(owner.config_json);rows=build_dynamic_rows(db,'telegram',c.workspace_id,c.contact_id,cfg,10)
            if idx>=len(rows):return True
            save_dynamic_selection(db,'telegram',c.workspace_id,c.contact_id,cfg,rows[idx]);return await _run_from(db,f,c,i,s,owner,by,out)
        m=re.fullmatch(r'wfbtn:(\d+)',body);b=by.get(int(m.group(1))) if m else None;valid={x.id for x in _choices(by,out,w.id,'buttons')+_choices(by,out,w.id,'list_messages')}
        if not b or b.id not in valid:return True
        return await _run_from(db,f,c,i,s,b,by,out)
    if not _is(w,FlowNodeType.QUESTION):return False
    cfg=_json(w.config_json);ok,val,err=_validate(cfg,i)
    if not ok:await _send(db,c,err or 'Please try again.');return True
    if cfg.get('capture_field_id'):set_field(db,c,int(cfg['capture_field_id']),val)
    sub=active_submission(db,f.id,c.id,'telegram')
    if sub:record_answer(db,sub,w,cfg,val)
    handle='thank_you' if _next(by,out,w.id,'thank_you') and not _next(by,out,w.id,'next') else 'next';n=_next(by,out,w.id,handle)
    if handle=='thank_you' and sub:
        _,cc=campaign_for_submission(db,sub);await complete_submission(db,sub,cc)
    if not n:
        if sub:
            _,cc=campaign_for_submission(db,sub);await complete_submission(db,sub,cc)
        s.status='completed';s.current_node_id=None;s.ended_at=datetime.utcnow();db.flush();return True
    return await _run_from(db,f,c,i,s,n,by,out)
def _track(run,s):
    if s.status=='completed':track_complete(run)
    elif s.status=='waiting':track_event(run,'delayed' if s.waiting_for=='delay' else 'waiting',node_id=s.current_node_id,status='waiting',message=f'Waiting for {s.waiting_for}',run_status='waiting')
async def resume_telegram_delay(db:Session,job)->bool:
    c=db.get(TelegramConversation,job.conversation_id);f=db.get(Flow,job.flow_id);s=_session(db,job.conversation_id)
    if not c or not f or not s:return False
    run=latest_open_run(f.id,'telegram',c.id);track_event(run,'resumed',node_id=job.delay_node_id,message='Delay elapsed',run_status='running');ns,by,out=_graph(db,f.id);result=await _run_from(db,f,c,None,s,by.get(job.resume_node_id) if job.resume_node_id else None,by,out);_track(run,s);return result
async def run_telegram_flows_for_inbound(db:Session,conversation:TelegramConversation,inbound:TelegramMessage)->int:
    s=_session(db,conversation.id)
    if s and s.status=='waiting':
        if s.waiting_for=='delay':return 0
        run=latest_open_run(s.flow_id,'telegram',conversation.id)
        try:r=await _resume(db,conversation,inbound,s);_track(run,s);return 1 if r else 0
        except Exception as exc:track_fail(run,exc,s.current_node_id);raise
    done=0
    for f in _matching_flows(db,conversation,inbound):
        run=start_run(f.id,f.workspace_id,'telegram',conversation.id,conversation.contact_id,None)
        try:
            if await _run_flow(db,f,conversation,inbound):s=_session(db,conversation.id);_track(run,s);done+=1
        except Exception as exc:track_fail(run,exc,_session(db,conversation.id).current_node_id if _session(db,conversation.id) else None);logger.exception('Telegram flow execution failed')
    return done