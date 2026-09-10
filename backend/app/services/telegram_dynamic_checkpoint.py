"""Make Telegram subscriber input durable before downstream nodes run.

A subscriber's dynamic-list choice or Question answer is user input and must
survive a later node failure. The Telegram runtime normally saves input and then
immediately continues the graph in the same database transaction. If a downstream
HTTP node raises, the webhook rolls that transaction back, unintentionally erasing
the captured custom field / answer and leaving the flow session at the old wait.

This hook checkpoints successful dynamic selections and User Input answers, then
ensures an exception while resuming a waiting Telegram interaction closes the
session after rollback. Flow-run diagnostics keep the actual run marked failed
separately.
"""

from datetime import datetime

from app.services import telegram_flow_runtime as runtime
from app.services import telegram_phone_flow as phone_flow


_original_save_dynamic_selection = runtime.save_dynamic_selection
_original_record_answer = runtime.record_answer
_original_run_inbound = phone_flow._original_run_inbound


def _checkpoint_dynamic_selection(db, channel, workspace_id, contact_id, config, row):
    saved = _original_save_dynamic_selection(
        db, channel, workspace_id, contact_id, config, row
    )
    if saved and channel == "telegram":
        db.commit()
    return saved


def _checkpoint_question_answer(db, submission, question_node, config, value):
    """Persist the Question answer and its capture field before continuing.

    The core Telegram runtime writes capture_field_id immediately before calling
    record_answer(). Committing here therefore checkpoints both writes together,
    without changing the transaction behaviour of ordinary Set Field nodes.
    """
    answer = _original_record_answer(db, submission, question_node, config, value)
    db.commit()
    return answer


async def _guarded_run_inbound(db, conversation, inbound):
    try:
        return await _original_run_inbound(db, conversation, inbound)
    except Exception:
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
    runtime.record_answer = _checkpoint_question_answer
    # telegram_phone_flow delegates valid waits to this captured core function,
    # so wrap the captured callable rather than only replacing runtime's public
    # entry point.
    phone_flow._original_run_inbound = _guarded_run_inbound
    runtime._telegram_dynamic_checkpoint_installed = True
