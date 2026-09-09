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
    """Return normalized, de-duplicated trigger phrases in display order.

    Accept the native JSON-array representation, a JSON string containing that
    array (seen in some older saves), newline/comma separated legacy values, and a
    normal single keyword.
    """
    raw_value = str(value or "").strip()
    decoded: object = raw_value
    for _ in range(2):
        if not isinstance(decoded, str):
            break
        candidate = decoded.strip()
        if not candidate or candidate[0] not in '["':
            break
        try:
            decoded = json.loads(candidate)
        except (TypeError, ValueError, json.JSONDecodeError):
            break

    if isinstance(decoded, list):
        raw_items = decoded
    else:
        text = str(decoded or "").strip()
        # Newlines are the historical format. A comma-separated fallback also
        # makes manually entered "hello, hi" triggers behave as expected.
        raw_items = text.splitlines()
        if len(raw_items) == 1 and ',' in text and not text.startswith('{'):
            raw_items = text.split(',')

    seen: set[str] = set()
    result: list[str] = []
    for raw in raw_items:
        item = str(raw).strip().strip('"').strip("'").strip()
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

    # Both native matchers resolve these module globals at call time, including
    # the native matcher retained by Default Actions.
    flow_runtime._match_keyword = matches
    telegram_flow_runtime._keyword = matches
    _installed = True
    logger.info("Multiple flow trigger phrase matching installed")
