import asyncio,logging
from datetime import datetime,UTC
from sqlalchemy import func,select
from app.core.database import SessionLocal
import app.models,app.telegram_models,app.broadcast_models
from app.broadcast_models import Broadcast,BroadcastRecipient
from app.telegram_models import TelegramBot,TelegramConversation,TelegramMessage
from app.services.telegram import send_text,send_media
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
            bot=db.get(TelegramBot,b.channel_account_id)
            if not bot or not bot.active:raise RuntimeError("Telegram bot is unavailable")
            if b.last_sent_at and b.stagger_seconds:
                elapsed=(now()-b.last_sent_at).total_seconds()
                if elapsed<b.stagger_seconds:await asyncio.sleep(b.stagger_seconds-elapsed)
            # Pause/cancel may happen while a stagger delay is sleeping. Re-read
            # the broadcast immediately before the provider call so a claimed
            # recipient is not sent after the operator has stopped delivery.
            db.expire_all();b=db.get(Broadcast,bid);recipient=db.get(BroadcastRecipient,rid)
            if b.status!="sending":
                recipient.status="pending";recipient.attempts=max(0,recipient.attempts-1);recipient.updated_at=now();db.commit()
                log.info("Broadcast %s stopped before recipient %s send; status=%s",bid,rid,b.status)
                return True
            result=await (send_media(bot.access_token,int(recipient.destination),b.media_type,b.media_url,recipient.rendered_text,b.parse_mode) if b.media_url else send_text(bot.access_token,int(recipient.destination),recipient.rendered_text,b.parse_mode))
            mid=int(result["message_id"]);recipient=db.get(BroadcastRecipient,rid);recipient.status="sent";recipient.provider_message_id=str(mid);recipient.sent_at=now();recipient.last_error=None;recipient.updated_at=now()
            conv=db.get(TelegramConversation,recipient.conversation_id)
            if conv:
                db.add(TelegramMessage(conversation_id=conv.id,telegram_message_id=mid,direction="outbound",message_type="text",body=recipient.rendered_text,status="sent",telegram_timestamp=now()))
                conv.last_message_at=now();conv.updated_at=now()
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
