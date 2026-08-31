import json
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.database import get_db
from app.core.security import require_admin, require_user
from app.models import Workspace
from app.services.telegram import TelegramError, send_text, set_webhook, verify_bot, webhook_info
from app.telegram_models import TelegramBot, TelegramContact, TelegramConversation, TelegramMessage

router = APIRouter(prefix="/telegram", tags=["Telegram"])

class TelegramVerifyIn(BaseModel): bot_token: str = Field(min_length=20)
class TelegramConnectIn(BaseModel):
    workspace_name: str=Field(min_length=1,max_length=150); workspace_slug: str=Field(min_length=1,max_length=150); bot_token: str=Field(min_length=20); webhook_base_url: str=Field(min_length=8,max_length=500)
    @field_validator("webhook_base_url")
    @classmethod
    def validate_webhook_base_url(cls,value:str):
        value=value.strip().rstrip("/")
        if not value.startswith("https://"): raise ValueError("Telegram webhooks require an HTTPS public URL")
        return value
class TelegramBotOut(BaseModel):
    id:int; workspace_id:int; workspace_name:str; workspace_slug:str; bot_id:int; username:str|None=None; first_name:str|None=None; active:bool; webhook_url:str|None=None; has_token:bool=True; created_at:datetime
class TelegramStatsOut(BaseModel): bots:int; contacts:int; conversations:int; messages:int; unread:int
class TelegramSendIn(BaseModel): text:str=Field(min_length=1,max_length=4096)

def bot_out(bot,workspace): return TelegramBotOut(id=bot.id,workspace_id=workspace.id,workspace_name=workspace.name,workspace_slug=workspace.slug,bot_id=bot.bot_id,username=bot.username,first_name=bot.first_name,active=bot.active,webhook_url=bot.webhook_url,has_token=bool(bot.access_token),created_at=bot.created_at)
def contact_out(c): return {"id":c.id,"telegram_user_id":c.telegram_user_id,"username":c.username,"first_name":c.first_name,"last_name":c.last_name,"name":" ".join(filter(None,[c.first_name,c.last_name])) or c.username or str(c.telegram_user_id),"language_code":c.language_code,"is_bot":False,"created_at":c.created_at,"updated_at":c.updated_at}
def message_out(m): return {"id":m.id,"telegram_message_id":m.telegram_message_id,"direction":m.direction,"message_type":m.message_type,"body":m.body,"status":m.status,"telegram_timestamp":m.telegram_timestamp,"created_at":m.created_at}
def conversation_out(c):
    last=c.messages[-1] if c.messages else None
    unread=bool(c.last_message_at and (not c.last_read_at or c.last_read_at<c.last_message_at))
    return {"id":c.id,"chat_id":c.chat_id,"chat_type":c.chat_type,"status":c.status,"assigned_user_id":c.assigned_user_id,"last_message_at":c.last_message_at,"last_read_at":c.last_read_at,"unread_count":1 if unread else 0,"last_message_body":last.body if last else None,"last_message_direction":last.direction if last else None,"contact":contact_out(c.contact),"bot":{"id":c.bot.id,"bot_id":c.bot.bot_id,"username":c.bot.username,"first_name":c.bot.first_name}}

@router.post("/verify",dependencies=[Depends(require_admin)])
async def verify_telegram_bot(request:TelegramVerifyIn):
    try:return {"connected":True,**await verify_bot(request.bot_token.strip())}
    except TelegramError as exc:raise HTTPException(status_code=502,detail=f"Telegram verification failed: {exc}") from exc
@router.get("/bots",response_model=list[TelegramBotOut],dependencies=[Depends(require_admin)])
def list_bots(db:Session=Depends(get_db)):
    rows=db.execute(select(TelegramBot,Workspace).join(Workspace,Workspace.id==TelegramBot.workspace_id).order_by(TelegramBot.created_at.asc())).all();return [bot_out(b,w) for b,w in rows]
