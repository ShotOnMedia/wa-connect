import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Contact, Conversation, Message, MessageDirection, MessageStatus, WhatsAppPhoneNumber
from app.services.service_window import open_service_window


def _unix_datetime(value: str | int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc).replace(tzinfo=None)


def _extract_body(message: dict) -> str | None:
    message_type = message.get("type", "unknown")
    if message_type == "text":
        return message.get("text", {}).get("body")
    if message_type == "button":
        button = message.get("button") or {}
        return button.get("payload") or button.get("text")
    if message_type == "interactive":
        interactive = message.get("interactive") or {}
        reply_type = interactive.get("type")
        if reply_type == "button_reply":
            reply = interactive.get("button_reply") or {}
            return reply.get("id") or reply.get("title")
        if reply_type == "list_reply":
            reply = interactive.get("list_reply") or {}
            return reply.get("id") or reply.get("title")
        return json.dumps(interactive, ensure_ascii=False)
    if message_type in {"image", "video", "audio", "document", "sticker", "location", "contacts"}:
        return json.dumps(message.get(message_type), ensure_ascii=False)
    return None


def process_webhook_payload(db: Session, payload: dict) -> tuple[int, list[Message]]:
    processed = 0
    inbound_messages: list[Message] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            metadata = value.get("metadata", {})
            meta_phone_number_id = metadata.get("phone_number_id")
            if not meta_phone_number_id:
                continue
            phone_number = db.scalar(select(WhatsAppPhoneNumber).where(WhatsAppPhoneNumber.phone_number_id == meta_phone_number_id))
            if not phone_number:
                continue
            workspace_id = phone_number.account.workspace_id
            contacts_by_wa_id = {item.get("wa_id"): item.get("profile", {}).get("name") for item in value.get("contacts", []) if item.get("wa_id")}
            for item in value.get("messages", []):
                meta_message_id = item.get("id")
                if meta_message_id and db.scalar(select(Message.id).where(Message.meta_message_id == meta_message_id)):
                    continue
                wa_id = item.get("from")
                if not wa_id:
                    continue
                contact = db.scalar(select(Contact).where(Contact.workspace_id == workspace_id, Contact.wa_id == wa_id))
                if not contact:
                    contact = Contact(workspace_id=workspace_id, wa_id=wa_id, name=contacts_by_wa_id.get(wa_id)); db.add(contact); db.flush()
                elif contacts_by_wa_id.get(wa_id) and contact.name != contacts_by_wa_id[wa_id]:
                    contact.name = contacts_by_wa_id[wa_id]
                conversation = db.scalar(select(Conversation).where(Conversation.phone_number_id == phone_number.id, Conversation.contact_id == contact.id))
                if not conversation:
                    conversation = Conversation(workspace_id=workspace_id, phone_number_id=phone_number.id, contact_id=contact.id); db.add(conversation); db.flush()
                timestamp = _unix_datetime(item.get("timestamp")); inbound_at = timestamp or datetime.utcnow(); conversation.last_message_at = inbound_at; open_service_window(conversation, inbound_at)
                message = Message(conversation_id=conversation.id, meta_message_id=meta_message_id, direction=MessageDirection.INBOUND, message_type=item.get("type", "unknown"), body=_extract_body(item), payload_json=json.dumps(item, ensure_ascii=False), status=MessageStatus.RECEIVED, whatsapp_timestamp=timestamp)
                db.add(message); db.flush(); inbound_messages.append(message); processed += 1
            for status_payload in value.get("statuses", []):
                meta_message_id = status_payload.get("id"); status_value = status_payload.get("status")
                if not meta_message_id or not status_value:
                    continue
                message = db.scalar(select(Message).where(Message.meta_message_id == meta_message_id))
                if not message:
                    continue
                try: message.status = MessageStatus(status_value)
                except ValueError: pass
    db.commit()
    return processed, inbound_messages
