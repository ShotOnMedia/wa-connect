from datetime import datetime
from fastapi import APIRouter,Depends,HTTPException,Response
from pydantic import BaseModel,Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import require_manager
from app.models import BroadcastTemplate,Workspace

router=APIRouter(prefix="/broadcast-templates",tags=["Broadcast Templates"],dependencies=[Depends(require_manager)])
class TemplateIn(BaseModel):
    name:str=Field(min_length=1,max_length=150);channel:str="telegram";message_text:str=Field(min_length=1,max_length=4096);parse_mode:str="HTML";media_url:str|None=None;media_type:str|None=None;stagger_seconds:float=Field(default=0.05,ge=0.05,le=60)
def active_workspace(db):
    wid=db.scalar(select(Workspace.id).where(Workspace.active.is_(True)).order_by(Workspace.id))
    if wid is None:raise HTTPException(400,"No active workspace")
    return int(wid)
def output(row):
    return {"id":row.id,"name":row.name,"channel":row.channel,"message_text":row.message_text,"parse_mode":row.parse_mode,"media_url":row.media_url,"media_type":row.media_type,"stagger_seconds":row.stagger_seconds,"created_at":row.created_at,"updated_at":row.updated_at}
@router.get("")
def list_templates(channel:str="telegram",db:Session=Depends(get_db)):
    wid=active_workspace(db);return [output(x) for x in db.scalars(select(BroadcastTemplate).where(BroadcastTemplate.workspace_id==wid,BroadcastTemplate.channel==channel).order_by(BroadcastTemplate.name)).all()]
@router.post("")
def create_template(body:TemplateIn,db:Session=Depends(get_db),user=Depends(require_manager)):
    wid=active_workspace(db);row=BroadcastTemplate(workspace_id=wid,name=body.name.strip(),channel=body.channel,message_text=body.message_text,parse_mode=body.parse_mode,media_url=body.media_url or None,media_type=body.media_type if body.media_url else None,stagger_seconds=body.stagger_seconds,created_by_user_id=user.id,created_at=datetime.utcnow(),updated_at=datetime.utcnow());db.add(row)
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,"A broadcast template with this name already exists")
    db.refresh(row);return output(row)
@router.put("/{template_id}")
def update_template(template_id:int,body:TemplateIn,db:Session=Depends(get_db)):
    wid=active_workspace(db);row=db.scalar(select(BroadcastTemplate).where(BroadcastTemplate.id==template_id,BroadcastTemplate.workspace_id==wid))
    if not row:raise HTTPException(404,"Broadcast template not found")
    row.name=body.name.strip();row.channel=body.channel;row.message_text=body.message_text;row.parse_mode=body.parse_mode;row.media_url=body.media_url or None;row.media_type=body.media_type if body.media_url else None;row.stagger_seconds=body.stagger_seconds;row.updated_at=datetime.utcnow()
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,"A broadcast template with this name already exists")
    db.refresh(row);return output(row)
@router.delete("/{template_id}",status_code=204)
def delete_template(template_id:int,db:Session=Depends(get_db)):
    wid=active_workspace(db);row=db.scalar(select(BroadcastTemplate).where(BroadcastTemplate.id==template_id,BroadcastTemplate.workspace_id==wid))
    if not row:raise HTTPException(404,"Broadcast template not found")
    db.delete(row);db.commit();return Response(status_code=204)
