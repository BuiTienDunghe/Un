from __future__ import annotations

from rq import Queue, Retry
from rq.job import Job
from redis import Redis


class JobQueueService:
    """Redis transport only; durable job state lives in PostgreSQL."""
    def __init__(self, redis_url: str, prefix: str, retry_intervals: tuple[int, ...] = (10, 30, 90)) -> None:
        self.redis = Redis.from_url(redis_url)
        self.prefix = prefix
        self.retry_intervals = retry_intervals

    def enqueue(self, job_type: str, job_id: str, delay_seconds: int = 0) -> str:
        try:
            Job.fetch(job_id, connection=self.redis)
            return job_id
        except Exception:
            pass
        queue = Queue(f"{self.prefix}:{'ocr' if job_type == 'extract_document' else 'index'}", connection=self.redis)
        function = "app.workers.tasks.extract_document" if job_type == "extract_document" else "app.workers.tasks.index_document"
        # RQ only transports a retry. PostgreSQL remains authoritative for the
        # retryable classification, durable attempt count and available_at.
        kwargs = {
            "job_id": job_id,
            "result_ttl": 0,
            "failure_ttl": 86400,
            "retry": Retry(max=len(self.retry_intervals), interval=self.retry_intervals),
        }
        return (queue.enqueue_in(delay_seconds, function, job_id, **kwargs) if delay_seconds else queue.enqueue(function, job_id, **kwargs)).id
