import json
from datetime import datetime,UTC
from fastapi import APIRouter,Depends,HTTPException,Response
from pydantic import BaseModel,Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import require_manager
from app.campaign_engine_models import MessagingCampaign,MessagingCampaignStep
from app.models import Workspace,WhatsAppAccount,WhatsAppPhoneNumber
from app.telegram_models import TelegramBot

router=APIRouter(prefix="/messaging-campaigns",tags=["Messaging Campaigns"],dependencies=[Depends(require_manager)])
def now():return datetime.now(UTC).replace(tzinfo=None)

class CampaignIn(BaseModel):
    name:str=Field(min_length=1,max_length=150);channel:str;channel_account_id:int;description:str|None=None
    audience_type:str="all";audience_filter:dict|None=None;audience_segment_id:int|None=None;scheduled_at:datetime|None=None
class StepIn(BaseModel):
    name:str=Field(min_length=1,max_length=150);delay_seconds:int=Field(default=0,ge=0,max=2592000)
    message_mode:str="freeform";message_text:str=Field(min_length=1,max_length=4096);provider_template:dict|None=None
    parse_mode:str="HTML";media_url:str|None=None;media_type:str|None=None

def workspace_for(db,channel,account_id):
    if channel=="telegram":
        wid=db.scalar(select(TelegramBot.workspace_id).where(TelegramBot.id==account_id))
    elif channel=="whatsapp":
        wid=db.scalar(select(WhatsAppAccount.workspace_id).join(WhatsAppPhoneNumber,WhatsAppPhoneNumber.whatsapp_account_id==WhatsAppAccount.id).where(WhatsAppPhoneNumber.id==account_id))
    else:raise HTTPException(400,"channel must be whatsapp or telegram")
    if wid is None:raise HTTPException(404,"Channel account not found")
    return wid
def step_out(s):return {"id":s.id,"position":s.position,"name":s.name,"delay_seconds":s.delay_seconds,"message_mode":s.message_mode,"message_text":s.message_text,"provider_template":json.loads(s.provider_template_json) if s.provider_template_json else None,"parse_mode":s.parse_mode,"media_url":s.media_url,"media_type":s.media_type,"created_at":s.created_at,"updated_at":s.updated_at}
def out(c,detail=False):
    data={"id":c.id,"name":c.name,"description":c.description,"channel":c.channel,"channel_account_id":c.channel_account_id,"status":c.status,"audience_type":c.audience_type,"audience_filter":json.loads(c.audience_filter_json) if c.audience_filter_json else None,"audience_segment_id":c.audience_segment_id,"scheduled_at":c.scheduled_at,"started_at":c.started_at,"completed_at":c.completed_at,"step_count":len(c.steps),"created_at":c.created_at,"updated_at":c.updated_at}
    if detail:data["steps"]=[step_out(x) for x in c.steps]
    return data
def get(db,cid):
    c=db.get(MessagingCampaign,cid)
    if not c:raise HTTPException(404,"Campaign not found")
    return c

@router.get("")
def listing(channel:str|None=None,db:Session=Depends(get_db),user=Depends(require_manager)):
    q=select(MessagingCampaign)
    if channel:q=q.where(MessagingCampaign.channel==channel)
    return [out(x) for x in db.scalars(q.order_by(MessagingCampaign.updated_at.desc())).all()]
@router.post("")
def create(body:CampaignIn,db:Session=Depends(get_db),user=Depends(require_manager)):
    wid=workspace_for(db,body.channel,body.channel_account_id)
    c=MessagingCampaign(workspace_id=wid,channel=body.channel,channel_account_id=body.channel_account_id,name=body.name.strip(),description=body.description,audience_type=body.audience_type,audience_filter_json=json.dumps(body.audience_filter) if body.audience_filter else None,audience_segment_id=body.audience_segment_id,scheduled_at=body.scheduled_at,created_by_user_id=user.id,created_at=now(),updated_at=now())
    db.add(c);db.commit();db.refresh(c);return out(c,True)
