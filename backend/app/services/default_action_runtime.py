"""Default Action runtime hooks.

Default Actions are deliberately lower priority than an interaction already waiting
for a reply/location/button and lower priority than explicit keyword/first-message
flow triggers. They therefore only claim otherwise-unhandled inbound events.
"""
from app.services.default_actions import attach_inbound_values, default_flow
from app.services import flow_runtime as whatsapp_runtime
from app.services import telegram_flow_runtime as telegram_runtime

_original_telegram_matching = telegram_runtime._matching_flows
_original_telegram_run_flow = telegram_runtime._run_flow
_original_whatsapp_matching = whatsapp_runtime._matching_flows
_original_whatsapp_run = whatsapp_runtime._run


def _telegram_matching(db, conversation, inbound):
    matches = _original_telegram_matching(db, conversation, inbound)
    if matches:
        return matches
    flow = default_flow(db, conversation.workspace_id, "telegram", inbound)
    return [flow] if flow else []


async def _telegram_run_flow(db, flow, conversation, inbound):
    attach_inbound_values(inbound, "telegram")
    conversation._default_action_inbound = inbound
    try:
        return await _original_telegram_run_flow(db, flow, conversation, inbound)
    finally:
        try:
            delattr(conversation, "_default_action_inbound")
        except AttributeError:
            pass


def _whatsapp_matching(db, conversation, inbound):
    matches = _original_whatsapp_matching(db, conversation, inbound)
    if matches:
        return matches
    flow = default_flow(db, conversation.workspace_id, "whatsapp", inbound)
    if flow:
        # _run() does not receive the inbound message, so carry its transient
        # Default Action context on the conversation for variable rendering.
        attach_inbound_values(inbound, "whatsapp")
        conversation._default_action_inbound = inbound
        conversation._default_action_flow_id = flow.id
        return [flow]
    return []


async def _whatsapp_run(db, flow, conversation, session, start=None):
    """Preserve the native WhatsApp _run(..., start=None) call signature.

    The runtime calls _run with four arguments for a newly matched flow and with a
    fifth start-node argument when resuming inside the graph.  The Default Action
    wrapper must support both forms; otherwise a newly matched Default Action raises
    TypeError before its first node can execute.
    """
    try:
        return await _original_whatsapp_run(db, flow, conversation, session, start)
    finally:
        if getattr(conversation, "_default_action_flow_id", None) == flow.id:
            try:
                delattr(conversation, "_default_action_inbound")
            except AttributeError:
                pass
            try:
                delattr(conversation, "_default_action_flow_id")
            except AttributeError:
                pass


def install():
    if not getattr(telegram_runtime, "_default_actions_installed", False):
        telegram_runtime._matching_flows = _telegram_matching
        telegram_runtime._run_flow = _telegram_run_flow
        telegram_runtime._default_actions_installed = True
    if not getattr(whatsapp_runtime, "_default_actions_installed", False):
        whatsapp_runtime._matching_flows = _whatsapp_matching
        whatsapp_runtime._run = _whatsapp_run
        whatsapp_runtime._default_actions_installed = True
