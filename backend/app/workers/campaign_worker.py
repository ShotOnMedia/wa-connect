import asyncio,json,logging,re
from datetime import datetime,UTC,timedelta
from sqlalchemy import func,select
from app.core.database import SessionLocal
import app.models,app.telegram_models,app.campaign_engine_models
from app.campaign_engine_models import MessagingCampaign,MessagingCampaignStep,MessagingCampaignRecipient,MessagingCampaignDelivery
from app.telegram_models import TelegramBot,TelegramConversation,TelegramMessage
from app.models import WhatsAppPhoneNumber,Conversation,Message,MessageDirection,MessageStatus
from app.core.config import settings
from app.services.telegram import send_text,send_media
from app.services.whatsapp import send_text_message,send_media_message,send_template_message

logging.basicConfig(level=logging.INFO);log=logging.getLogger("campaign-worker")
TOKEN_RE=re.compile(r"%([a-zA-Z0-9_.-]+)%")
def now():return datetime.now(UTC).replace(tzinfo=None)
def render_values(text,values):return TOKEN_RE.sub(lambda m:str(values.get(m.group(1),m.group(0))),text or "")
class PermanentDeliveryError(RuntimeError):pass

def finish_campaign_if_done(db,campaign_id):
    pending=db.scalar(select(func.count()).select_from(MessagingCampaignRecipient).where(MessagingCampaignRecipient.campaign_id==campaign_id,MessagingCampaignRecipient.status.in_(["pending","running"]))) or 0
    if pending:return
    c=db.get(MessagingCampaign,campaign_id)
    if c and c.status not in ("cancelled","completed","completed_with_failures","failed"):
        total=db.scalar(select(func.count()).select_from(MessagingCampaignRecipient).where(MessagingCampaignRecipient.campaign_id==campaign_id)) or 0
        failed=db.scalar(select(func.count()).select_from(MessagingCampaignRecipient).where(MessagingCampaignRecipient.campaign_id==campaign_id,MessagingCampaignRecipient.status=="failed")) or 0
        completed=db.scalar(select(func.count()).select_from(MessagingCampaignRecipient).where(MessagingCampaignRecipient.campaign_id==campaign_id,MessagingCampaignRecipient.status=="completed")) or 0
        c.status="failed" if total and failed==total else "completed_with_failures" if failed else "completed"
        c.completed_at=now();c.updated_at=now();db.commit();log.info("Campaign %s finished with status %s (%s completed, %s failed)",campaign_id,c.status,completed,failed)

