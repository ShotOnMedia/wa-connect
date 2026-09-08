"""Install the shared subscriber resolver into existing Developer API modules.

Kept as a compatibility shim so existing endpoint contracts stay unchanged
while all body-first subscriber actions share one resolution policy.
"""
from app.api import developer_api_actions, developer_api_body
from app.services.subscriber_resolver import resolve_subscriber


def _resolve(db, ctx, channel, subscriber):
    return resolve_subscriber(db, int(ctx.workspace_id), subscriber, channel)


def install() -> None:
    developer_api_body._resolve_body_subscriber = _resolve
    developer_api_actions._resolve_body_subscriber = _resolve
