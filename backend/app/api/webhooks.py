import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.core.config import settings
from app.core.database import get_db
from app.models import Conversation
from app.services.flow_runtime import run_flows_for_inbound
from app.services.webhook import process_webhook_payload
from app.services.whatsapp import verify_meta_signature

router = APIRouter(prefix="/webhooks/meta", tags=["Meta webhooks"])
logger = logging.getLogger(__name__)


def _flow_reply_value(message):
    """Return Meta's routing value while keeping the human title in Live Chat.

    The webhook service deliberately stores the visible interactive title in
    Message.body so agents see e.g. "Apple iPhone 15 Pro" rather than an
    internal value such as ``wfdyn:56:1``. Flow routing, however, must use the
    reply id/payload. This extracts that value from the original Meta payload.
    """
    if str(message.message_type or "").lower() not in {"interactive", "button"}:
        return None
    try:
        payload = json.loads(message.payload_json or "{}")
    except (TypeError, json.JSONDecodeError):
        return None

    if payload.get("type") == "button":
        button = payload.get("button") or {}
        return button.get("payload") or None

    interactive = payload.get("interactive") or {}
    reply_type = interactive.get("type")
    if reply_type == "button_reply":
        return (interactive.get("button_reply") or {}).get("id") or None
    if reply_type == "list_reply":
        return (interactive.get("list_reply") or {}).get("id") or None
    return None


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
        original_body = inbound_message.body
        try:
            conversation = db.scalar(select(Conversation).where(Conversation.id == inbound_message.conversation_id))
            if conversation:
                routing_value = _flow_reply_value(inbound_message)
                if routing_value:
                    # Present the routing ID to the runtime without marking the
                    # ORM column dirty. Runtime commits therefore keep the
                    # human-readable title stored for Live Chat/history.
                    set_committed_value(inbound_message, "body", routing_value)
                flows_executed += await run_flows_for_inbound(db, conversation, inbound_message)
        except Exception:
            logger.exception("Flow execution failed for inbound message id=%s", inbound_message.id)
        finally:
            # Restore the in-memory object for any later processing in this
            # request. set_committed_value avoids an unnecessary UPDATE.
            set_committed_value(inbound_message, "body", original_body)

    return {"ok": True, "processed": processed, "flows_executed": flows_executed}
