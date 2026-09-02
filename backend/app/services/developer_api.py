import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from datetime import datetime

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.developer_api_models import DeveloperApiKey, DeveloperApiRequestLog

ALL_SCOPES = {
    "subscribers:read",
    "subscribers:write",
    "fields:read",
    "fields:write",
    "tags:read",
    "tags:write",
    "conversations:write",
    "flows:read",
    "flows:trigger",
}
DEFAULT_SCOPES = sorted(ALL_SCOPES)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    token = "wac_live_" + secrets.token_urlsafe(32)
    prefix = token[:20]
    return token, prefix, _hash(token)


def scopes_for(key: DeveloperApiKey) -> set[str]:
    try:
        values = json.loads(key.scopes_json or "[]")
    except (TypeError, json.JSONDecodeError):
        values = []
    return {str(v) for v in values if str(v) in ALL_SCOPES}


@dataclass
class DeveloperApiContext:
    key: DeveloperApiKey
    scopes: set[str]

    @property
    def workspace_id(self) -> int:
        return self.key.workspace_id


def require_api_key(
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> DeveloperApiContext:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer API key required")
    token = authorization.split(" ", 1)[1].strip()
    if not token.startswith("wac_live_"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    key = db.scalar(select(DeveloperApiKey).where(DeveloperApiKey.token_hash == _hash(token)))
    now = datetime.utcnow()
    if not key or not key.active or key.revoked_at is not None or (key.expires_at and key.expires_at <= now):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key is inactive or expired")
    key.last_used_at = now
    db.commit()
    return DeveloperApiContext(key=key, scopes=scopes_for(key))


def require_scope(scope: str):
    def dependency(ctx: DeveloperApiContext = Depends(require_api_key)) -> DeveloperApiContext:
        if scope not in ctx.scopes:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"API key requires scope: {scope}")
        return ctx
    return dependency


def log_request(
    db: Session,
    ctx: DeveloperApiContext,
    request: Request,
    status_code: int,
    started_at: float,
    *,
    channel: str | None = None,
    error_message: str | None = None,
) -> None:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    remote = forwarded or (request.client.host if request.client else None)
    db.add(
        DeveloperApiRequestLog(
            workspace_id=ctx.workspace_id,
            api_key_id=ctx.key.id,
            method=request.method,
            path=request.url.path,
            status_code=status_code,
            duration_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
            channel=channel,
            remote_addr=remote,
            error_message=(error_message or "")[:4000] or None,
        )
    )
    db.commit()
