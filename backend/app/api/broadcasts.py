import re
from datetime import datetime, UTC
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import func,select
from sqlalchemy.orm import Session
from app.broadcast_models import Broadcast,BroadcastRecipient
from app.core.database import get_db
from app.core.security import require_manager
from app.models import Workspace
from app.telegram_models import TelegramBot,TelegramContact,TelegramConversation,TelegramContactFieldValue
from app.models import ContactFieldDefinition
from app.services.telegram import send_text

router=APIRouter(prefix="/broadcasts",tags=["Broadcasts"],dependencies=[Depends(require_manager)])
def now():return datetime.now(UTC).replace(tzinfo=None)
def utc_naive(value):
    if value is None:return None
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value
class BroadcastIn(BaseModel):
    name:str=Field(min_length=1,max_length=150);channel:str="telegram";channel_account_id:int;message_text:str=Field(min_length=1,max_length=4096);audience_type:str="all";contact_ids:list[int]=Field(default_factory=list);scheduled_at:datetime|None=None
class TestIn(BaseModel):contact_id:int
def workspace(db):
    wid=db.scalar(select(Workspace.id).where(Workspace.active.is_(True)).order_by(Workspace.id))
    if wid is None:raise HTTPException(400,"No active workspace")
    return wid
def out(b):
    return {"id":b.id,"name":b.name,"channel":b.channel,"channel_account_id":b.channel_account_id,"message_text":b.message_text,"audience_type":b.audience_type,"status":b.status,"scheduled_at":b.scheduled_at,"started_at":b.started_at,"completed_at":b.completed_at,"total_recipients":b.total_recipients,"sent_count":b.sent_count,"failed_count":b.failed_count,"created_at":b.created_at,"updated_at":b.updated_at}
def render(text,contact,fields):
    values={"name":" ".join(x for x in [contact.first_name,contact.last_name] if x).strip() or contact.username or str(contact.telegram_user_id),"first_name":contact.first_name or "","last_name":contact.last_name or "","username":contact.username or "","subscriber_id":str(contact.telegram_user_id)}
    values.update(fields)
    return re.sub(r"%([a-zA-Z0-9_.-]+)%",lambda m:str(values.get(m.group(1),m.group(0))),text)
def audience(db,wid,bot_id,kind,ids):
    q=select(TelegramContact,TelegramConversation).join(TelegramConversation,TelegramConversation.contact_id==TelegramContact.id).where(TelegramContact.workspace_id==wid,TelegramConversation.telegram_bot_id==bot_id,TelegramConversation.chat_type=="private")
    if kind=="selected":
        if not ids:return []
        q=q.where(TelegramContact.id.in_(ids))
    elif kind!="all":raise HTTPException(400,"audience_type must be all or selected")
    return db.execute(q.order_by(TelegramContact.id)).all()
def field_values(db,contact_ids):
    if not contact_ids:return {}
    rows=db.execute(select(TelegramContactFieldValue.contact_id,ContactFieldDefinition.key,TelegramContactFieldValue.value_text).join(ContactFieldDefinition,ContactFieldDefinition.id==TelegramContactFieldValue.field_id).where(TelegramContactFieldValue.contact_id.in_(contact_ids))).all()
    result={}
    for cid,key,value in rows:result.setdefault(cid,{})[key]=value or ""
    return result

@router.get("")
def list_broadcasts(db:Session=Depends(get_db),user=Depends(require_manager)):
    return [out(x) for x in db.scalars(select(Broadcast).where(Broadcast.workspace_id==workspace(db)).order_by(Broadcast.created_at.desc()).limit(200)).all()]
