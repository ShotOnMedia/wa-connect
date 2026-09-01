import json
from datetime import datetime
import httpx
from sqlalchemy import select
from app.user_input_models import UserInputAnswer, UserInputSubmission

def start_submission(db,flow,conversation,campaign_node,channel,config):
    row=UserInputSubmission(workspace_id=flow.workspace_id,flow_id=flow.id,campaign_node_id=campaign_node.id,channel=channel,conversation_id=conversation.id,contact_id=conversation.contact_id,status='active',webhook_url=(config.get('webhook_url') or None),started_at=datetime.utcnow());db.add(row);db.flush();return row

def active_submission(db,flow_id,conversation_id,channel):
    return db.scalar(select(UserInputSubmission).where(UserInputSubmission.flow_id==flow_id,UserInputSubmission.conversation_id==conversation_id,UserInputSubmission.channel==channel,UserInputSubmission.status=='active').order_by(UserInputSubmission.id.desc()))

def record_answer(db,submission,question_node,config,value):
    key=str(config.get('answer_key') or config.get('field_key') or f'question_{question_node.id}')[:120]
    row=UserInputAnswer(submission_id=submission.id,question_node_id=question_node.id,answer_key=key,question_text=config.get('text'),value_text=None if value is None else str(value));db.add(row);db.flush();return row

async def complete_submission(db,submission,campaign_config=None):
    if not submission:return
    submission.status='completed';submission.completed_at=datetime.utcnow();db.flush();cfg=campaign_config or {};url=(submission.webhook_url or '').strip()
    if not url or not cfg.get('webhook_enabled'):return
    answers=db.scalars(select(UserInputAnswer).where(UserInputAnswer.submission_id==submission.id).order_by(UserInputAnswer.id)).all();payload={'submission_id':submission.id,'flow_id':submission.flow_id,'channel':submission.channel,'contact_id':submission.contact_id,'conversation_id':submission.conversation_id,'submitted_at':submission.completed_at.isoformat()+'Z','answers':{a.answer_key:a.value_text for a in answers}}
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