@router.post("/bots",response_model=TelegramBotOut,status_code=201,dependencies=[Depends(require_admin)])
async def connect_bot(request:TelegramConnectIn,db:Session=Depends(get_db)):
    token=request.bot_token.strip()
    try:verified=await verify_bot(token)
    except TelegramError as exc:raise HTTPException(status_code=502,detail=f"Telegram verification failed: {exc}") from exc
    workspace=db.scalar(select(Workspace).where(Workspace.slug==request.workspace_slug.strip()))
    if not workspace: workspace=Workspace(name=request.workspace_name.strip(),slug=request.workspace_slug.strip());db.add(workspace);db.flush()
    bot=db.scalar(select(TelegramBot).where(TelegramBot.bot_id==verified["bot_id"]))
    if bot and bot.workspace_id!=workspace.id:raise HTTPException(status_code=409,detail="This Telegram bot is already connected to another workspace")
    if not bot: bot=TelegramBot(workspace_id=workspace.id,bot_id=verified["bot_id"],username=verified.get("username"),first_name=verified.get("first_name"),access_token=token,webhook_secret=secrets.token_urlsafe(32),active=True);db.add(bot);db.flush()
    else:
        bot.username=verified.get("username");bot.first_name=verified.get("first_name");bot.access_token=token;bot.active=True
        if not bot.webhook_secret:bot.webhook_secret=secrets.token_urlsafe(32)
    webhook_url=f"{request.webhook_base_url}{settings.api_prefix}/webhooks/telegram/{bot.bot_id}"
    try:await set_webhook(token,webhook_url,bot.webhook_secret)
    except TelegramError as exc:db.rollback();raise HTTPException(status_code=502,detail=f"Bot verified, but webhook registration failed: {exc}") from exc
    bot.webhook_url=webhook_url;db.commit();db.refresh(bot);return bot_out(bot,workspace)
@router.get("/bots/{bot_db_id}/health",dependencies=[Depends(require_admin)])
async def bot_health(bot_db_id:int,db:Session=Depends(get_db)):
    bot=db.scalar(select(TelegramBot).where(TelegramBot.id==bot_db_id))
    if not bot:raise HTTPException(status_code=404,detail="Telegram bot not found")
    try:
        identity=await verify_bot(bot.access_token)
        if bot.webhook_url and bot.webhook_secret: await set_webhook(bot.access_token,bot.webhook_url,bot.webhook_secret)
        return {"connected":True,"identity":identity,"webhook":await webhook_info(bot.access_token)}
    except TelegramError as exc:raise HTTPException(status_code=502,detail=str(exc)) from exc
@router.get("/stats",response_model=TelegramStatsOut,dependencies=[Depends(require_user)])
def telegram_stats(db:Session=Depends(get_db)):
    bots=db.scalar(select(func.count()).select_from(TelegramBot).where(TelegramBot.active.is_(True))) or 0;contacts=db.scalar(select(func.count()).select_from(TelegramContact)) or 0;conversations=db.scalar(select(func.count()).select_from(TelegramConversation)) or 0;messages=db.scalar(select(func.count()).select_from(TelegramMessage)) or 0;unread=db.scalar(select(func.count()).select_from(TelegramConversation).where(TelegramConversation.last_message_at.is_not(None),(TelegramConversation.last_read_at.is_(None))|(TelegramConversation.last_read_at<TelegramConversation.last_message_at))) or 0;return TelegramStatsOut(bots=bots,contacts=contacts,conversations=conversations,messages=messages,unread=unread)

@router.get("/contacts",dependencies=[Depends(require_user)])
def telegram_contacts(q:str|None=None,db:Session=Depends(get_db)):
    stmt=select(TelegramContact).order_by(TelegramContact.updated_at.desc())
    if q:
        term=f"%{q.strip()}%";stmt=stmt.where(or_(TelegramContact.first_name.ilike(term),TelegramContact.last_name.ilike(term),TelegramContact.username.ilike(term)))
    contacts=db.scalars(stmt).all();result=[]
    for c in contacts:
        convs=db.scalars(select(TelegramConversation).options(joinedload(TelegramConversation.bot)).where(TelegramConversation.contact_id==c.id).order_by(TelegramConversation.last_message_at.desc())).all()
        result.append({**contact_out(c),"conversation_count":len(convs),"last_message_at":convs[0].last_message_at if convs else None,"conversations":[{"id":x.id,"chat_id":x.chat_id,"status":x.status,"last_message_at":x.last_message_at,"bot":{"id":x.bot.id,"username":x.bot.username,"first_name":x.bot.first_name}} for x in convs]})
    return result
