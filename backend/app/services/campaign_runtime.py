import json
import logging
from sqlalchemy import select

from app.campaign_models import Campaign, CampaignQuestion
from app.flow_models import FlowNodeType, FlowSessionStatus
from app.services.user_input import active_submission, complete_submission, record_campaign_answer
from app.user_input_models import UserInputAnswer

logger = logging.getLogger(__name__)


class _CampaignPause(Exception):
    def __init__(self, submission, node, config):
        self.submission=submission;self.node=node;self.config=config


def _question_config(question):
    try:cfg=json.loads(question.config_json or '{}')
    except (TypeError,ValueError):cfg={}
    cfg={**cfg,'text':question.question_text,'answer_key':question.answer_key,'reply_type':question.reply_type,'required':question.required,'capture_field_id':question.capture_field_id}
    choices=cfg.get('choices')
    if choices and not cfg.get('pattern'):cfg['pattern']=json.dumps(choices,ensure_ascii=False)
    return cfg


def _questions(db,campaign_id):
    return db.scalars(select(CampaignQuestion).where(CampaignQuestion.campaign_id==campaign_id).order_by(CampaignQuestion.sort_order,CampaignQuestion.id)).all()


def _next_question(db,submission):
    answered=set(db.scalars(select(UserInputAnswer.campaign_question_id).where(UserInputAnswer.submission_id==submission.id,UserInputAnswer.campaign_question_id.is_not(None))).all())
    return next((q for q in _questions(db,submission.campaign_id) if q.id not in answered),None)


def _durable_image(inbound,channel):
    try:payload=json.loads(inbound.payload_json or '{}')
    except (TypeError,ValueError):return None
    if channel=='telegram':
        photos=(payload.get('message') or {}).get('photo') or [];item=photos[-1] if photos else {}
    else:item=payload.get('image') or {}
    value=str((item or {}).get('wa_connect_url') or '')
    return value or None


def _campaign_ok(db,submission,channel):
    campaign=db.get(Campaign,submission.campaign_id) if submission and submission.campaign_id else None
    if not campaign:raise RuntimeError('Selected Campaign no longer exists')
    if campaign.status!='active':raise RuntimeError(f'Campaign “{campaign.name}” is not active')
    if campaign.channel_scope not in {'both',channel}:raise RuntimeError(f'Campaign “{campaign.name}” is not enabled for {channel}')
    return campaign


def _resolve_campaign(db,flow,conversation,config):
    campaign_id=config.get('campaign_id')
    if campaign_id:
        campaign=db.get(Campaign,int(campaign_id))
        if campaign:return campaign
        raise RuntimeError(f'Selected Campaign id {campaign_id} no longer exists')

    name=str(config.get('campaign_name') or '').strip()
    if not name:return None

    # Telegram flows can intentionally execute for a conversation whose workspace
    # differs from the workspace historically stored on the Flow. Campaigns belong
    # to the messaging workspace, so prefer the live conversation workspace first.
    workspace_ids=[]
    for value in (getattr(conversation,'workspace_id',None),getattr(flow,'workspace_id',None)):
        if value is not None and value not in workspace_ids:workspace_ids.append(value)
    for workspace_id in workspace_ids:
        campaign=db.scalar(select(Campaign).where(Campaign.workspace_id==workspace_id,Campaign.name==name))
        if campaign:
            logger.info('Resolved Campaign %s id=%s via workspace=%s flow=%s conversation=%s',name,campaign.id,workspace_id,flow.id,conversation.id)
            return campaign

    # Current WA Connect installs are effectively single-tenant. If workspace
    # history has drifted, allow a globally unique campaign name rather than
    # silently treating the User Input Flow as a campaign-less block.
    matches=db.scalars(select(Campaign).where(Campaign.name==name).order_by(Campaign.id)).all()
    if len(matches)==1:
        campaign=matches[0]
        logger.warning('Resolved Campaign %s id=%s by unique-name fallback; flow workspace=%s conversation workspace=%s',name,campaign.id,getattr(flow,'workspace_id',None),getattr(conversation,'workspace_id',None))
        return campaign
    if len(matches)>1:raise RuntimeError(f'Campaign “{name}” is ambiguous across workspaces; save the flow again so it stores campaign_id')
    raise RuntimeError(f'Selected Campaign “{name}” could not be found')


