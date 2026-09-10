"""Run a target flow when a flow Button uses the ``start_flow`` action."""
from __future__ import annotations

import re

from app.flow_models import Flow, FlowNodeType, FlowStatus


def resolve_target_flow(db, source_flow: Flow, config: dict) -> Flow:
    raw = config.get("action_value")
    try:
        target_id = int(str(raw or "").strip())
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Start flow button requires a valid target flow ID") from exc
    target = db.get(Flow, target_id)
    if not target:
        raise RuntimeError(f"Start flow target #{target_id} no longer exists")
    if target.workspace_id != source_flow.workspace_id:
        raise RuntimeError(f"Start flow target #{target_id} belongs to another workspace")
    if target.status != FlowStatus.ACTIVE:
        raise RuntimeError(f"Start flow target #{target_id} is not active")
    return target


def install() -> None:
    """Intercept Telegram button replies whose action is Start flow.

    The normal Telegram runtime already validates that the callback belongs to
    the currently waiting Interactive Message.  We preserve that validation,
    then hand the same inbound callback to the selected target flow.  _run_flow
    deliberately reuses/reinitialises the subscriber's existing session, so the
    menu flow is replaced cleanly rather than leaving two active sessions.
    """
    from app.services import telegram_flow_runtime as tg

    if getattr(tg, "_button_start_flow_installed", False):
        return
    original_resume = tg._resume

    async def resume_with_start_flow(db, conversation, inbound, session):
        if session.waiting_for == "button":
            source = db.get(Flow, session.flow_id)
            if source:
                _nodes, by_id, out = tg._graph(db, source.id)
                waiting = by_id.get(session.current_node_id)
                body = str(inbound.body or "").strip()
                match = re.fullmatch(r"wfbtn:(\d+)", body)
                if waiting and tg._is(waiting, FlowNodeType.INTERACTIVE) and match:
                    button = by_id.get(int(match.group(1)))
                    valid = {x.id for x in tg._choices(by_id, out, waiting.id, "buttons") + tg._choices(by_id, out, waiting.id, "list_messages")}
                    if button and button.id in valid:
                        cfg = tg._json(button.config_json)
                        if str(cfg.get("action") or "next").strip().lower() == "start_flow":
                            target = resolve_target_flow(db, source, cfg)
                            return await tg._run_flow(db, target, conversation, inbound)
        return await original_resume(db, conversation, inbound, session)

    tg._resume = resume_with_start_flow
    tg._button_start_flow_installed = True
