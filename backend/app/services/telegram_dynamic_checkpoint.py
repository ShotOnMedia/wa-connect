"""Make Telegram dynamic-list selections durable before downstream nodes run.

A subscriber's button choice is user input and must survive a later node failure.
The Telegram runtime normally saves the selected custom field and then immediately
continues the graph in the same database transaction.  If a downstream HTTP node
raises, the webhook rolls that transaction back, unintentionally erasing the
selection and leaving the flow session at the old waiting node.

This hook checkpoints a successful dynamic selection, then ensures an exception
while resuming a waiting Telegram interaction closes the session after rollback.
Flow-run diagnostics keep the actual run marked failed separately.
"""

from datetime import datetime

from app.services import telegram_flow_runtime as runtime
from app.services import telegram_phone_flow as phone_flow


_original_save_dynamic_selection = runtime.save_dynamic_selection
_original_run_inbound = phone_flow._original_run_inbound


def _checkpoint_dynamic_selection(db, channel, workspace_id, contact_id, config, row):
    saved = _original_save_dynamic_selection(
        db, channel, workspace_id, contact_id, config, row
    )
    if saved and channel == "telegram":
        # The subscriber's choice is an atomic checkpoint.  A failure in the
        # next node must not roll it back.
        db.commit()
    return saved


async def _guarded_run_inbound(db, conversation, inbound):
    try:
        return await _original_run_inbound(db, conversation, inbound)
    except Exception:
        # Return to the most recent committed checkpoint, then close the live
        # session so Live Chat does not continue to display a stale
        # waiting/button state.  The FlowRun has already been marked failed by
        # the core runtime before the exception reaches this wrapper.
        db.rollback()
        session = runtime._session(db, conversation.id)
        if session:
            now = datetime.utcnow()
            session.status = "completed"
            session.current_node_id = None
            session.waiting_for = None
            session.ended_at = now
            session.updated_at = now
            db.commit()
        raise


def install():
    if getattr(runtime, "_telegram_dynamic_checkpoint_installed", False):
        return
    runtime.save_dynamic_selection = _checkpoint_dynamic_selection
    # telegram_phone_flow delegates valid waits to this captured core function,
    # so wrap the captured callable rather than only replacing runtime's public
    # entry point.
    phone_flow._original_run_inbound = _guarded_run_inbound
    runtime._telegram_dynamic_checkpoint_installed = True
