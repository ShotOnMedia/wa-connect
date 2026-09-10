"""Priority keyword flows that may interrupt a waiting interaction.

The normal runtime deliberately gives a waiting Question / Interactive Message /
Location request ownership of the next inbound message.  That is correct for most
keywords, but recovery commands such as help, /help, menu or cancel need an
explicit escape hatch when the subscriber never received the message they are
supposed to answer.

A flow opts in through ``interrupt_active_flow`` on its Trigger node config.  No
keyword is privileged or hard-coded.  The setting is channel-scoped because only
flows targeted to the inbound channel are considered.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from sqlalchemy import select

from app.flow_channel_models import FlowChannelTarget
from app.flow_models import Flow, FlowNode, FlowNodeType, FlowStatus, FlowTriggerType
from app.services.flow_tracking import complete as track_complete, fail as track_fail, start_run
from app.services.multi_trigger import matches

logger = logging.getLogger(__name__)
_installed = False


def _json(value):
    try:
        return json.loads(value or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}


def _interrupt_flow(db, workspace_id: int, channel: str, body: str | None) -> Flow | None:
    """Return the first active interrupt-enabled keyword flow matching body."""
    text = str(body or "").strip()
    if not text:
        return None
    flows = db.scalars(
        select(Flow)
        .join(FlowChannelTarget, FlowChannelTarget.flow_id == Flow.id)
        .where(
            Flow.workspace_id == workspace_id,
            Flow.status == FlowStatus.ACTIVE,
            Flow.trigger_type == FlowTriggerType.KEYWORD,
            FlowChannelTarget.channel == channel,
        )
        .order_by(Flow.id)
    ).all()
    for flow in flows:
        if not matches(flow.trigger_value, text):
            continue
        trigger = db.scalar(
            select(FlowNode)
            .where(FlowNode.flow_id == flow.id, FlowNode.node_type == FlowNodeType.TRIGGER)
            .order_by(FlowNode.id)
            .limit(1)
        )
        if trigger and bool(_json(trigger.config_json).get("interrupt_active_flow")):
            return flow
    return None


def install() -> None:
    global _installed
    if _installed:
        return

    from app.services import flow_runtime as wa
    from app.services import telegram_flow_runtime as tg

    original_tg_resume = tg._resume
    original_tg_track = tg._track
    original_wa_resume = wa._resume
    original_wa_track = wa._track_state

    async def telegram_resume(db, conversation, inbound, session):
        flow = _interrupt_flow(db, conversation.workspace_id, "telegram", getattr(inbound, "body", None))
        if not flow:
            return await original_tg_resume(db, conversation, inbound, session)

        old_flow_id = session.flow_id
        old_run = tg.latest_open_run(old_flow_id, "telegram", conversation.id)
        if old_run:
            track_complete(old_run, f"Flow interrupted by keyword flow: {flow.name}")

        session.status = "reset"
        session.current_node_id = None
        session.waiting_for = None
        session.ended_at = datetime.utcnow()
        session.updated_at = datetime.utcnow()
        db.flush()

        new_run = start_run(flow.id, flow.workspace_id, "telegram", conversation.id, conversation.contact_id, None)
        try:
            result = await tg._run_flow(db, flow, conversation, inbound)
            current = tg._session(db, conversation.id)
            if current:
                original_tg_track(new_run, current)
                current._interrupt_skip_run_id = old_run
            logger.info(
                "Telegram interrupt flow matched conversation=%s previous_flow=%s interrupt_flow=%s keyword=%r",
                conversation.id, old_flow_id, flow.id, getattr(inbound, "body", None),
            )
            return result
        except Exception as exc:
            track_fail(new_run, exc, tg._session(db, conversation.id).current_node_id if tg._session(db, conversation.id) else None)
            logger.exception("Telegram interrupt flow execution failed flow=%s conversation=%s", flow.id, conversation.id)
            # The interrupt was intentionally consumed.  Do not let the outer
            # waiting-flow handler rewrite the already-completed previous run.
            current = tg._session(db, conversation.id)
            if current:
                current._interrupt_skip_run_id = old_run
            return True

    def telegram_track(run_id, session):
        if getattr(session, "_interrupt_skip_run_id", None) == run_id:
            try:
                delattr(session, "_interrupt_skip_run_id")
            except AttributeError:
                pass
            return
        return original_tg_track(run_id, session)

    async def whatsapp_resume(db, conversation, inbound, session):
        flow = _interrupt_flow(db, conversation.workspace_id, "whatsapp", getattr(inbound, "body", None))
        if not flow:
            return await original_wa_resume(db, conversation, inbound, session)

        old_flow_id = session.flow_id
        old_run = wa.latest_open_run(old_flow_id, "whatsapp", conversation.id)
        if old_run:
            track_complete(old_run, f"Flow interrupted by keyword flow: {flow.name}")

        wa._finish(session, wa.FlowSessionStatus.RESET)
        session.updated_at = datetime.utcnow()
        db.flush()

        new_session = wa._start_session(db, conversation, flow, inbound)
        new_run = start_run(flow.id, flow.workspace_id, "whatsapp", conversation.id, conversation.contact_id, new_session.current_node_id)
        try:
            result = await wa._run(db, flow, conversation, new_session)
            original_wa_track(new_run, new_session)
            new_session._interrupt_skip_run_id = old_run
            logger.info(
                "WhatsApp interrupt flow matched conversation=%s previous_flow=%s interrupt_flow=%s keyword=%r",
                conversation.id, old_flow_id, flow.id, getattr(inbound, "body", None),
            )
            return result
        except Exception as exc:
            track_fail(new_run, exc, new_session.current_node_id)
            new_session._interrupt_skip_run_id = old_run
            logger.exception("WhatsApp interrupt flow execution failed flow=%s conversation=%s", flow.id, conversation.id)
            return True

    def whatsapp_track(run_id, session):
        if getattr(session, "_interrupt_skip_run_id", None) == run_id:
            try:
                delattr(session, "_interrupt_skip_run_id")
            except AttributeError:
                pass
            return
        return original_wa_track(run_id, session)

    # Campaign support is installed before this hook, so these wrappers sit at
    # the outer resume boundary and can interrupt campaign waits as well as the
    # native question/button/location waits.
    tg._resume = telegram_resume
    tg._track = telegram_track
    wa._resume = whatsapp_resume
    wa._track_state = whatsapp_track
    _installed = True
    logger.info("Interruptible keyword flow routing installed")
