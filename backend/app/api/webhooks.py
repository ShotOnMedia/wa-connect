import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models import Conversation
from app.services.flow_runtime import run_flows_for_inbound
from app.services.webhook import process_webhook_payload
from app.services.whatsapp import verify_meta_signature

router = APIRouter(prefix="/webhooks/meta", tags=["Meta webhooks"])
logger = logging.getLogger(__name__)


@router.get("/whatsapp")
def verify_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    if hub_mode != "subscribe" or hub_verify_token != settings.meta_verify_token:
        raise HTTPException(status_code=403, detail="Webhook verification failed")
    return Response(content=hub_challenge, media_type="text/plain")


@router.post("/whatsapp")
async def receive_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    raw_body = await request.body()
    if not verify_meta_signature(raw_body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = await request.json()
    processed, inbound_messages = process_webhook_payload(db, payload)
    flows_executed = 0

    for inbound_message in inbound_messages:
        try:
            conversation = db.scalar(select(Conversation).where(Conversation.id == inbound_message.conversation_id))
            if conversation:
                flows_executed += await run_flows_for_inbound(db, conversation, inbound_message)
        except Exception:
            logger.exception("Flow execution failed for inbound message id=%s", inbound_message.id)

    return {"ok": True, "processed": processed, "flows_executed": flows_executed}
