import hashlib
import hmac

import httpx

from app.core.config import settings


class WhatsAppError(RuntimeError):
    pass


def verify_meta_signature(raw_body: bytes, signature_header: str | None) -> bool:
    if not settings.meta_app_secret:
        return settings.app_env == "development"
    if not signature_header or not signature_header.startswith("sha256="):
        return False

    supplied = signature_header.removeprefix("sha256=")
    expected = hmac.new(settings.meta_app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(supplied, expected)


async def send_text_message(phone_number_id: str, access_token: str, to: str, text: str) -> dict:
    url = f"https://graph.facebook.com/{settings.meta_graph_api_version}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": text},
    }
    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, json=payload, headers=headers)

    if response.is_error:
        raise WhatsAppError(f"Meta API {response.status_code}: {response.text}")
    return response.json()
