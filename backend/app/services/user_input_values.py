import json,re
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.campaign_models import Campaign
from app.user_input_models import UserInputAnswer,UserInputSubmission

def latest_input_answer(db:Session,conversation_id:int,channel:str,answer_key:str)->str:
    key=str(answer_key or '').strip()
    if not key:return ''
    submission=db.scalar(select(UserInputSubmission).where(UserInputSubmission.conversation_id==conversation_id,UserInputSubmission.channel==channel).order_by(UserInputSubmission.id.desc()))
    if not submission:return ''
    answer=db.scalar(select(UserInputAnswer.value_text).where(UserInputAnswer.submission_id==submission.id,UserInputAnswer.answer_key==key).order_by(UserInputAnswer.id.desc()))
    return str(answer or '')

def _slug(value):return re.sub(r'[^a-z0-9]+','_',str(value or '').casefold()).strip('_')

def latest_campaign_answers(db:Session,conversation_id:int,channel:str,campaign_slug:str|None=None)->str:
    stmt=select(UserInputSubmission).where(UserInputSubmission.conversation_id==conversation_id,UserInputSubmission.channel==channel,UserInputSubmission.campaign_id.is_not(None))
    rows=db.scalars(stmt.order_by(UserInputSubmission.id.desc())).all()
    submission=None
    for row in rows:
        if not campaign_slug:submission=row;break
        campaign=db.get(Campaign,row.campaign_id)
        if campaign and _slug(campaign.name)==_slug(campaign_slug):submission=row;break
    if not submission:return '[]'
    answers=db.scalars(select(UserInputAnswer).where(UserInputAnswer.submission_id==submission.id).order_by(UserInputAnswer.id)).all()
    result=[]
    for answer in answers:
        reply_type=None
        if answer.campaign_question_id:
            from app.campaign_models import CampaignQuestion
            question=db.get(CampaignQuestion,answer.campaign_question_id);reply_type=question.reply_type if question else None
        result.append({'key':answer.answer_key,'question':answer.question_text,'type':reply_type,'answer':answer.value_text})
    return json.dumps(result,ensure_ascii=False,separators=(',',':'))
