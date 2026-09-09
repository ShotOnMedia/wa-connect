"""Queue Developer API Telegram flow triggers behind an executing flow.

A Telegram conversation intentionally has one flow-session row.  External systems
can request the next flow from inside an HTTP node of the current flow, so that
request cannot block waiting for the current graph without deadlocking the HTTP
call.  Queue it in Redis and drain it once the current inbound execution reaches a
stable state.
"""

import json
import logging
from datetime import datetime, timezone

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings

logger = logging.getLogger(__name__)
redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
MAX_PENDING = 20


def _key(conversation_id: int) -> str:
    return f"wa-connect:telegram:flow-queue:{int(conversation_id)}"


async def enqueue_telegram_flow(conversation_id: int, flow_id: int, restart: bool = True) -> int:
    """Append a flow request and return its 1-based queue position.

    Exact duplicate requests already waiting in the queue are coalesced.  This
    makes retries from an external caller idempotent enough for the hand-off use
    case without discarding different requested flows.
    """
    key = _key(conversation_id)
    item = {
        "flow_id": int(flow_id),
        "restart": bool(restart),
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        pending = await redis_client.lrange(key, 0, MAX_PENDING - 1)
        for index, raw in enumerate(pending):
            try:
                existing = json.loads(raw)
            except Exception:
                continue
            if int(existing.get("flow_id") or 0) == int(flow_id) and bool(existing.get("restart", True)) == bool(restart):
                return index + 1
        if len(pending) >= MAX_PENDING:
            raise RuntimeError("Telegram flow queue is full for this subscriber")
        await redis_client.rpush(key, json.dumps(item, separators=(",", ":")))
        await redis_client.expire(key, 3600)
        return len(pending) + 1
    except RedisError as exc:
        raise RuntimeError(f"Could not queue Telegram flow: {exc}") from exc


async def drain_telegram_flow_queue(db, conversation) -> int:
    """Run queued flows FIFO until one waits or the queue becomes empty."""
    # Imports stay local to avoid a module cycle with external_flow_trigger.
    from app.flow_models import Flow, FlowStatus
    from app.services.external_flow_trigger import trigger_telegram_flow
    from app.services.telegram_flow_runtime import _session as telegram_session

    key = _key(conversation.id)
    started = 0
    while started < MAX_PENDING:
        session = telegram_session(db, conversation.id)
        if session and session.status == "active":
            break
        try:
            raw = await redis_client.lpop(key)
        except RedisError:
            logger.exception("Could not read Telegram flow queue conversation=%s", conversation.id)
            break
        if not raw:
            break
        try:
            item = json.loads(raw)
            flow_id = int(item.get("flow_id"))
            restart = bool(item.get("restart", True))
        except Exception:
            logger.warning("Discarding malformed Telegram flow queue item conversation=%s raw=%r", conversation.id, raw)
            continue
        flow = db.get(Flow, flow_id)
        if not flow or flow.status != FlowStatus.ACTIVE or int(flow.workspace_id) != int(conversation.workspace_id):
            logger.warning("Discarding unavailable queued Telegram flow conversation=%s flow=%s", conversation.id, flow_id)
            continue
        try:
            await trigger_telegram_flow(db, flow, conversation, restart)
            db.commit()
            started += 1
            logger.info("Started queued Telegram flow conversation=%s flow=%s", conversation.id, flow_id)
        except RuntimeError as exc:
            db.rollback()
            # If another execution became active, preserve this request at the
            # head of the queue for the next stable-state drain.
            if "currently executing" in str(exc):
                try:
                    await redis_client.lpush(key, raw)
                    await redis_client.expire(key, 3600)
                except RedisError:
                    logger.exception("Could not restore Telegram flow queue item conversation=%s", conversation.id)
                break
            logger.exception("Queued Telegram flow rejected conversation=%s flow=%s", conversation.id, flow_id)
        except Exception:
            db.rollback()
            logger.exception("Queued Telegram flow failed conversation=%s flow=%s", conversation.id, flow_id)
        session = telegram_session(db, conversation.id)
        if session and session.status in {"active", "waiting"}:
            break
    return started
