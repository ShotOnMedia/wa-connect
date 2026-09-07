import json
import mimetypes
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import ContactFieldDefinition, ContactFieldType
from app.services.telegram import TelegramError, download_file, get_file


MAX_IMAGE_BYTES = 25 * 1024 * 1024


def _public_base_url() -> str:
    configured = str(settings.public_base_url or "").strip().rstrip("/")
    if configured:
        return configured
    for origin in settings.cors_origins:
        value = str(origin or "").strip().rstrip("/")
        if value.startswith("https://"):
            return value
    return ""


def _extension(content_type: str | None, fallback: str = ".jpg") -> str:
    mime = str(content_type or "").split(";", 1)[0].strip().lower()
    known = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif", "image/heic": ".heic", "image/heif": ".heif"}
    return known.get(mime) or mimetypes.guess_extension(mime) or fallback


def _store_image(content: bytes, content_type: str | None) -> str:
    if not content:
        raise RuntimeError("Incoming image download returned an empty file")
    if len(content) > MAX_IMAGE_BYTES:
        raise RuntimeError("Incoming image is larger than the 25 MB storage limit")
    mime = str(content_type or "").split(";", 1)[0].strip().lower()
    if mime and not mime.startswith("image/"):
        raise RuntimeError(f"Incoming media is not an image ({mime})")
    root = Path(settings.inbound_media_dir)
    root.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}{_extension(mime)}"
    (root / filename).write_bytes(content)
    base = _public_base_url()
    path = f"{settings.api_prefix}/inbound-media/{filename}"
    return f"{base}{path}" if base else path


def _image_field(db: Session, workspace_id: int, field_id: int | str | None):
    if not field_id:
        return None
    return db.scalar(select(ContactFieldDefinition).where(ContactFieldDefinition.id == int(field_id), ContactFieldDefinition.workspace_id == workspace_id, ContactFieldDefinition.active.is_(True), ContactFieldDefinition.field_type == ContactFieldType.IMAGE))


async def capture_image_field_value(db: Session, conversation, inbound, field_id, channel: str) -> str | None:
    """Persist an incoming image when the Question captures into an Image custom field.

    Returns None when the capture target is not an Image field. Otherwise returns
    a WA Connect-controlled URL suitable for custom fields, variables and webhooks.
    """
    if not _image_field(db, conversation.workspace_id, field_id):
        return None
    channel = str(channel or "").lower()
    try:
        payload = json.loads(inbound.payload_json or "{}")
    except (TypeError, json.JSONDecodeError):
        payload = {}

    if channel == "telegram":
        if str(inbound.message_type or "").lower() != "photo":
            raise RuntimeError("Image custom fields can only capture an incoming Telegram photo")
        message = payload.get("message") or {}
        photos = message.get("photo") or []
        item = photos[-1] if photos else None
        file_id = (item or {}).get("file_id")
        if not file_id:
            raise RuntimeError("Telegram photo does not contain a retrievable file id")
        try:
            info = await get_file(conversation.bot.access_token, file_id)
            file_path = (info or {}).get("file_path")
            if not file_path:
                raise TelegramError("Telegram did not return a file path")
            content, content_type = await download_file(conversation.bot.access_token, file_path)
        except TelegramError as exc:
            raise RuntimeError(f"Could not store incoming Telegram image: {exc}") from exc
        return _store_image(content, content_type or "image/jpeg")

    if channel == "whatsapp":
        if str(inbound.message_type or "").lower() != "image":
            raise RuntimeError("Image custom fields can only capture an incoming WhatsApp image")
        image = payload.get("image") or {}
        media_id = image.get("id")
        if not media_id:
            raise RuntimeError("WhatsApp image does not contain a retrievable media id")
        phone = conversation.phone_number
        if not phone.access_token:
            raise RuntimeError("WhatsApp phone number has no access token")
        headers = {"Authorization": f"Bearer {phone.access_token}"}
        meta_url = f"https://graph.facebook.com/{settings.meta_graph_api_version}/{media_id}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            meta = await client.get(meta_url, headers=headers)
            if meta.is_error:
                raise RuntimeError(f"Could not retrieve WhatsApp image metadata: HTTP {meta.status_code}")
            download_url = (meta.json() or {}).get("url")
            if not download_url:
                raise RuntimeError("Meta did not return a WhatsApp media download URL")
            response = await client.get(download_url, headers=headers)
            if response.is_error:
                raise RuntimeError(f"Could not download incoming WhatsApp image: HTTP {response.status_code}")
        return _store_image(response.content, response.headers.get("content-type") or image.get("mime_type") or "image/jpeg")

    raise RuntimeError(f"Unsupported image capture channel: {channel}")
