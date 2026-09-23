import json
from datetime import datetime
from fastapi import APIRouter,Depends,HTTPException,Response
from pydantic import BaseModel,Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import require_manager
from app.models import AudienceSegment,Workspace

router=APIRouter(prefix="/audience-segments",tags=["Audience Segments"],dependencies=[Depends(require_manager)])
class SegmentRule(BaseModel):field:str;operator:str="equals";value:str=""
class SegmentFilter(BaseModel):logic:str="and";rules:list[SegmentRule]=Field(default_factory=list)
class SegmentIn(BaseModel):name:str=Field(min_length=1,max_length=150);channel:str="telegram";audience_filter:SegmentFilter

def active_workspace(db):
    wid=db.scalar(select(Workspace.id).where(Workspace.active.is_(True)).order_by(Workspace.id))
    if wid is None:raise HTTPException(400,"No active workspace")
    return int(wid)
def output(row):
    return {"id":row.id,"name":row.name,"channel":row.channel,"audience_filter":json.loads(row.filter_json),"created_at":row.created_at,"updated_at":row.updated_at}
@router.get("")
def list_segments(channel:str="telegram",db:Session=Depends(get_db)):
    wid=active_workspace(db);return [output(x) for x in db.scalars(select(AudienceSegment).where(AudienceSegment.workspace_id==wid,AudienceSegment.channel==channel).order_by(AudienceSegment.name)).all()]
@router.post("")
def create_segment(body:SegmentIn,db:Session=Depends(get_db),user=Depends(require_manager)):
    wid=active_workspace(db);row=AudienceSegment(workspace_id=wid,name=body.name.strip(),channel=body.channel,filter_json=json.dumps(body.audience_filter.model_dump()),created_by_user_id=user.id,created_at=datetime.utcnow(),updated_at=datetime.utcnow());db.add(row)
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,"A segment with this name already exists")
    db.refresh(row);return output(row)
@router.put("/{segment_id}")
def update_segment(segment_id:int,body:SegmentIn,db:Session=Depends(get_db)):
    wid=active_workspace(db);row=db.scalar(select(AudienceSegment).where(AudienceSegment.id==segment_id,AudienceSegment.workspace_id==wid))
    if not row:raise HTTPException(404,"Segment not found")
    row.name=body.name.strip();row.channel=body.channel;row.filter_json=json.dumps(body.audience_filter.model_dump());row.updated_at=datetime.utcnow()
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,"A segment with this name already exists")
    db.refresh(row);return output(row)
@router.delete("/{segment_id}",status_code=204)
def delete_segment(segment_id:int,db:Session=Depends(get_db)):
    wid=active_workspace(db);row=db.scalar(select(AudienceSegment).where(AudienceSegment.id==segment_id,AudienceSegment.workspace_id==wid))
    if not row:raise HTTPException(404,"Segment not found")
    db.delete(row);db.commit();return Response(status_code=204)
