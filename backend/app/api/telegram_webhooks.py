import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.system_fields import sync_telegram_system_fields
from app.services.telegram import answer_callback
from app.services.telegram_phone_flow import run_telegram_flows_for_inbound
from app.telegram_models import TelegramBot, TelegramContact, TelegramConversation, TelegramMessage

router=APIRouter(prefix="/webhooks/telegram",tags=["Telegram webhooks"]); logger=logging.getLogger(__name__)


def detect_message_type(message:dict)->tuple[str,str|None]:
    if "text" in message:return "text",message.get("text")
    if "photo" in message:return "photo",message.get("caption")
    if "video" in message:return "video",message.get("caption")
    if "voice" in message:return "voice",message.get("caption")
    if "audio" in message:return "audio",message.get("caption")
    if "document" in message:return "document",message.get("caption")
    if "sticker" in message:return "sticker",(message.get("sticker") or {}).get("emoji")
    if "location" in message:
        location=message.get("location") or {};return "location",f"{location.get('latitude')}, {location.get('longitude')}"
    if "contact" in message:return "contact",(message.get("contact") or {}).get("phone_number")
    return "unknown",None


def _upsert_contact_conversation(db,bot,sender,chat):
    sender_id=sender.get("id");chat_id=chat.get("id")
    if sender_id is None or chat_id is None:return None,None
    contact=db.scalar(select(TelegramContact).where(TelegramContact.workspace_id==bot.workspace_id,TelegramContact.telegram_user_id==int(sender_id)))
    if not contact:
        contact=TelegramContact(workspace_id=bot.workspace_id,telegram_user_id=int(sender_id));db.add(contact);db.flush()
    contact.username=sender.get("username");contact.first_name=sender.get("first_name");contact.last_name=sender.get("last_name");contact.language_code=sender.get("language_code")
    sync_telegram_system_fields(db,contact)
    conversation=db.scalar(select(TelegramConversation).where(TelegramConversation.telegram_bot_id==bot.id,TelegramConversation.chat_id==int(chat_id)))
    if not conversation:
        conversation=TelegramConversation(workspace_id=bot.workspace_id,telegram_bot_id=bot.id,contact_id=contact.id,chat_id=int(chat_id),chat_type=chat.get("type") or "private",status="open");db.add(conversation);db.flush()
    else:conversation.contact_id=contact.id
    return contact,conversation


@router.post("/{bot_id}")
async def receive_telegram_webhook(bot_id:int,request:Request,x_telegram_bot_api_secret_token:str|None=Header(default=None),db:Session=Depends(get_db)):
    bot=db.scalar(select(TelegramBot).where(TelegramBot.bot_id==bot_id,TelegramBot.active.is_(True)))
    if not bot:raise HTTPException(status_code=404,detail="Telegram bot not found")
    if not x_telegram_bot_api_secret_token or x_telegram_bot_api_secret_token!=bot.webhook_secret:raise HTTPException(status_code=401,detail="Invalid Telegram webhook secret")
    payload=await request.json();update_id=int(payload.get("update_id") or 0);callback=payload.get("callback_query")
    if callback:
        callback_id=callback.get("id");data=str(callback.get("data") or "");source_message=callback.get("message") or {};sender=callback.get("from") or {};chat=source_message.get("chat") or {}
        if callback_id:
            try:await answer_callback(bot.access_token,callback_id)
            except Exception:logger.exception("Could not acknowledge Telegram callback %s",callback_id)
        _,conversation=_upsert_contact_conversation(db,bot,sender,chat)
        if not conversation:return {"ok":True,"processed":0,"ignored":True}
        synthetic_id=-abs(update_id or int(datetime.utcnow().timestamp()*1000));existing=db.scalar(select(TelegramMessage).where(TelegramMessage.conversation_id==conversation.id,TelegramMessage.telegram_message_id==synthetic_id))
        if existing:db.commit();return {"ok":True,"processed":0,"duplicate":True}
        timestamp=datetime.utcnow();inbound=TelegramMessage(conversation_id=conversation.id,telegram_message_id=synthetic_id,direction="inbound",message_type="button",body=data,payload_json=json.dumps(payload,ensure_ascii=False),status="received",telegram_timestamp=timestamp)
        db.add(inbound);conversation.last_message_at=timestamp;db.commit();db.refresh(inbound);flows_executed=0
        try:flows_executed=await run_telegram_flows_for_inbound(db,conversation,inbound);db.commit()
        except Exception:db.rollback();logger.exception("Telegram callback flow execution failed conversation=%s data=%r",conversation.id,data)
        return {"ok":True,"processed":1,"conversation_id":conversation.id,"message_id":inbound.id,"flows_executed":flows_executed,"callback":True}
    message=payload.get("message")
    if not message:return {"ok":True,"processed":0,"ignored":True}
    sender=message.get("from") or {};chat=message.get("chat") or {};telegram_message_id=message.get("message_id");contact,conversation=_upsert_contact_conversation(db,bot,sender,chat)
    if not conversation or telegram_message_id is None:return {"ok":True,"processed":0,"ignored":True}
    existing=db.scalar(select(TelegramMessage).where(TelegramMessage.conversation_id==conversation.id,TelegramMessage.telegram_message_id==int(telegram_message_id)))
    if existing:db.commit();return {"ok":True,"processed":0,"duplicate":True}
    if contact:
        phone=(message.get("contact") or {}).get("phone_number") if "contact" in message else None
        location=message.get("location") if "location" in message else None
        sync_telegram_system_fields(db,contact,phone_number=phone,location=location)
    message_type,body=detect_message_type(message);timestamp=datetime.utcfromtimestamp(message["date"]) if message.get("date") else datetime.utcnow();inbound=TelegramMessage(conversation_id=conversation.id,telegram_message_id=int(telegram_message_id),direction="inbound",message_type=message_type,body=body,payload_json=json.dumps(payload,ensure_ascii=False),status="received",telegram_timestamp=timestamp)
    db.add(inbound);conversation.last_message_at=timestamp;db.commit();db.refresh(inbound);flows_executed=0
    try:flows_executed=await run_telegram_flows_for_inbound(db,conversation,inbound);db.commit()
    except Exception:db.rollback();logger.exception("Telegram flow runtime failed conversation=%s inbound=%s",conversation.id,inbound.id)
    return {"ok":True,"processed":1,"conversation_id":conversation.id,"message_id":inbound.id,"flows_executed":flows_executed}
