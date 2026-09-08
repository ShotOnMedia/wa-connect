import json,re
from datetime import datetime
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import func,select
from sqlalchemy.orm import Session,selectinload
from app.campaign_models import Campaign,CampaignQuestion
from app.core.database import get_db
from app.core.security import require_manager

router=APIRouter(prefix="/campaigns",tags=["Campaigns"],dependencies=[Depends(require_manager)])

class CampaignIn(BaseModel):
    name:str=Field(min_length=1,max_length=150);description:str|None=None;status:str="draft";channel_scope:str="both"
class QuestionIn(BaseModel):
    question_text:str=Field(min_length=1);title:str|None=None;answer_key:str|None=None;reply_type:str="text";required:bool=True;capture_field_id:int|None=None;config:dict=Field(default_factory=dict)
class OrderIn(BaseModel):question_ids:list[int]

def _key(value):return re.sub(r"[^a-z0-9_.-]+","_",str(value or "").casefold()).strip("_")[:120]
def _q(row):
    try:cfg=json.loads(row.config_json or "{}")
    except Exception:cfg={}
    return {"id":row.id,"sort_order":row.sort_order,"title":row.title,"question_text":row.question_text,"answer_key":row.answer_key,"reply_type":row.reply_type,"required":row.required,"capture_field_id":row.capture_field_id,"config":cfg}
def _c(row,detail=False):
    data={"id":row.id,"name":row.name,"description":row.description,"status":row.status,"channel_scope":row.channel_scope,"question_count":len(row.questions) if hasattr(row,"questions") else 0,"created_at":row.created_at,"updated_at":row.updated_at}
    if detail:data["questions"]=[_q(q) for q in row.questions]
    return data
def _campaign(db,user,cid):
    row=db.scalar(select(Campaign).options(selectinload(Campaign.questions)).where(Campaign.id==cid,Campaign.workspace_id==user.workspace_id))
    if not row:raise HTTPException(404,"Campaign not found")
    return row

@router.get("")
def list_campaigns(db:Session=Depends(get_db),user=Depends(require_manager)):
    rows=db.scalars(select(Campaign).options(selectinload(Campaign.questions)).where(Campaign.workspace_id==user.workspace_id).order_by(Campaign.name)).all();return [_c(r) for r in rows]
@router.post("")
def create_campaign(body:CampaignIn,db:Session=Depends(get_db),user=Depends(require_manager)):
    if db.scalar(select(Campaign.id).where(Campaign.workspace_id==user.workspace_id,func.lower(Campaign.name)==body.name.strip().lower())):raise HTTPException(409,"A campaign with this name already exists")
    row=Campaign(workspace_id=user.workspace_id,name=body.name.strip(),description=body.description,status=body.status,channel_scope=body.channel_scope,created_by_user_id=user.id);db.add(row);db.commit();return _c(_campaign(db,user,row.id),True)
@router.get("/{campaign_id}")
def get_campaign(campaign_id:int,db:Session=Depends(get_db),user=Depends(require_manager)):return _c(_campaign(db,user,campaign_id),True)
@router.patch("/{campaign_id}")
def update_campaign(campaign_id:int,body:CampaignIn,db:Session=Depends(get_db),user=Depends(require_manager)):
    row=_campaign(db,user,campaign_id);row.name=body.name.strip();row.description=body.description;row.status=body.status;row.channel_scope=body.channel_scope;row.updated_at=datetime.utcnow();db.commit();return _c(_campaign(db,user,campaign_id),True)
@router.delete("/{campaign_id}",status_code=204)
def delete_campaign(campaign_id:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    row=_campaign(db,user,campaign_id);db.delete(row);db.commit()
@router.post("/{campaign_id}/questions")
def add_question(campaign_id:int,body:QuestionIn,db:Session=Depends(get_db),user=Depends(require_manager)):
    row=_campaign(db,user,campaign_id);order=(db.scalar(select(func.max(CampaignQuestion.sort_order)).where(CampaignQuestion.campaign_id==row.id)) or 0)+1;key=_key(body.answer_key or body.title or body.question_text) or f"question_{order}";cfg={**body.config,"text":body.question_text,"answer_key":key,"reply_type":body.reply_type,"required":body.required,"capture_field_id":body.capture_field_id};q=CampaignQuestion(campaign_id=row.id,sort_order=order,title=body.title,question_text=body.question_text,answer_key=key,reply_type=body.reply_type,required=body.required,capture_field_id=body.capture_field_id,config_json=json.dumps(cfg));db.add(q);db.commit();db.refresh(q);return _q(q)
@router.patch("/{campaign_id}/questions/{question_id}")
def update_question(campaign_id:int,question_id:int,body:QuestionIn,db:Session=Depends(get_db),user=Depends(require_manager)):
    row=_campaign(db,user,campaign_id);q=db.scalar(select(CampaignQuestion).where(CampaignQuestion.id==question_id,CampaignQuestion.campaign_id==row.id));
    if not q:raise HTTPException(404,"Question not found")
    key=_key(body.answer_key or body.title or body.question_text) or f"question_{q.sort_order}";cfg={**body.config,"text":body.question_text,"answer_key":key,"reply_type":body.reply_type,"required":body.required,"capture_field_id":body.capture_field_id};q.title=body.title;q.question_text=body.question_text;q.answer_key=key;q.reply_type=body.reply_type;q.required=body.required;q.capture_field_id=body.capture_field_id;q.config_json=json.dumps(cfg);q.updated_at=datetime.utcnow();db.commit();db.refresh(q);return _q(q)
@router.delete("/{campaign_id}/questions/{question_id}",status_code=204)
def delete_question(campaign_id:int,question_id:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    row=_campaign(db,user,campaign_id);q=db.scalar(select(CampaignQuestion).where(CampaignQuestion.id==question_id,CampaignQuestion.campaign_id==row.id));
    if not q:raise HTTPException(404,"Question not found")
    db.delete(q);db.commit();remaining=db.scalars(select(CampaignQuestion).where(CampaignQuestion.campaign_id==row.id).order_by(CampaignQuestion.sort_order)).all();
    for i,item in enumerate(remaining,1):item.sort_order=i
    db.commit()
@router.post("/{campaign_id}/questions-order")
def reorder(campaign_id:int,body:OrderIn,db:Session=Depends(get_db),user=Depends(require_manager)):
    row=_campaign(db,user,campaign_id);items=db.scalars(select(CampaignQuestion).where(CampaignQuestion.campaign_id==row.id)).all();by={q.id:q for q in items}
    if set(body.question_ids)!=set(by):raise HTTPException(400,"question_ids must contain every campaign question exactly once")
    for i,qid in enumerate(body.question_ids,1):by[qid].sort_order=-i
    db.flush()
    for i,qid in enumerate(body.question_ids,1):by[qid].sort_order=i
    db.commit();return [_q(q) for q in sorted(items,key=lambda x:x.sort_order)]
