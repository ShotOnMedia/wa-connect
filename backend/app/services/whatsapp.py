import hashlib
import hmac

import httpx

from app.core.config import settings


class WhatsAppError(RuntimeError):
    pass


def verify_meta_signature(raw_body: bytes, signature_header: str | None) -> bool:
    if not settings.meta_app_secret:
        return False
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    supplied = signature_header.removeprefix("sha256=")
    if len(supplied) != 64:
        return False
    expected = hmac.new(settings.meta_app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(supplied.lower(), expected)


async def _graph_get(path: str, access_token: str, params: dict | None = None) -> dict:
    url = f"https://graph.facebook.com/{settings.meta_graph_api_version}/{path.lstrip('/')}"
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(url, headers=headers, params=params)
    if response.is_error:
        raise WhatsAppError(f"Meta API {response.status_code}: {response.text}")
    return response.json()


async def _send_message(phone_number_id: str, access_token: str, payload: dict) -> dict:
    url = f"https://graph.facebook.com/{settings.meta_graph_api_version}/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, json=payload, headers=headers)
    if response.is_error:
        raise WhatsAppError(f"Meta API {response.status_code}: {response.text}")
    return response.json()


async def verify_whatsapp_connection(waba_id: str, phone_number_id: str, access_token: str) -> dict:
    phone = await _graph_get(phone_number_id, access_token, {"fields": "id,display_phone_number,verified_name,quality_rating,platform_type,code_verification_status"})
    account = await _graph_get(waba_id, access_token, {"fields": "id,name"})
    numbers = await _graph_get(waba_id + "/phone_numbers", access_token, {"fields": "id"})
    belongs_to_waba = any(str(item.get("id")) == str(phone_number_id) for item in numbers.get("data", []))
    if not belongs_to_waba:
        raise WhatsAppError("The supplied phone number does not belong to the supplied WhatsApp Business Account")
    return {"waba_id": str(account.get("id", waba_id)), "account_name": account.get("name"), "phone_number_id": str(phone.get("id", phone_number_id)), "display_phone_number": phone.get("display_phone_number"), "verified_name": phone.get("verified_name"), "quality_rating": phone.get("quality_rating"), "platform_type": phone.get("platform_type"), "code_verification_status": phone.get("code_verification_status")}


async def send_text_message(phone_number_id: str, access_token: str, to: str, text: str) -> dict:
    return await _send_message(phone_number_id, access_token, {
        "messaging_product": "whatsapp", "recipient_type": "individual", "to": to,
        "type": "text", "text": {"preview_url": False, "body": text},
    })


async def send_media_message(phone_number_id: str, access_token: str, to: str, media_type: str, media: str, caption: str | None = None, filename: str | None = None) -> dict:
    """Send media by public URL or an existing Meta media ID."""
    wa_type = {"image": "image", "video": "video", "audio": "audio", "file": "document", "document": "document"}.get(media_type)
    if not wa_type:
        raise WhatsAppError(f"Unsupported WhatsApp media type: {media_type}")
    media_obj = {"link": media} if media.startswith(("http://", "https://")) else {"id": media}
    if caption and wa_type != "audio":
        media_obj["caption"] = caption
    if filename and wa_type == "document":
        media_obj["filename"] = filename
    return await _send_message(phone_number_id, access_token, {
        "messaging_product": "whatsapp", "recipient_type": "individual", "to": to,
        "type": wa_type, wa_type: media_obj,
    })
