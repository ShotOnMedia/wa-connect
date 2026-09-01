import asyncio
import logging
from datetime import datetime, UTC

from sqlalchemy import select

from app.core.database import SessionLocal
# Import the model modules that own tables referenced by FlowDelayJob foreign keys.
# SQLAlchemy must have those tables registered in the shared Base.metadata before
# it can flush/update a FlowDelayJob mapper.
import app.flow_models  # noqa: F401
import app.models  # noqa: F401
import app.telegram_models  # noqa: F401
from app.flow_delay_models import FlowDelayJob

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("flow-delay-worker")


def utcnow():
    # MariaDB columns are currently naive DATETIME values, so generate UTC and
    # strip tzinfo at the persistence boundary while avoiding datetime.utcnow().
    return datetime.now(UTC).replace(tzinfo=None)


async def process_due_jobs():
    with SessionLocal() as db:
        jobs = db.scalars(
            select(FlowDelayJob)
            .where(FlowDelayJob.status == "pending", FlowDelayJob.run_at <= utcnow())
            .order_by(FlowDelayJob.run_at, FlowDelayJob.id)
            .limit(25)
        ).all()
        for job in jobs:
            job_id = job.id
            try:
                job.status = "processing"
                job.attempts += 1
                job.updated_at = utcnow()
                db.commit()

                if job.channel == "telegram":
                    from app.services.telegram_flow_runtime import resume_telegram_delay
                    await resume_telegram_delay(db, job)
                elif job.channel == "whatsapp":
                    from app.services.flow_runtime import resume_whatsapp_delay
                    await resume_whatsapp_delay(db, job)
                else:
                    raise RuntimeError(f"Unsupported delay channel: {job.channel}")

                job.status = "completed"
                job.completed_at = utcnow()
                job.updated_at = utcnow()
                job.last_error = None
                db.commit()
                logger.info("Completed delay job %s channel=%s", job.id, job.channel)
            except Exception as exc:
                db.rollback()
                failed = db.get(FlowDelayJob, job_id)
                if failed:
                    failed.status = "pending" if failed.attempts < 3 else "failed"
                    failed.last_error = str(exc)[:4000]
                    failed.run_at = utcnow()
                    failed.updated_at = utcnow()
                    db.commit()
                logger.exception("Delay job %s failed", job_id)


async def main():
    logger.info("Flow delay worker started")
    while True:
        try:
            await process_due_jobs()
        except Exception:
            # A single database/model error must not kill the worker container.
            logger.exception("Unexpected delay worker iteration failure")
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