@router.get("/contacts/{contact_id}",dependencies=[Depends(require_user)])
def telegram_contact(contact_id:int,db:Session=Depends(get_db)):
    c=db.scalar(select(TelegramContact).where(TelegramContact.id==contact_id))
    if not c:raise HTTPException(status_code=404,detail="Telegram contact not found")
    convs=db.scalars(select(TelegramConversation).options(joinedload(TelegramConversation.bot)).where(TelegramConversation.contact_id==c.id).order_by(TelegramConversation.last_message_at.desc())).all()
    return {**contact_out(c),"conversation_count":len(convs),"last_message_at":convs[0].last_message_at if convs else None,"conversations":[{"id":x.id,"chat_id":x.chat_id,"status":x.status,"last_message_at":x.last_message_at,"bot":{"id":x.bot.id,"username":x.bot.username,"first_name":x.bot.first_name}} for x in convs]}

@router.get("/conversations",dependencies=[Depends(require_user)])
def telegram_conversations(db:Session=Depends(get_db)):
    rows=db.scalars(select(TelegramConversation).options(joinedload(TelegramConversation.contact),joinedload(TelegramConversation.bot),joinedload(TelegramConversation.messages)).order_by(TelegramConversation.last_message_at.desc())).unique().all();return [conversation_out(c) for c in rows]
@router.get("/conversations/{conversation_id}/messages",dependencies=[Depends(require_user)])
def telegram_messages(conversation_id:int,db:Session=Depends(get_db)):
    c=db.scalar(select(TelegramConversation).where(TelegramConversation.id==conversation_id));
    if not c:raise HTTPException(status_code=404,detail="Telegram conversation not found")
    return [message_out(m) for m in db.scalars(select(TelegramMessage).where(TelegramMessage.conversation_id==conversation_id).order_by(TelegramMessage.created_at.asc())).all()]
@router.post("/conversations/{conversation_id}/read",dependencies=[Depends(require_user)])
def telegram_mark_read(conversation_id:int,db:Session=Depends(get_db)):
    c=db.scalar(select(TelegramConversation).where(TelegramConversation.id==conversation_id));
    if not c:raise HTTPException(status_code=404,detail="Telegram conversation not found")
    c.last_read_at=datetime.utcnow();db.commit();return {"ok":True}
@router.post("/conversations/{conversation_id}/messages",dependencies=[Depends(require_user)])
async def telegram_send_message(conversation_id:int,request:TelegramSendIn,db:Session=Depends(get_db)):
    c=db.scalar(select(TelegramConversation).options(joinedload(TelegramConversation.bot)).where(TelegramConversation.id==conversation_id))
    if not c:raise HTTPException(status_code=404,detail="Telegram conversation not found")
    try:sent=await send_text(c.bot.access_token,c.chat_id,request.text.strip())
    except TelegramError as exc:raise HTTPException(status_code=502,detail=f"Telegram send failed: {exc}") from exc
    timestamp=datetime.utcfromtimestamp(sent["date"]) if sent.get("date") else datetime.utcnow();m=TelegramMessage(conversation_id=c.id,telegram_message_id=int(sent["message_id"]),direction="outbound",message_type="text",body=sent.get("text") or request.text.strip(),payload_json=json.dumps(sent,ensure_ascii=False),status="sent",telegram_timestamp=timestamp);db.add(m);c.last_message_at=timestamp;c.last_read_at=timestamp;db.commit();db.refresh(m);return message_out(m)