@router.get("/telegram/audience")
def telegram_audience(bot_id:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    wid=workspace(db);bot=db.get(TelegramBot,bot_id)
    if not bot or bot.workspace_id!=wid:raise HTTPException(404,"Telegram bot not found")
    rows=audience(db,wid,bot_id,"all",[])
    return [{"id":c.id,"name":" ".join(x for x in [c.first_name,c.last_name] if x).strip() or c.username or str(c.telegram_user_id),"username":c.username,"telegram_user_id":c.telegram_user_id} for c,_ in rows]
@router.post("")
def create(body:BroadcastIn,db:Session=Depends(get_db),user=Depends(require_manager)):
    wid=workspace(db)
    if body.channel!="telegram":raise HTTPException(400,"Telegram is the first supported broadcast channel")
    bot=db.get(TelegramBot,body.channel_account_id)
    if not bot or bot.workspace_id!=wid or not bot.active:raise HTTPException(400,"Select an active Telegram bot")
    b=Broadcast(workspace_id=wid,channel="telegram",channel_account_id=bot.id,name=body.name.strip(),message_text=body.message_text,audience_type=body.audience_type,status="draft",scheduled_at=utc_naive(body.scheduled_at),created_by_user_id=user.id,created_at=now(),updated_at=now());db.add(b);db.flush()
    rows=audience(db,wid,bot.id,body.audience_type,body.contact_ids);fv=field_values(db,[c.id for c,_ in rows])
    for c,conv in rows:db.add(BroadcastRecipient(broadcast_id=b.id,channel_contact_id=c.id,conversation_id=conv.id,destination=str(conv.chat_id),display_name=" ".join(x for x in [c.first_name,c.last_name] if x).strip() or c.username,rendered_text=render(body.message_text,c,fv.get(c.id,{})),status="pending",created_at=now(),updated_at=now()))
    b.total_recipients=len(rows);db.commit();db.refresh(b);return out(b)
@router.get("/{broadcast_id}")
def detail(broadcast_id:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    b=db.get(Broadcast,broadcast_id)
    if not b or b.workspace_id!=workspace(db):raise HTTPException(404,"Broadcast not found")
    data=out(b);data["recipients"]=[{"id":r.id,"contact_id":r.channel_contact_id,"display_name":r.display_name,"destination":r.destination,"status":r.status,"attempts":r.attempts,"last_error":r.last_error,"sent_at":r.sent_at} for r in db.scalars(select(BroadcastRecipient).where(BroadcastRecipient.broadcast_id==b.id).order_by(BroadcastRecipient.id)).all()];return data
@router.post("/{broadcast_id}/queue")
def queue(broadcast_id:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    b=db.get(Broadcast,broadcast_id)
    if not b or b.workspace_id!=workspace(db):raise HTTPException(404,"Broadcast not found")
    if b.status not in ("draft","scheduled"):raise HTTPException(409,"Broadcast cannot be queued from its current state")
    if not b.total_recipients:raise HTTPException(400,"Broadcast has no recipients")
    b.status="scheduled" if b.scheduled_at and b.scheduled_at>now() else "queued";b.updated_at=now();db.commit();db.refresh(b);return out(b)
@router.post("/{broadcast_id}/cancel")
def cancel(broadcast_id:int,db:Session=Depends(get_db),user=Depends(require_manager)):
    b=db.get(Broadcast,broadcast_id)
    if not b or b.workspace_id!=workspace(db):raise HTTPException(404,"Broadcast not found")
    if b.status in ("completed","cancelled"):raise HTTPException(409,"Broadcast is already finished")
    b.status="cancelled";b.updated_at=now();db.commit();db.refresh(b);return out(b)
@router.post("/{broadcast_id}/test")
async def test(broadcast_id:int,body:TestIn,db:Session=Depends(get_db),user=Depends(require_manager)):
    b=db.get(Broadcast,broadcast_id)
    if not b or b.workspace_id!=workspace(db):raise HTTPException(404,"Broadcast not found")
    r=db.scalar(select(BroadcastRecipient).where(BroadcastRecipient.broadcast_id==b.id,BroadcastRecipient.channel_contact_id==body.contact_id))
    if not r:raise HTTPException(404,"Recipient is not in this broadcast audience")
    bot=db.get(TelegramBot,b.channel_account_id);result=await send_text(bot.access_token,int(r.destination),r.rendered_text)
    return {"ok":True,"telegram_message_id":result.get("message_id")}
