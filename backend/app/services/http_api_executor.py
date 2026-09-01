import json
import re
import time
from datetime import datetime
from typing import Any, Callable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.http_api_models import HttpApi, HttpApiCall
from app.models import ContactFieldDefinition, ContactFieldType, ContactFieldValue
from app.telegram_models import TelegramContactFieldValue


def _loads(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _pairs(items, render):
    result = {}
    for item in items or []:
        key = str(item.get("key") or "").strip()
        if key:
            result[render(key)] = render(str(item.get("value") or ""))
    return result


def _render_value(value: Any, render: Callable[[str], str]):
    if isinstance(value, str):
        return render(value)
    if isinstance(value, list):
        return [_render_value(v, render) for v in value]
    if isinstance(value, dict):
        return {k: _render_value(v, render) for k, v in value.items()}
    return value


def extract_path(data: Any, path: str):
    current = data
    for part in [p for p in re.split(r"\.(?![^\[]*\])", str(path or "").strip()) if p]:
        match = re.fullmatch(r"([^\[]+)(?:\[(\d+)\])?", part)
        if not match:
            return None
        key, index = match.groups()
        if isinstance(current, dict):
            if key not in current:
                return None
            current = current[key]
        else:
            return None
        if index is not None:
            if not isinstance(current, list) or int(index) >= len(current):
                return None
            current = current[int(index)]
    return current


def flatten_paths(data: Any, prefix: str = "", limit: int = 250):
    rows = []

    def walk(value, path):
        if len(rows) >= limit:
            return
        if isinstance(value, dict):
            if not value and path:
                rows.append({"path": path, "preview": "{}"})
            for key, child in value.items():
                walk(child, f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            if not value and path:
                rows.append({"path": path, "preview": "[]"})
            for i, child in enumerate(value[:20]):
                walk(child, f"{path}[{i}]")
        elif path:
            preview = "null" if value is None else str(value)
            rows.append({"path": path, "preview": preview[:180]})

    walk(data, prefix)
    return rows


def _ensure_field(db: Session, workspace_id: int, key: str):
    key = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(key or "").strip()).strip("_")[:80]
    if not key:
        return None
    field = db.scalar(select(ContactFieldDefinition).where(ContactFieldDefinition.workspace_id == workspace_id, ContactFieldDefinition.key == key))
    if field:
        return field
    label = key.replace("_", " ").replace(".", " ").strip().title() or key
    field = ContactFieldDefinition(workspace_id=workspace_id, key=key, label=label[:120], field_type=ContactFieldType.TEXT, required=False, active=True, sort_order=999)
    db.add(field)
    db.flush()
    return field


def _save_mapping(db: Session, channel: str, workspace_id: int, contact_id: int, target_key: str, value: Any):
    field = _ensure_field(db, workspace_id, target_key)
    if not field:
        return False
    text = None if value is None else (json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value))
    if channel == "telegram":
        row = db.scalar(select(TelegramContactFieldValue).where(TelegramContactFieldValue.contact_id == contact_id, TelegramContactFieldValue.field_id == field.id))
        if row:
            row.value_text = text
            row.updated_at = datetime.utcnow()
        else:
            db.add(TelegramContactFieldValue(contact_id=contact_id, field_id=field.id, value_text=text))
    else:
        row = db.scalar(select(ContactFieldValue).where(ContactFieldValue.contact_id == contact_id, ContactFieldValue.field_id == field.id))
        if row:
            row.value_text = text
            row.updated_at = datetime.utcnow()
        else:
            db.add(ContactFieldValue(contact_id=contact_id, field_id=field.id, value_text=text))
    db.flush()
    return True


async def execute_http_api(db: Session, api: HttpApi, render: Callable[[str], str], *, channel: str | None = None, workspace_id: int | None = None, contact_id: int | None = None, flow_run_id: int | None = None, apply_mappings: bool = True):
    started = time.perf_counter()
    requested_url = render(api.endpoint_url)
    status_code = None
    response_text = None
    response_json = None
    final_url = requested_url
    content_type = None
    error = None

    try:
        headers = _pairs(_loads(api.headers_json, []), render)
        params = _pairs(_loads(api.query_json, []), render)
        cookies = _pairs(_loads(api.cookies_json, []), render)
        kwargs = {"headers": headers, "params": params, "cookies": cookies, "timeout": api.timeout_seconds}
        body = _render_value(_loads(api.body_json, None), render)
        body_type = str(api.body_type or "none").lower()
        if body_type == "json" and body is not None:
            kwargs["json"] = body
        elif body_type in {"raw", "text"} and body is not None:
            kwargs["content"] = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
        elif body_type in {"form", "x-www-form-urlencoded"} and body is not None:
            kwargs["data"] = body
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.request(api.method, requested_url, **kwargs)
        status_code = response.status_code
        final_url = str(response.url)
        content_type = response.headers.get("content-type")
        response_text = response.text[:20000]
        try:
            response_json = response.json()
        except Exception:
            response_json = None
        success = 200 <= status_code < 400
        if not success:
            error = f"HTTP {status_code}"
    except Exception as exc:
        success = False
        error = f"{type(exc).__name__}: {exc}"

    duration_ms = int((time.perf_counter() - started) * 1000)
    api.total_calls += 1
    api.total_success += 1 if success else 0
    api.total_error += 0 if success else 1
    api.last_called_at = datetime.utcnow()

    mapped = []
    if success and apply_mappings and response_json is not None and channel and workspace_id and contact_id:
        for mapping in _loads(api.response_mappings_json, []):
            source_path = str(mapping.get("source_path") or "").strip()
            target_key = str(mapping.get("target_key") or "").strip()
            if not source_path or not target_key:
                continue
            value = extract_path(response_json, source_path)
            if _save_mapping(db, channel, workspace_id, contact_id, target_key, value):
                mapped.append({"source_path": source_path, "target_key": target_key, "value": value})

    db.add(HttpApiCall(http_api_id=api.id, flow_run_id=flow_run_id, status_code=status_code, success=success, duration_ms=duration_ms, error_message=error, response_preview=response_text, created_at=datetime.utcnow()))
    db.flush()
    return {"success": success, "status_code": status_code, "method": api.method, "requested_url": requested_url, "final_url": final_url, "content_type": content_type, "duration_ms": duration_ms, "error": error, "response": response_text, "response_json": response_json, "response_paths": flatten_paths(response_json) if response_json is not None else [], "mapped": mapped}
