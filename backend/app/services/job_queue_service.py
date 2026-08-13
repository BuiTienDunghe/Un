from __future__ import annotations

from rq import Queue, Retry
from rq.job import Job
from redis import Redis

from app.services.job_routing import resolve_job_route


class JobQueueService:
    """Redis transport only; durable job state lives in PostgreSQL."""
    def __init__(
        self,
        redis_url: str,
        prefix: str,
        retry_intervals: tuple[int, ...] = (10, 30, 90),
        *,
        memory_queue_name: str = "memory_extract",
    ) -> None:
        self.redis = Redis.from_url(redis_url)
        self.prefix = prefix
        self.retry_intervals = retry_intervals
        self.memory_queue_name = memory_queue_name

    def enqueue(self, job_type: str, job_id: str, delay_seconds: int = 0) -> str:
        route = resolve_job_route(
            job_type,
            memory_queue_name=self.memory_queue_name,
        )
        try:
            existing = Job.fetch(job_id, connection=self.redis)
        except Exception:
            existing = None
        if existing is not None:
            try:
                status = str(existing.get_status(refresh=False))
            except Exception:
                status = ""
            # Only a still-live transport counts as already enqueued. A failed
            # or finished RQ job lingering in a registry (failure_ttl) must not
            # swallow a durable re-enqueue of the same job ID.
            if status in {"queued", "started", "scheduled", "deferred"}:
                return job_id
            try:
                existing.delete()
            except Exception:
                pass
        queue = Queue(
            f"{self.prefix}:{route.queue_name}",
            connection=self.redis,
        )
        # RQ only transports a retry. PostgreSQL remains authoritative for the
        # retryable classification, durable attempt count and available_at.
        kwargs = {
            "job_id": job_id,
            "result_ttl": 0,
            "failure_ttl": 86400,
            "retry": Retry(max=len(self.retry_intervals), interval=self.retry_intervals),
        }
        return (
            queue.enqueue_in(
                delay_seconds,
                route.task_path,
                job_id,
                **kwargs,
            )
            if delay_seconds
            else queue.enqueue(route.task_path, job_id, **kwargs)
        ).id
