"""Multiple keyword/phrase support for flow triggers.

Trigger values remain backward compatible: an existing single keyword is one trigger;
newer flows may store one trigger phrase per line. Matching remains exact,
case-insensitive and whitespace-trimmed.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
_installed = False


def phrases(value: str | None) -> list[str]:
    """Return normalized, de-duplicated trigger phrases in display order."""
    seen: set[str] = set()
    result: list[str] = []
    for raw in str(value or "").splitlines():
        item = raw.strip()
        key = item.casefold()
        if item and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def matches(value: str | None, body: str | None) -> bool:
    incoming = str(body or "").strip().casefold()
    return bool(incoming) and any(item.casefold() == incoming for item in phrases(value))


def install() -> None:
    """Patch both channel runtimes without changing their session/routing semantics."""
    global _installed
    if _installed:
        return
    from app.services import flow_runtime, telegram_flow_runtime

    flow_runtime._match_keyword = matches
    telegram_flow_runtime._keyword = matches
    _installed = True
    logger.info("Multiple flow trigger phrase matching installed")
