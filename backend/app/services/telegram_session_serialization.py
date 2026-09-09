"""Serialize Telegram flow execution for a conversation.

Telegram can deliver a second update while an earlier flow is still awaiting an
external HTTP call.  TelegramFlowSession is intentionally one row per
conversation, so concurrent executions can otherwise overwrite each other's
status/current node.  Locking that row for the lifetime of the webhook flow
transaction preserves inbound ordering and prevents a stale flow from marking a
newer waiting interaction completed.
"""

from sqlalchemy import select

from app.flow_channel_models import TelegramFlowSession
from app.services import telegram_flow_runtime as runtime


def _locked_session(db, conversation_id):
    return db.scalar(
        select(TelegramFlowSession)
        .where(TelegramFlowSession.conversation_id == conversation_id)
        .with_for_update()
    )


def install():
    if getattr(runtime, "_telegram_session_serialization_installed", False):
        return
    runtime._session = _locked_session
    runtime._telegram_session_serialization_installed = True
