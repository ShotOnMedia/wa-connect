import asyncio
import logging
from datetime import datetime

from sqlalchemy import select

from app.core.database import SessionLocal
from app.flow_delay_models import FlowDelayJob

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("flow-delay-worker")


async def process_due_jobs():
    with SessionLocal() as db:
        jobs = db.scalars(
            select(FlowDelayJob)
            .where(FlowDelayJob.status == "pending", FlowDelayJob.run_at <= datetime.utcnow())
            .order_by(FlowDelayJob.run_at, FlowDelayJob.id)
            .limit(25)
        ).all()
        for job in jobs:
            try:
                job.status = "processing"
                job.attempts += 1
                job.updated_at = datetime.utcnow()
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
                job.completed_at = datetime.utcnow()
                job.updated_at = datetime.utcnow()
                job.last_error = None
                db.commit()
                logger.info("Completed delay job %s channel=%s", job.id, job.channel)
            except Exception as exc:
                db.rollback()
                failed = db.get(FlowDelayJob, job.id)
                if failed:
                    failed.status = "pending" if failed.attempts < 3 else "failed"
                    failed.last_error = str(exc)[:4000]
                    failed.run_at = datetime.utcnow()
                    failed.updated_at = datetime.utcnow()
                    db.commit()
                logger.exception("Delay job %s failed", job.id)


async def main():
    logger.info("Flow delay worker started")
    while True:
        await process_due_jobs()
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
