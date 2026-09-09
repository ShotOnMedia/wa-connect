"""Serialize Telegram webhook processing per conversation with Redis.

Telegram updates for the same chat may arrive while an earlier flow is awaiting an
external HTTP request.  Flow state is intentionally one session per conversation,
so those executions must not overlap.  A Redis lock spans database commits and
async HTTP awaits, unlike a row lock tied to one SQLAlchemy transaction.
"""

import logging
from contextlib import asynccontextmanager

from redis.asyncio import Redis
from redis.exceptions import LockError, RedisError

from app.core.config import settings

logger = logging.getLogger(__name__)
redis_client = Redis.from_url(settings.redis_url, decode_responses=True)


class TelegramConversationLockError(RuntimeError):
    pass


@asynccontextmanager
async def telegram_conversation_lock(conversation_id: int):
    name = f"wa-connect:telegram:conversation:{int(conversation_id)}"
    lock = redis_client.lock(name, timeout=120, blocking_timeout=60)
    acquired = False
    try:
        try:
            acquired = bool(await lock.acquire())
        except RedisError as exc:
            raise TelegramConversationLockError(
                f"Could not acquire Telegram conversation lock {conversation_id}: {exc}"
            ) from exc
        if not acquired:
            raise TelegramConversationLockError(
                f"Timed out waiting for Telegram conversation {conversation_id}"
            )
        yield
    finally:
        if acquired:
            try:
                await lock.release()
            except LockError:
                logger.warning(
                    "Telegram conversation lock expired before release conversation=%s",
                    conversation_id,
                )
            except RedisError:
                logger.exception(
                    "Could not release Telegram conversation lock conversation=%s",
                    conversation_id,
                )
