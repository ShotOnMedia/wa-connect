"""Default Action runtime hooks.

Default Actions are deliberately lower priority than an interaction already waiting
for a reply/location/button and lower priority than explicit keyword/first-message
flow triggers. They therefore only claim otherwise-unhandled inbound events.
"""
from app.services.default_actions import attach_inbound_values, default_flow
from app.services import telegram_flow_runtime as telegram_runtime

_original_telegram_matching = telegram_runtime._matching_flows
_original_telegram_run_flow = telegram_runtime._run_flow


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


def install():
    if getattr(telegram_runtime, "_default_actions_installed", False):
        return
    telegram_runtime._matching_flows = _telegram_matching
    telegram_runtime._run_flow = _telegram_run_flow
    telegram_runtime._default_actions_installed = True
