from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.postgres.models import Job, OutboxEvent
from app.services.job_errors import retry_delay
from app.services.job_routing import UnknownJobTypeError


class OutboxDispatcherService:
    """Publishes durable job-enqueue events; Redis is never part of the DB transaction."""
    def __init__(self, sessions: sessionmaker, queue: object, max_attempts: int = 3) -> None:
        self.sessions, self.queue, self.max_attempts = sessions, queue, max_attempts

    def dispatch_pending(self, limit: int = 100) -> int:
        now = datetime.now(UTC)
        with self.sessions.begin() as session:
            events = list(session.scalars(select(OutboxEvent).where(
                OutboxEvent.status.in_(("pending", "retrying")),
                (OutboxEvent.available_at.is_(None)) | (OutboxEvent.available_at <= now),
            ).order_by(OutboxEvent.created_at).limit(limit).with_for_update(skip_locked=True)))
            ids = [event.id for event in events]
            for event in events:
                event.status, event.attempts = "processing", event.attempts + 1
        count = 0
        for event_id in ids:
            with self.sessions() as session:
                event = session.get(OutboxEvent, event_id); job = session.get(Job, event.job_id) if event else None
                if not event or not job or job.status not in {"queued", "retrying"}:
                    continue
                job_id, job_type = job.id, job.job_type
            try:
                redis_id = self.queue.enqueue(job_type, job_id)
                with self.sessions.begin() as session:
                    event = session.get(OutboxEvent, event_id); job = session.get(Job, job_id)
                    if event and event.status == "processing":
                        event.status, event.redis_job_id, event.published_at, event.processed_at, event.last_error = "completed", redis_id, datetime.now(UTC), datetime.now(UTC), None
                        if job: job.redis_job_id = redis_id
                        count += 1
            except Exception as error:
                with self.sessions.begin() as session:
                    event = session.get(OutboxEvent, event_id)
                    if event and event.status == "processing":
                        if isinstance(error, UnknownJobTypeError):
                            event.status = "failed"
                        elif event.attempts >= self.max_attempts:
                            event.status = "failed"
                        else:
                            event.status = "retrying"; event.available_at = datetime.now(UTC) + timedelta(seconds=retry_delay(event.attempts))
                        event.last_error = str(error)[:1000]
        return count
