import json


def choices(config):
    """Return normalized Question choices stored in the existing pattern field."""
    if str(config.get("reply_type") or "").lower() not in {"choice", "multiple_choice"}:
        return []
    raw = config.get("pattern") or "[]"
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return []
    result = []
    for item in data or []:
        if isinstance(item, str):
            label = value = item.strip()
        elif isinstance(item, dict):
            label = str(item.get("label") or "").strip()
            value = str(item.get("value") if item.get("value") not in (None, "") else label).strip()
        else:
            continue
        if label and value:
            result.append({"label": label[:80], "value": value[:200]})
    return result[:10]


def validate_choice(config, body):
    opts = choices(config)
    value = str(body or "").strip()
    for option in opts:
        if value == option["value"] or value.casefold() == option["label"].casefold():
            return True, option["value"], None
    allowed = ", ".join(option["label"] for option in opts)
    error = str(config.get("validation_error") or "").strip()
    return False, None, error or (f"Please choose one of: {allowed}." if allowed else "Please choose one of the available options.")


def install():
    """Install choice-aware sending/validation without duplicating the flow engines."""
    from app.flow_models import FlowNode, FlowNodeType, FlowSession
    from app.flow_channel_models import TelegramFlowSession
    from app.services import flow_runtime as wa
    from app.services import telegram_flow_runtime as tg
    from app.services.whatsapp import send_reply_buttons
    from app.services.telegram import send_buttons

    wa_send_text = wa._send_text
    wa_validate = wa._validate
    tg_send = tg._send
    tg_validate = tg._validate

    async def wa_choice_send(db, conversation, text):
        session = db.scalar(wa.select(FlowSession).where(FlowSession.conversation_id == conversation.id))
        node = db.get(FlowNode, session.current_node_id) if session and session.current_node_id else None
        cfg = wa._json(node.config_json) if node and node.node_type == FlowNodeType.QUESTION else {}
        opts = choices(cfg)
        if opts and wa._can_send(conversation):
            rendered = wa.render_whatsapp(db, conversation, text or "Choose an option").strip() or "Choose an option"
            phone = conversation.phone_number
            response = await send_reply_buttons(phone.phone_number_id, phone.access_token, conversation.contact.wa_id, rendered, opts[:3])
            wa._store_outbound(db, conversation, response, "interactive", rendered)
            return
        await wa_send_text(db, conversation, text)

    def wa_choice_validate(config, inbound):
        if str(config.get("reply_type") or "").lower() in {"choice", "multiple_choice"}:
            return validate_choice(config, inbound.body)
        return wa_validate(config, inbound)

    async def tg_choice_send(db, conversation, text):
        session = db.scalar(tg.select(TelegramFlowSession).where(TelegramFlowSession.conversation_id == conversation.id))
        node = db.get(FlowNode, session.current_node_id) if session and session.current_node_id else None
        cfg = tg._json(node.config_json) if node and tg._is(node, FlowNodeType.QUESTION) else {}
        opts = choices(cfg)
        if opts:
            rendered = tg._render(db, conversation, text or "Choose an option").strip() or "Choose an option"
            buttons = [{"label": o["label"], "id": node.id, "value": o["value"]} for o in opts]
            response = await send_buttons(conversation.bot.access_token, conversation.chat_id, rendered, buttons)
            tg._store(db, conversation, response, "interactive", rendered)
            return
        await tg_send(db, conversation, text)

    def tg_choice_validate(config, inbound):
        if str(config.get("reply_type") or "").lower() in {"choice", "multiple_choice"}:
            return validate_choice(config, inbound.body)
        return tg_validate(config, inbound)

    wa._send_text = wa_choice_send
    wa._validate = wa_choice_validate
    tg._send = tg_choice_send
    tg._validate = tg_choice_validate
