import httpx


class TelegramError(RuntimeError):
    pass


async def telegram_api(token: str, method: str, payload: dict | None = None):
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(url, json=payload or {})
    except httpx.HTTPError as exc:
        raise TelegramError(f"Telegram request failed: {exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise TelegramError(f"Telegram returned an invalid response ({response.status_code})") from exc

    if not response.is_success or not data.get("ok"):
        description = data.get("description") or f"HTTP {response.status_code}"
        raise TelegramError(description)
    return data.get("result")


async def verify_bot(token: str) -> dict:
    result = await telegram_api(token, "getMe")
    return {
        "bot_id": int(result["id"]),
        "username": result.get("username"),
        "first_name": result.get("first_name"),
        "can_join_groups": bool(result.get("can_join_groups", False)),
        "can_read_all_group_messages": bool(result.get("can_read_all_group_messages", False)),
        "supports_inline_queries": bool(result.get("supports_inline_queries", False)),
    }


async def set_webhook(token: str, webhook_url: str, secret_token: str) -> dict:
    result = await telegram_api(token, "setWebhook", {
        "url": webhook_url,
        "secret_token": secret_token,
        "allowed_updates": ["message"],
        "drop_pending_updates": False,
    })
    return {"registered": bool(result)}


async def webhook_info(token: str) -> dict:
    result = await telegram_api(token, "getWebhookInfo")
    return {
        "url": result.get("url") or "",
        "has_custom_certificate": bool(result.get("has_custom_certificate", False)),
        "pending_update_count": int(result.get("pending_update_count") or 0),
        "last_error_date": result.get("last_error_date"),
        "last_error_message": result.get("last_error_message"),
        "max_connections": result.get("max_connections"),
        "allowed_updates": result.get("allowed_updates") or [],
    }


async def send_text(token: str, chat_id: int, text: str) -> dict:
    return await telegram_api(token, "sendMessage", {"chat_id": chat_id, "text": text})


async def send_media(token: str, chat_id: int, media_type: str, media: str, caption: str | None = None) -> dict:
    """Send Telegram media using a public URL or an existing Telegram file_id."""
    methods = {
        "image": ("sendPhoto", "photo"),
        "photo": ("sendPhoto", "photo"),
        "video": ("sendVideo", "video"),
        "audio": ("sendAudio", "audio"),
        "file": ("sendDocument", "document"),
        "document": ("sendDocument", "document"),
    }
    if media_type not in methods:
        raise TelegramError(f"Unsupported Telegram media type: {media_type}")
    method, field = methods[media_type]
    payload = {"chat_id": chat_id, field: media}
    if caption:
        payload["caption"] = caption
    return await telegram_api(token, method, payload)
