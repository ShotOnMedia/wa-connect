import httpx
class TelegramError(RuntimeError):pass
async def telegram_api(token,method,payload=None):
    url=f"https://api.telegram.org/bot{token}/{method}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:r=await client.post(url,json=payload or {})
    except httpx.HTTPError as exc:raise TelegramError(f"Telegram request failed: {exc}") from exc
    try:data=r.json()
    except ValueError as exc:raise TelegramError(f"Telegram returned an invalid response ({r.status_code})") from exc
    if not r.is_success or not data.get("ok"):raise TelegramError(data.get("description") or f"HTTP {r.status_code}")
    return data.get("result")
async def verify_bot(token):
    r=await telegram_api(token,"getMe");return {"bot_id":int(r["id"]),"username":r.get("username"),"first_name":r.get("first_name"),"can_join_groups":bool(r.get("can_join_groups",False)),"can_read_all_group_messages":bool(r.get("can_read_all_group_messages",False)),"supports_inline_queries":bool(r.get("supports_inline_queries",False))}
async def set_webhook(token,webhook_url,secret_token):return {"registered":bool(await telegram_api(token,"setWebhook",{"url":webhook_url,"secret_token":secret_token,"allowed_updates":["message","callback_query"],"drop_pending_updates":False}))}
async def webhook_info(token):
    r=await telegram_api(token,"getWebhookInfo");return {"url":r.get("url") or "","has_custom_certificate":bool(r.get("has_custom_certificate",False)),"pending_update_count":int(r.get("pending_update_count") or 0),"last_error_date":r.get("last_error_date"),"last_error_message":r.get("last_error_message"),"max_connections":r.get("max_connections"),"allowed_updates":r.get("allowed_updates") or []}
async def send_text(token,chat_id,text):return await telegram_api(token,"sendMessage",{"chat_id":chat_id,"text":text})
async def send_buttons(token,chat_id,text,buttons):
    rows=[]
    for b in buttons:
        label=str(b.get("label") or "Button")[:64];url=str(b.get("url") or "").strip();rows.append([{"text":label,"url":url}] if url else [{"text":label,"callback_data":str(b.get("value") or b.get("id") or label)[:64]}])
    return await telegram_api(token,"sendMessage",{"chat_id":chat_id,"text":text,"reply_markup":{"inline_keyboard":rows}})
async def send_product_card(token,chat_id,name,description="",price="",currency="",image="",url="",button_text="View product"):
    parts=[str(name).strip()]
    if price:parts.append(f"{str(currency).strip()} {str(price).strip()}".strip())
    if description:parts.append(str(description).strip())
    caption="\n\n".join(p for p in parts if p);markup={"inline_keyboard":[[{"text":str(button_text or "View product")[:64],"url":str(url)}]]} if url else None
    if image:
        payload={"chat_id":chat_id,"photo":image,"caption":caption[:1024]}
        if markup:payload["reply_markup"]=markup
        return await telegram_api(token,"sendPhoto",payload)
    payload={"chat_id":chat_id,"text":caption or "Product"}
    if markup:payload["reply_markup"]=markup
    return await telegram_api(token,"sendMessage",payload)
async def answer_callback(token,callback_query_id):await telegram_api(token,"answerCallbackQuery",{"callback_query_id":callback_query_id})
async def send_media(token,chat_id,media_type,media,caption=None):
    methods={"image":("sendPhoto","photo"),"photo":("sendPhoto","photo"),"video":("sendVideo","video"),"audio":("sendAudio","audio"),"file":("sendDocument","document"),"document":("sendDocument","document")}
    if media_type not in methods:raise TelegramError(f"Unsupported Telegram media type: {media_type}")
    method,field=methods[media_type];payload={"chat_id":chat_id,field:media}
    if caption:payload["caption"]=caption
    return await telegram_api(token,method,payload)
