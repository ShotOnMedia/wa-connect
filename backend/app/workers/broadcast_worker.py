import asyncio,logging
from datetime import datetime,UTC
from sqlalchemy import func,select
from app.core.database import SessionLocal
import app.models,app.telegram_models,app.broadcast_models
from app.broadcast_models import Broadcast,BroadcastRecipient
from app.telegram_models import TelegramBot,TelegramConversation,TelegramMessage
from app.models import WhatsAppPhoneNumber,Conversation,Message,MessageDirection,MessageStatus
from app.core.config import settings
from app.services.telegram import send_text,send_media
from app.services.whatsapp import send_text_message,send_media_message,send_template_message
logging.basicConfig(level=logging.INFO);log=logging.getLogger("broadcast-worker")
def now():return datetime.now(UTC).replace(tzinfo=None)

async def process_one():
    with SessionLocal() as db:
        b=db.scalar(select(Broadcast).where(Broadcast.status.in_(["queued","scheduled","sending"]),((Broadcast.scheduled_at.is_(None))|(Broadcast.scheduled_at<=now()))).order_by(Broadcast.created_at,Broadcast.id).limit(1))
        if not b:return False
        if b.status!="sending":b.status="sending";b.started_at=b.started_at or now();b.updated_at=now();db.commit()
        recipient=db.scalar(select(BroadcastRecipient).where(BroadcastRecipient.broadcast_id==b.id,BroadcastRecipient.status=="pending").order_by(BroadcastRecipient.id).limit(1))
        if not recipient:
            b.sent_count=db.scalar(select(func.count()).select_from(BroadcastRecipient).where(BroadcastRecipient.broadcast_id==b.id,BroadcastRecipient.status=="sent")) or 0
            b.failed_count=db.scalar(select(func.count()).select_from(BroadcastRecipient).where(BroadcastRecipient.broadcast_id==b.id,BroadcastRecipient.status=="failed")) or 0
            b.status="completed";b.completed_at=now();b.updated_at=now();db.commit();log.info("Broadcast %s completed sent=%s failed=%s",b.id,b.sent_count,b.failed_count);return True
        recipient.status="sending";recipient.attempts+=1;recipient.updated_at=now();db.commit();rid=recipient.id;bid=b.id
        try:
            if b.channel=="telegram":
                account=db.get(TelegramBot,b.channel_account_id)
                if not account or not account.active:raise RuntimeError("Telegram bot is unavailable")
            elif b.channel=="whatsapp":
                account=db.get(WhatsAppPhoneNumber,b.channel_account_id)
                if not account or not account.active:raise RuntimeError("WhatsApp connection is unavailable")
            else:raise RuntimeError("Unsupported broadcast channel")
            if b.last_sent_at and b.stagger_seconds:
                elapsed=(now()-b.last_sent_at).total_seconds()
                if elapsed<b.stagger_seconds:await asyncio.sleep(b.stagger_seconds-elapsed)
            # Loading the bot above starts a MariaDB transaction.  With the
            # default REPEATABLE READ isolation level, merely expiring ORM
            # objects here can still re-read the old "sending" snapshot after
            # an operator has committed Pause/Cancel in another connection.
            # End that transaction first, then do the final stop check from a
            # fresh transaction immediately before the Telegram API call.
            db.rollback()
            b=db.get(Broadcast,bid);recipient=db.get(BroadcastRecipient,rid)
            if b.status!="sending":
                recipient.status="pending";recipient.attempts=max(0,recipient.attempts-1);recipient.updated_at=now();db.commit()
                log.info("Broadcast %s stopped before recipient %s send; status=%s",bid,rid,b.status)
                return True
            # Copy everything needed for the provider call, then close the DB
            # transaction so no snapshot is held while waiting on Telegram.
            if b.channel=="telegram":
                account=db.get(TelegramBot,b.channel_account_id)
                if not account or not account.active:raise RuntimeError("Telegram bot is unavailable")
                token=account.access_token;destination=int(recipient.destination);media_type=b.media_type;media_url=b.media_url;rendered_text=recipient.rendered_text;parse_mode=b.parse_mode;db.commit()
                result=await (send_media(token,destination,media_type,media_url,rendered_text,parse_mode) if media_url else send_text(token,destination,rendered_text,parse_mode));mid=str(result["message_id"])
            else:
                account=db.get(WhatsAppPhoneNumber,b.channel_account_id)
                if not account or not account.active:raise RuntimeError("WhatsApp connection is unavailable")
                token=account.access_token or settings.meta_access_token
                if not token:raise RuntimeError("No WhatsApp access token configured")
                phone_number_id=account.phone_number_id;destination=recipient.destination;media_type=b.media_type;media_url=b.media_url;rendered_text=recipient.rendered_text;db.commit()
                
                if b.message_mode=="template":
                    snap=json.loads(b.provider_template_json or "{}");components=snap.get("components_payload") or []
                    result=await send_template_message(phone_number_id,token,destination,snap["name"],snap["language"],components)
                else:result=await (send_media_message(phone_number_id,token,destination,media_type,media_url,rendered_text) if media_url else send_text_message(phone_number_id,token,destination,rendered_text))
                mid=str((result.get("messages") or [{}])[0].get("id") or "")
            recipient=db.get(BroadcastRecipient,rid);recipient.status="sent";recipient.provider_message_id=mid or None;recipient.sent_at=now();recipient.last_error=None;recipient.updated_at=now()
            if b.channel=="telegram":
                conv=db.get(TelegramConversation,recipient.conversation_id)
                if conv:db.add(TelegramMessage(conversation_id=conv.id,telegram_message_id=int(mid),direction="outbound",message_type="text",body=recipient.rendered_text,status="sent",telegram_timestamp=now()));conv.last_message_at=now();conv.updated_at=now()
            else:
                conv=db.get(Conversation,recipient.conversation_id)
                if conv:db.add(Message(conversation_id=conv.id,meta_message_id=mid or None,direction=MessageDirection.OUTBOUND,message_type=b.media_type if b.media_url else "text",body=recipient.rendered_text,status=MessageStatus.SENT,whatsapp_timestamp=now()));conv.last_message_at=now();conv.updated_at=now()
            b=db.get(Broadcast,bid);b.sent_count+=1;b.last_sent_at=now();b.updated_at=now();db.commit()
        except Exception as exc:
            db.rollback();recipient=db.get(BroadcastRecipient,rid);b=db.get(Broadcast,bid)
            recipient.status="pending" if recipient.attempts<3 else "failed";recipient.last_error=str(exc)[:4000];recipient.updated_at=now()
            if recipient.status=="failed":b.failed_count+=1
            b.updated_at=now();db.commit();log.exception("Broadcast %s recipient %s failed",bid,rid)
        return True

async def main():
    log.info("Broadcast worker started")
    while True:
        try:
            worked=await process_one()
        except Exception:log.exception("Unexpected broadcast worker failure");worked=False
        await asyncio.sleep(0.05 if worked else 1.0)
if __name__=="__main__":asyncio.run(main())