async def _send_wa_question(wa,db,conversation,question):
    from app.services.question_choices import choices
    from app.services.whatsapp import send_list_message,send_reply_buttons
    cfg=_question_config(question);text=wa.render_whatsapp(db,conversation,cfg.get('text') or 'Please answer the question.').strip() or 'Please answer the question.';opts=choices(cfg)
    if opts and wa._can_send(conversation):
        phone=conversation.phone_number
        if len(opts)<=3:response=await send_reply_buttons(phone.phone_number_id,phone.access_token,conversation.contact.wa_id,text,opts)
        else:response=await send_list_message(phone.phone_number_id,phone.access_token,conversation.contact.wa_id,text,[{'label':o['label'],'value':o['value']} for o in opts],'Choose','Options')
        wa._store_outbound(db,conversation,response,'interactive',text);return
    await wa._send_text(db,conversation,text)


async def _send_tg_question(tg,db,conversation,question):
    from app.services.question_choices import choices
    from app.services.telegram import request_phone_number,send_buttons
    cfg=_question_config(question);text=tg._render(db,conversation,cfg.get('text') or 'Please answer the question.').strip() or 'Please answer the question.'
    if str(cfg.get('reply_type') or '').lower()=='telegram_phone':
        response=await request_phone_number(conversation.bot.access_token,conversation.chat_id,text,str(cfg.get('telegram_phone_button_text') or 'Share phone number'));tg._store(db,conversation,response,'phone_request',text);return
    opts=choices(cfg)
    if opts:
        response=await send_buttons(conversation.bot.access_token,conversation.chat_id,text,[{'label':o['label'],'value':o['value']} for o in opts]);tg._store(db,conversation,response,'interactive',text);return
    await tg._send(db,conversation,text)


async def _finish_wa(wa,db,flow,conversation,session,node,submission,config):
    await complete_submission(db,submission,config)
    thanks=str(config.get('thank_you_text') or '').strip()
    if thanks:await wa._send_text(db,conversation,thanks)
    nodes,by_id,out=wa._graph(db,flow.id);next_node=wa._next(by_id,out,node.id);session.status=FlowSessionStatus.ACTIVE;session.waiting_for=None
    if not next_node:wa._finish(session);db.flush();return True
    return await wa._run(db,flow,conversation,session,next_node)


async def _finish_tg(tg,db,flow,conversation,inbound,session,node,submission,config):
    await complete_submission(db,submission,config)
    thanks=str(config.get('thank_you_text') or '').strip()
    if thanks:await tg._send(db,conversation,thanks)
    nodes,by_id,out=tg._graph(db,flow.id);next_node=tg._next(by_id,out,node.id);session.status='active';session.waiting_for=None
    if not next_node:
        session.status='completed';session.current_node_id=None;session.ended_at=tg.datetime.utcnow();db.flush();return True
    return await tg._run_from(db,flow,conversation,inbound,session,next_node,by_id,out)


