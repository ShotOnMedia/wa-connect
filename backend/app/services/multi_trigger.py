"""Multiple keyword/phrase support for flow triggers.

Existing single keywords and legacy newline-separated values remain supported.
The editor stores multiple phrases as a JSON array string because HTML text inputs
strip newline characters. Matching remains exact, case-insensitive and trimmed.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)
_installed = False


def phrases(value: str | None) -> list[str]:
    """Return normalized, de-duplicated trigger phrases in display order."""
    raw_value = str(value or "").strip()
    raw_items: list[object]
    if raw_value.startswith("["):
        try:
            decoded = json.loads(raw_value)
            raw_items = decoded if isinstance(decoded, list) else [raw_value]
        except (TypeError, ValueError, json.JSONDecodeError):
            raw_items = raw_value.splitlines()
    else:
        raw_items = raw_value.splitlines()

    seen: set[str] = set()
    result: list[str] = []
    for raw in raw_items:
        item = str(raw).strip()
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
