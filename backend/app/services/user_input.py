import json
import re
from datetime import datetime
import httpx
from sqlalchemy import select
from app.user_input_models import UserInputAnswer, UserInputSubmission

def start_submission(db,flow,conversation,campaign_node,channel,config):
    row=UserInputSubmission(workspace_id=flow.workspace_id,flow_id=flow.id,campaign_node_id=campaign_node.id,campaign_id=(int(config.get('campaign_id')) if config.get('campaign_id') else None),channel=channel,conversation_id=conversation.id,contact_id=conversation.contact_id,status='active',webhook_url=(config.get('webhook_url') or None),started_at=datetime.utcnow());db.add(row);db.flush();return row

def active_submission(db,flow_id,conversation_id,channel):
    return db.scalar(select(UserInputSubmission).where(UserInputSubmission.flow_id==flow_id,UserInputSubmission.conversation_id==conversation_id,UserInputSubmission.channel==channel,UserInputSubmission.status=='active').order_by(UserInputSubmission.id.desc()))

def _clean_key(value):
    key=re.sub(r'[^a-z0-9_.-]+','_',str(value or '').casefold()).strip('_')
    return key[:120]

def _answer_key(db,question_node,config):
    explicit=_clean_key(config.get('answer_key') or config.get('field_key'))
    if explicit:return explicit
    field_id=config.get('capture_field_id') or config.get('save_reply_field_id')
    if field_id:
        from app.models import ContactFieldDefinition
        field=db.get(ContactFieldDefinition,int(field_id))
        field_key=_clean_key(getattr(field,'key','') if field else '')
        if field_key:return field_key
    title=str(getattr(question_node,'title','') or '').strip()
    if title and title.casefold()!='question':
        key=_clean_key(title)
        if key:return key
    return f'question_{question_node.id}'

def _answer_value(config,value):
    if value is None:return None
    text=str(value)
    if str(config.get('reply_type') or '').lower() in {'image','photo'}:
        try:
            media=json.loads(text)
            if isinstance(media,dict):
                for key in ('wa_connect_url','id','url'):
                    if str(media.get(key) or '').startswith(('http://','https://','/')):return str(media[key])
        except (TypeError,ValueError):pass
    return text

def record_answer(db,submission,question_node,config,value):
    key=_answer_key(db,question_node,config)
    row=UserInputAnswer(submission_id=submission.id,question_node_id=question_node.id,answer_key=key,question_text=config.get('text'),value_text=_answer_value(config,value));db.add(row);db.flush();return row

def record_campaign_answer(db,submission,campaign_question,config,value):
    row=UserInputAnswer(submission_id=submission.id,question_node_id=None,campaign_question_id=campaign_question.id,answer_key=_clean_key(campaign_question.answer_key) or f'question_{campaign_question.sort_order}',question_text=str(config.get('text') or campaign_question.question_text or ''),value_text=_answer_value(config,value));db.add(row);db.flush();return row

def submission_answer_array(db,submission):
    rows=db.scalars(select(UserInputAnswer).where(UserInputAnswer.submission_id==submission.id).order_by(UserInputAnswer.id)).all()
    result=[]
    for answer in rows:
        reply_type=None
        if answer.campaign_question_id:
            from app.campaign_models import CampaignQuestion
            question=db.get(CampaignQuestion,answer.campaign_question_id);reply_type=question.reply_type if question else None
        result.append({'key':answer.answer_key,'question':answer.question_text,'type':reply_type,'answer':answer.value_text})
    return result

async def complete_submission(db,submission,campaign_config=None):
    if not submission:return
    submission.status='completed';submission.completed_at=datetime.utcnow();db.flush();cfg=campaign_config or {};url=(submission.webhook_url or '').strip()
    if not url or not cfg.get('webhook_enabled'):return
    answers=db.scalars(select(UserInputAnswer).where(UserInputAnswer.submission_id==submission.id).order_by(UserInputAnswer.id)).all();payload={'submission_id':submission.id,'flow_id':submission.flow_id,'campaign_id':submission.campaign_id,'channel':submission.channel,'contact_id':submission.contact_id,'conversation_id':submission.conversation_id,'submitted_at':submission.completed_at.isoformat()+'Z','answers':{a.answer_key:a.value_text for a in answers},'question_answers':submission_answer_array(db,submission)}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:r=await client.post(url,json=payload);r.raise_for_status()
    except httpx.HTTPError as exc:
        submission.status='webhook_error';db.flush();raise RuntimeError(f'User input webhook failed: {exc}') from exc

def campaign_for_submission(db,submission):
    if not submission:return None,{}
    from app.flow_models import FlowNode
    node=db.get(FlowNode,submission.campaign_node_id)
    if not node:return None,{}
    try:cfg=json.loads(node.config_json or '{}')
    except (TypeError,json.JSONDecodeError):cfg={}
    return node,cfg