def install():
    from app.services import flow_runtime as wa
    from app.services import telegram_flow_runtime as tg
    if getattr(wa,'_campaign_runtime_installed',False):return

    wa_start=wa.start_submission;tg_start=tg.start_submission;wa_run=wa._run;tg_run=tg._run_from;wa_resume=wa._resume;tg_resume=tg._resume

    def start_with_campaign(original,db,flow,conversation,node,channel,config):
        campaign=_resolve_campaign(db,flow,conversation,config)
        submission=original(db,flow,conversation,node,channel,config)
        if campaign:
            submission.campaign_id=int(campaign.id);db.flush();_campaign_ok(db,submission,channel);raise _CampaignPause(submission,node,config)
        return submission

    wa.start_submission=lambda db,flow,conversation,node,channel,config:start_with_campaign(wa_start,db,flow,conversation,node,channel,config)
    tg.start_submission=lambda db,flow,conversation,node,channel,config:start_with_campaign(tg_start,db,flow,conversation,node,channel,config)

    async def wa_run_campaign(db,flow,conversation,session,start=None):
        try:return await wa_run(db,flow,conversation,session,start)
        except _CampaignPause as pause:
            question=_next_question(db,pause.submission)
            if not question:return await _finish_wa(wa,db,flow,conversation,session,pause.node,pause.submission,pause.config)
            session.current_node_id=pause.node.id;session.status=FlowSessionStatus.WAITING;session.waiting_for='campaign';await _send_wa_question(wa,db,conversation,question);db.flush();return True

    async def tg_run_campaign(db,flow,conversation,inbound,session,node,by_id,out):
        try:return await tg_run(db,flow,conversation,inbound,session,node,by_id,out)
        except _CampaignPause as pause:
            question=_next_question(db,pause.submission)
            if not question:return await _finish_tg(tg,db,flow,conversation,inbound,session,pause.node,pause.submission,pause.config)
            session.current_node_id=pause.node.id;session.status='waiting';session.waiting_for='campaign';await _send_tg_question(tg,db,conversation,question);db.flush();return True

    wa._run=wa_run_campaign;tg._run_from=tg_run_campaign

    async def wa_resume_campaign(db,conversation,inbound,session):
        if session.waiting_for!='campaign':return await wa_resume(db,conversation,inbound,session)
        flow=db.get(wa.Flow,session.flow_id);node=db.get(wa.FlowNode,session.current_node_id)
        if not flow or not node or node.node_type!=FlowNodeType.USER_INPUT_FLOW:return await wa_resume(db,conversation,inbound,session)
        submission=active_submission(db,flow.id,conversation.id,'whatsapp');_campaign_ok(db,submission,'whatsapp');question=_next_question(db,submission)
        if not question:return await _finish_wa(wa,db,flow,conversation,session,node,submission,wa._json(node.config_json))
        cfg=_question_config(question);valid,value,error=wa._validate(cfg,inbound)
        if str(cfg.get('reply_type') or '').lower() in {'image','photo'}:value=_durable_image(inbound,'whatsapp') or value
        if not valid:await wa._send_text(db,conversation,error or 'Please try again.');session.status=FlowSessionStatus.WAITING;session.waiting_for='campaign';db.flush();return True
        if cfg.get('capture_field_id'):wa._set_field(db,conversation,int(cfg['capture_field_id']),value)
        record_campaign_answer(db,submission,question,cfg,value);next_question=_next_question(db,submission)
        if next_question:session.status=FlowSessionStatus.WAITING;session.waiting_for='campaign';await _send_wa_question(wa,db,conversation,next_question);db.flush();return True
        return await _finish_wa(wa,db,flow,conversation,session,node,submission,wa._json(node.config_json))

    async def tg_resume_campaign(db,conversation,inbound,session):
        if session.waiting_for!='campaign':return await tg_resume(db,conversation,inbound,session)
        flow=db.get(tg.Flow,session.flow_id);node=db.get(tg.FlowNode,session.current_node_id)
        if not flow or not node or not tg._is(node,FlowNodeType.USER_INPUT_FLOW):return await tg_resume(db,conversation,inbound,session)
        submission=active_submission(db,flow.id,conversation.id,'telegram');_campaign_ok(db,submission,'telegram');question=_next_question(db,submission)
        if not question:return await _finish_tg(tg,db,flow,conversation,inbound,session,node,submission,tg._json(node.config_json))
        cfg=_question_config(question);valid,value,error=tg._validate(cfg,inbound)
        if str(cfg.get('reply_type') or '').lower() in {'image','photo'}:value=_durable_image(inbound,'telegram') or value
        if not valid:await tg._send(db,conversation,error or 'Please try again.');session.status='waiting';session.waiting_for='campaign';db.flush();return True
        if cfg.get('capture_field_id'):tg.set_field(db,conversation,int(cfg['capture_field_id']),value)
        record_campaign_answer(db,submission,question,cfg,value);next_question=_next_question(db,submission)
        if next_question:session.status='waiting';session.waiting_for='campaign';await _send_tg_question(tg,db,conversation,next_question);db.flush();return True
        return await _finish_tg(tg,db,flow,conversation,inbound,session,node,submission,tg._json(node.config_json))

    wa._resume=wa_resume_campaign;tg._resume=tg_resume_campaign;wa._campaign_runtime_installed=True;tg._campaign_runtime_installed=True
