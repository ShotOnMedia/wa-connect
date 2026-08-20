import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Contact, Conversation, Message, MessageDirection, MessageStatus, WhatsAppPhoneNumber


def _unix_datetime(value: str | int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc).replace(tzinfo=None)


def _extract_body(message: dict) -> str | None:
    message_type = message.get("type", "unknown")
    if message_type == "text":
        return message.get("text", {}).get("body")
    if message_type in {"button", "interactive"}:
        return json.dumps(message.get(message_type), ensure_ascii=False)
    if message_type in {"image", "video", "audio", "document", "sticker", "location", "contacts"}:
        return json.dumps(message.get(message_type), ensure_ascii=False)
    return None


def process_webhook_payload(db: Session, payload: dict) -> int:
    processed = 0

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            metadata = value.get("metadata", {})
            meta_phone_number_id = metadata.get("phone_number_id")
            if not meta_phone_number_id:
                continue

            phone_number = db.scalar(
                select(WhatsAppPhoneNumber).where(WhatsAppPhoneNumber.phone_number_id == meta_phone_number_id)
            )
            if not phone_number:
                continue

            workspace_id = phone_number.account.workspace_id
            contacts_by_wa_id = {
                item.get("wa_id"): item.get("profile", {}).get("name")
                for item in value.get("contacts", [])
                if item.get("wa_id")
            }

            for item in value.get("messages", []):
                meta_message_id = item.get("id")
                if meta_message_id and db.scalar(select(Message.id).where(Message.meta_message_id == meta_message_id)):
                    continue

                wa_id = item.get("from")
                if not wa_id:
                    continue

                contact = db.scalar(
                    select(Contact).where(Contact.workspace_id == workspace_id, Contact.wa_id == wa_id)
                )
                if not contact:
                    contact = Contact(workspace_id=workspace_id, wa_id=wa_id, name=contacts_by_wa_id.get(wa_id))
                    db.add(contact)
                    db.flush()
                elif contacts_by_wa_id.get(wa_id) and contact.name != contacts_by_wa_id[wa_id]:
                    contact.name = contacts_by_wa_id[wa_id]

                conversation = db.scalar(
                    select(Conversation).where(
                        Conversation.phone_number_id == phone_number.id,
                        Conversation.contact_id == contact.id,
                    )
                )
                if not conversation:
                    conversation = Conversation(
                        workspace_id=workspace_id,
                        phone_number_id=phone_number.id,
                        contact_id=contact.id,
                    )
                    db.add(conversation)
                    db.flush()

                timestamp = _unix_datetime(item.get("timestamp"))
                conversation.last_message_at = timestamp or datetime.utcnow()

                db.add(
                    Message(
                        conversation_id=conversation.id,
                        meta_message_id=meta_message_id,
                        direction=MessageDirection.INBOUND,
                        message_type=item.get("type", "unknown"),
                        body=_extract_body(item),
                        payload_json=json.dumps(item, ensure_ascii=False),
                        status=MessageStatus.RECEIVED,
                        whatsapp_timestamp=timestamp,
                    )
                )
                processed += 1

            statuses = value.get("statuses", [])
            for status_payload in statuses:
                meta_message_id = status_payload.get("id")
                status_value = status_payload.get("status")
                if not meta_message_id or not status_value:
                    continue
                message = db.scalar(select(Message).where(Message.meta_message_id == meta_message_id))
                if not message:
                    continue
                try:
                    message.status = MessageStatus(status_value)
                except ValueError:
                    pass

    db.commit()
    return processed
