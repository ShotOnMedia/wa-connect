from datetime import datetime, timedelta

from app.models import Conversation

SERVICE_WINDOW_HOURS = 24


class ServiceWindowClosed(RuntimeError):
    pass


def open_service_window(conversation: Conversation, inbound_at: datetime | None = None) -> None:
    """Open/refresh the WhatsApp customer service window from an inbound user message."""
    inbound_at = inbound_at or datetime.utcnow()
    conversation.last_customer_message_at = inbound_at
    conversation.service_window_expires_at = inbound_at + timedelta(hours=SERVICE_WINDOW_HOURS)


def service_window_open(conversation: Conversation, now: datetime | None = None) -> bool:
    now = now or datetime.utcnow()
    return bool(conversation.service_window_expires_at and conversation.service_window_expires_at > now)


def require_service_window(conversation: Conversation) -> None:
    if not service_window_open(conversation):
        raise ServiceWindowClosed(
            "The 24-hour WhatsApp customer service window has expired. "
            "A template message is required before free-form messaging can resume."
        )
