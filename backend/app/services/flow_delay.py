from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.flow_delay_models import FlowDelayJob


def normalized_seconds(config: dict) -> int:
    try:
        seconds = int(config.get("seconds", 60))
    except (TypeError, ValueError):
        seconds = 60
    return max(1, min(seconds, 60 * 60 * 24 * 365))


def schedule_delay(db: Session, channel: str, flow_id: int, conversation_id: int, delay_node_id: int, resume_node_id: int | None, config: dict) -> FlowDelayJob:
    # One pending job per conversation/delay node prevents duplicate resumes if a webhook is retried.
    existing = db.scalar(select(FlowDelayJob).where(
        FlowDelayJob.channel == channel,
        FlowDelayJob.flow_id == flow_id,
        FlowDelayJob.conversation_id == conversation_id,
        FlowDelayJob.delay_node_id == delay_node_id,
        FlowDelayJob.status == "pending",
    ))
    if existing:
        return existing
    job = FlowDelayJob(
        channel=channel,
        flow_id=flow_id,
        conversation_id=conversation_id,
        delay_node_id=delay_node_id,
        resume_node_id=resume_node_id,
        run_at=datetime.utcnow() + timedelta(seconds=normalized_seconds(config)),
        status="pending",
    )
    db.add(job)
    db.flush()
    return job