async def process_one():
    with SessionLocal() as db:
        current=now()
        c=db.scalar(select(MessagingCampaign).where(MessagingCampaign.status=="scheduled",MessagingCampaign.scheduled_at.is_not(None),MessagingCampaign.scheduled_at<=current).order_by(MessagingCampaign.scheduled_at,MessagingCampaign.id).limit(1))
        if c:c.status="running";c.started_at=c.started_at or current;c.updated_at=current;db.commit()
        d=db.scalar(select(MessagingCampaignDelivery).join(MessagingCampaign,MessagingCampaign.id==MessagingCampaignDelivery.campaign_id).where(MessagingCampaign.status=="running",MessagingCampaignDelivery.status=="pending",MessagingCampaignDelivery.due_at<=current).order_by(MessagingCampaignDelivery.due_at,MessagingCampaignDelivery.id).limit(1))
        if not d:return False
        d.status="sending";d.attempts+=1;d.updated_at=now()
        r=db.get(MessagingCampaignRecipient,d.recipient_id);r.status="running";r.started_at=r.started_at or now();r.updated_at=now()
        db.commit();did=d.id;cid=d.campaign_id;rid=d.recipient_id
        try:
            db.rollback();d=db.get(MessagingCampaignDelivery,did);c=db.get(MessagingCampaign,cid);r=db.get(MessagingCampaignRecipient,rid)
            if c.status!="running":
                d.status="pending";d.attempts=max(0,d.attempts-1);d.updated_at=now();db.commit();return True
            step=db.get(MessagingCampaignStep,d.step_id)
            text=d.rendered_text;media_url=d.media_url;media_type=d.media_type;parse_mode=d.parse_mode
            if c.channel=="telegram":
                account=db.get(TelegramBot,c.channel_account_id)
                if not account or not account.active:raise RuntimeError("Telegram bot is unavailable")
                token=account.access_token;destination=int(r.destination);db.commit()
                result=await (send_media(token,destination,media_type,media_url,text,parse_mode) if media_url else send_text(token,destination,text,parse_mode))
                mid=str(result["message_id"])
            elif c.channel=="whatsapp":
                account=db.get(WhatsAppPhoneNumber,c.channel_account_id)
                if not account or not account.active:raise RuntimeError("WhatsApp connection is unavailable")
                token=account.access_token or settings.meta_access_token
                if not token:raise RuntimeError("No WhatsApp access token configured")
                phone_number_id=account.phone_number_id;destination=r.destination
                values=json.loads(r.field_values_json or "{}")
                mode=step.message_mode if step else "freeform"
                provider=json.loads(step.provider_template_json or "{}") if step else {}
                def resolve(value):
                    if isinstance(value,str):return render_values(value,values)
                    if isinstance(value,list):return [resolve(x) for x in value]
                    if isinstance(value,dict):return {k:resolve(v) for k,v in value.items()}
                    return value
                provider=resolve(provider)
                if mode!="template":
                    conv=db.get(Conversation,r.conversation_id)
                    if not conv or not conv.service_window_expires_at or conv.service_window_expires_at<=now():raise PermanentDeliveryError("WhatsApp service window has closed; an approved template message is required for this campaign step")
                db.commit()
                if mode=="template":
                    components=provider.get("components_payload") or []
                    result=await send_template_message(phone_number_id,token,destination,provider["name"],provider["language"],components)
                else:
                    result=await (send_media_message(phone_number_id,token,destination,media_type,media_url,text) if media_url else send_text_message(phone_number_id,token,destination,text))
                mid=str((result.get("messages") or [{}])[0].get("id") or "")
            else:raise RuntimeError("Unsupported campaign channel")
            d=db.get(MessagingCampaignDelivery,did);r=db.get(MessagingCampaignRecipient,rid);c=db.get(MessagingCampaign,cid)
            d.status="sent";d.provider_message_id=mid;d.sent_at=now();d.last_error=None;d.updated_at=now()
            if c.channel=="telegram":
                conv=db.get(TelegramConversation,r.conversation_id)
                if conv:
                    db.add(TelegramMessage(conversation_id=conv.id,telegram_message_id=int(mid),direction="outbound",message_type=d.media_type if d.media_url else "text",body=d.rendered_text,status="sent",telegram_timestamp=now()))
                    conv.last_message_at=now();conv.updated_at=now()
            else:
                conv=db.get(Conversation,r.conversation_id)
                if conv:
                    db.add(Message(conversation_id=conv.id,meta_message_id=mid or None,direction=MessageDirection.OUTBOUND,message_type=d.media_type if d.media_url else "text",body=d.rendered_text,status=MessageStatus.SENT,whatsapp_timestamp=now()))
                    conv.last_message_at=now();conv.updated_at=now()
            next_step=db.scalar(select(MessagingCampaignStep).where(MessagingCampaignStep.campaign_id==cid,MessagingCampaignStep.position>d.step_position).order_by(MessagingCampaignStep.position).limit(1))
            if next_step:
                values=json.loads(r.field_values_json or "{}")
                db.add(MessagingCampaignDelivery(campaign_id=cid,recipient_id=rid,step_id=next_step.id,step_position=next_step.position,rendered_text=render_values(next_step.message_text,values),media_url=next_step.media_url,media_type=next_step.media_type,parse_mode=next_step.parse_mode,status="pending",due_at=d.sent_at+timedelta(seconds=next_step.delay_seconds),created_at=now(),updated_at=now()))
                r.current_step_position=next_step.position;r.status="running";r.updated_at=now()
            else:
                r.status="completed";r.completed_at=now();r.updated_at=now()
            db.commit();finish_campaign_if_done(db,cid)
        except Exception as exc:
            db.rollback();d=db.get(MessagingCampaignDelivery,did);r=db.get(MessagingCampaignRecipient,rid)
            d.last_error=str(exc)[:4000];d.updated_at=now()
            permanent=isinstance(exc,PermanentDeliveryError)
            if not permanent and d.attempts<3:
                d.status="pending";d.due_at=now()+timedelta(seconds=30)
            else:
                d.status="failed";r.status="failed";r.failed_at=now();r.last_error=d.last_error;r.updated_at=now()
            db.commit();finish_campaign_if_done(db,cid);log.exception("Campaign %s delivery %s failed",cid,did)
        return True

async def main():
    log.info("Campaign worker started")
    while True:
        try:worked=await process_one()
        except Exception:log.exception("Unexpected campaign worker failure");worked=False
        await asyncio.sleep(0.1 if worked else 1.0)
if __name__=="__main__":asyncio.run(main())
