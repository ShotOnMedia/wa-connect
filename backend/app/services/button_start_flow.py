"""Run a target flow when a flow Button uses the ``start_flow`` action.

The visual builder stores the target flow ID in ``action_value``.  Keep the
implementation here so both channel runtimes share the same validation rules
without adding another database model/migration.
"""
from __future__ import annotations

from app.flow_models import Flow, FlowStatus


def resolve_target_flow(db, source_flow: Flow, config: dict, channel: str) -> Flow:
    raw = config.get("action_value")
    try:
        target_id = int(str(raw or "").strip())
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Start flow button requires a valid target flow ID") from exc

    target = db.get(Flow, target_id)
    if not target:
        raise RuntimeError(f"Start flow target #{target_id} no longer exists")
    if target.workspace_id != source_flow.workspace_id:
        raise RuntimeError(f"Start flow target #{target_id} belongs to another workspace")
    if target.status != FlowStatus.ACTIVE:
        raise RuntimeError(f"Start flow target #{target_id} is not active")

    # Channel targeting is checked by the runtime's normal graph/session path;
    # the source flow itself already establishes the channel context here.
    return target


def install() -> None:
    """Patch the small BUTTON branches in both runtimes.

    Direct helper hooks are installed rather than replacing the runtime files.
    This keeps the feature isolated and makes it safe alongside the existing
    campaign/default-action/dynamic-list runtime patches.
    """
    from app.services import flow_runtime as wa
    from app.services import telegram_flow_runtime as tg

    if getattr(tg, "_button_start_flow_installed", False):
        return

    tg._button_start_flow_resolver = resolve_target_flow
    wa._button_start_flow_resolver = resolve_target_flow
    tg._button_start_flow_installed = True
    wa._button_start_flow_installed = True
