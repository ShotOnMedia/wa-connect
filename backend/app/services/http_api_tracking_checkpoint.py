"""Commit HTTP API call diagnostics before flow tracking touches FlowRun.

HttpApiCall has a foreign key to FlowRun.  Leaving a freshly inserted call row
uncommitted can keep an InnoDB lock on the parent flow_runs row while the
best-effort tracking session tries to update that same run.  The result is a
lock-wait timeout even though the actual HTTP request has already completed.

HTTP execution already uses transaction checkpoints around external network
I/O.  Make the completed call record, response mappings and API counters a
second durable checkpoint before flow diagnostics update the run row.
"""

from app.services import flow_http_diagnostics


_original_execute_http_api = flow_http_diagnostics.execute_http_api


async def _checkpointed_execute_http_api(db, *args, **kwargs):
    result = await _original_execute_http_api(db, *args, **kwargs)
    # Persist HttpApiCall (including its FlowRun FK), response mappings and API
    # counters, releasing any parent-row FK lock before track_event/complete/fail
    # opens its independent observability session.
    db.commit()
    return result


def install() -> None:
    if getattr(flow_http_diagnostics, "_http_api_tracking_checkpoint_installed", False):
        return
    flow_http_diagnostics.execute_http_api = _checkpointed_execute_http_api
    flow_http_diagnostics._http_api_tracking_checkpoint_installed = True