@router.get("/{cid}")
def detail(cid:int,db:Session=Depends(get_db),user=Depends(require_manager)):return out(get(db,cid),True)
@router.put("/{cid}")
def update(cid:int,body:CampaignIn,db:Session=Depends(get_db),user=Depends(require_manager)):
    c=get(db,cid)
    if c.status!="draft":raise HTTPException(409,"Only draft campaigns can be edited")
    wid=workspace_for(db,body.channel,body.channel_account_id)
    c.workspace_id=wid;c.channel=body.channel;c.channel_account_id=body.channel_account_id;c.name=body.name.strip();c.description=body.description;c.audience_type=body.audience_type;c.audience_filter_json=json.dumps(body.audience_filter) if body.audience_filter else None;c.audience_segment_id=body.audience_segment_id;c.scheduled_at=body.scheduled_at;c.updated_at=now()
    db.commit();db.refresh(c);return out(c,True)
@router.delete("/{cid}",status_code=204)
def delete(cid:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    c=get(db,cid)
    if c.status!="draft":raise HTTPException(409,"Only draft campaigns can be deleted")
    db.delete(c);db.commit();return Response(status_code=204)
@router.post("/{cid}/steps")
def add_step(cid:int,body:StepIn,db:Session=Depends(get_db),user=Depends(require_manager)):
    c=get(db,cid)
    if c.status!="draft":raise HTTPException(409,"Only draft campaigns can be edited")
    position=max([x.position for x in c.steps],default=0)+1
    s=MessagingCampaignStep(campaign_id=c.id,position=position,name=body.name.strip(),delay_seconds=body.delay_seconds,message_mode=body.message_mode,message_text=body.message_text,provider_template_json=json.dumps(body.provider_template) if body.provider_template else None,parse_mode=body.parse_mode,media_url=body.media_url,media_type=body.media_type,created_at=now(),updated_at=now())
    db.add(s);db.commit();db.refresh(s);return step_out(s)
@router.put("/{cid}/steps/{sid}")
def update_step(cid:int,sid:int,body:StepIn,db:Session=Depends(get_db),user=Depends(require_manager)):
    c=get(db,cid);s=db.get(MessagingCampaignStep,sid)
    if c.status!="draft":raise HTTPException(409,"Only draft campaigns can be edited")
    if not s or s.campaign_id!=c.id:raise HTTPException(404,"Campaign step not found")
    s.name=body.name.strip();s.delay_seconds=body.delay_seconds;s.message_mode=body.message_mode;s.message_text=body.message_text;s.provider_template_json=json.dumps(body.provider_template) if body.provider_template else None;s.parse_mode=body.parse_mode;s.media_url=body.media_url;s.media_type=body.media_type;s.updated_at=now();db.commit();db.refresh(s);return step_out(s)
@router.delete("/{cid}/steps/{sid}",status_code=204)
def delete_step(cid:int,sid:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    c=get(db,cid);s=db.get(MessagingCampaignStep,sid)
    if c.status!="draft":raise HTTPException(409,"Only draft campaigns can be edited")
    if not s or s.campaign_id!=c.id:raise HTTPException(404,"Campaign step not found")
    pos=s.position;db.delete(s);db.flush()
    for x in db.scalars(select(MessagingCampaignStep).where(MessagingCampaignStep.campaign_id==cid,MessagingCampaignStep.position>pos).order_by(MessagingCampaignStep.position)).all():x.position-=1
    db.commit();return Response(status_code=204)
@router.post("/{cid}/steps/{sid}/move")
def move_step(cid:int,sid:int,direction:str,db:Session=Depends(get_db),user=Depends(require_manager)):
    c=get(db,cid);s=db.get(MessagingCampaignStep,sid)
    if c.status!="draft":raise HTTPException(409,"Only draft campaigns can be edited")
    if not s or s.campaign_id!=cid:raise HTTPException(404,"Campaign step not found")
    target=s.position+(-1 if direction=="up" else 1 if direction=="down" else 0)
    other=db.scalar(select(MessagingCampaignStep).where(MessagingCampaignStep.campaign_id==cid,MessagingCampaignStep.position==target))
    if other:
        tmp=-s.id;s.position=tmp;db.flush();other.position=s.position if False else (target+1 if direction=="up" else target-1);db.flush();s.position=target;db.commit()
    return out(c,True)
