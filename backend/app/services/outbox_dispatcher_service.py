from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.postgres.models import Job, OutboxEvent
from app.services.job_errors import retry_delay
from app.services.job_routing import UnknownJobTypeError


class OutboxDispatcherService:
    """Publishes durable job-enqueue events; Redis is never part of the DB transaction."""
    def __init__(self, sessions: sessionmaker, queue: object, max_attempts: int = 3, reclaim_seconds: int = 300) -> None:
        self.sessions, self.queue, self.max_attempts = sessions, queue, max_attempts
        # A dispatcher that dies between marking `processing` and publishing
        # must not strand the event forever: after this window it becomes
        # claimable again. Re-publishing is safe because JobQueueService.enqueue
        # dedupes jobs that already live in Redis.
        self.reclaim_seconds = reclaim_seconds

    def dispatch_pending(self, limit: int = 100) -> int:
        now = datetime.now(UTC)
        with self.sessions.begin() as session:
            events = list(session.scalars(select(OutboxEvent).where(
                ((OutboxEvent.status.in_(("pending", "retrying"))) & ((OutboxEvent.available_at.is_(None)) | (OutboxEvent.available_at <= now)))
                # Reclaim: `processing` always carries an available_at deadline
                # (set below); one that has expired belongs to a dead dispatcher.
                | ((OutboxEvent.status == "processing") & (OutboxEvent.available_at <= now)),
            ).order_by(OutboxEvent.created_at).limit(limit).with_for_update(skip_locked=True)))
            ids = [event.id for event in events]
            for event in events:
                event.status, event.attempts = "processing", event.attempts + 1
                event.available_at = now + timedelta(seconds=self.reclaim_seconds)
        count = 0
        for event_id in ids:
            with self.sessions() as session:
                event = session.get(OutboxEvent, event_id); job = session.get(Job, event.job_id) if event else None
                if not event:
                    continue
                if not job or job.status not in {"queued", "retrying"}:
                    # The event's job moved on (or vanished) before publish:
                    # there is nothing left to enqueue, and leaving the event in
                    # `processing` would strand it. Close it out explicitly.
                    with self.sessions.begin() as closing:
                        stale = closing.get(OutboxEvent, event_id)
                        if stale and stale.status == "processing":
                            stale.status, stale.processed_at = "completed", datetime.now(UTC)
                            stale.last_error = None if not job else f"job already {job.status}; nothing to publish"
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
