from sqlalchemy import select
from sqlalchemy.orm import Session
from app.user_input_models import UserInputAnswer,UserInputSubmission

def latest_input_answer(db:Session,conversation_id:int,channel:str,answer_key:str)->str:
    key=str(answer_key or '').strip()
    if not key:return ''
    submission=db.scalar(select(UserInputSubmission).where(UserInputSubmission.conversation_id==conversation_id,UserInputSubmission.channel==channel).order_by(UserInputSubmission.id.desc()))
    if not submission:return ''
    answer=db.scalar(select(UserInputAnswer.value_text).where(UserInputAnswer.submission_id==submission.id,UserInputAnswer.answer_key==key).order_by(UserInputAnswer.id.desc()))
    return str(answer or '')
