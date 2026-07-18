from __future__ import annotations

from datetime import UTC, datetime
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.postgres.models import DocumentVersion, IngestionRun, Job
from app.postgres.repositories import PostgresDocumentRepository


class JobRecoveryService:
    """Explicit Phase-3 recovery command; scheduler/outbox remain Phase 4."""
    def __init__(self, sessions: sessionmaker, queue: object) -> None:
        self.sessions, self.queue = sessions, queue

    def reconcile_queued(self, dry_run: bool = False) -> int:
        count = 0
        with self.sessions.begin() as session:
            repo = PostgresDocumentRepository(session)
            runs = session.scalars(select(IngestionRun).join(DocumentVersion, DocumentVersion.id == IngestionRun.version_id).where(IngestionRun.current_stage == "chunking", IngestionRun.cancel_requested.is_(False), DocumentVersion.status == "staging").with_for_update(skip_locked=True)).all()
            for run in runs:
                extract = session.scalar(select(Job).where(Job.ingestion_run_id == run.id, Job.job_type == "extract_document", Job.status == "completed"))
                if extract:
                    repo.create_job("index_document", run.document_id, run.version_id, run.id, 3)
            session.flush()
            jobs = repo.queued_jobs_without_redis()
            job_ids = [(job.id, job.job_type) for job in jobs if job.status in {"queued", "retrying"} and (job.available_at is None or job.available_at <= datetime.now(UTC))]
        for job_id, job_type in job_ids:
            try:
                if dry_run: count += 1; continue
                redis_id = self.queue.enqueue(job_type, job_id)
                with self.sessions.begin() as session:
                    job = PostgresDocumentRepository(session).get_job(job_id, lock=True)
                    if job and job.status in {"queued", "retrying"}:
                        job.redis_job_id = redis_id
                count += 1
            except Exception:
                continue
        return count

    def recover_stale(self, dry_run: bool = False) -> int:
        now, count = datetime.now(UTC), 0
        with self.sessions.begin() as session:
            jobs = session.scalars(select(Job).where(Job.status == "running", Job.lease_expires_at < now, Job.heartbeat_at < now).with_for_update(skip_locked=True)).all()
            for job in jobs:
                if job.attempts >= job.max_attempts:
                    if dry_run: count += 1; continue
                    job.status, job.worker_id, job.lease_expires_at, job.heartbeat_at, job.redis_job_id = "failed", None, None, None, None
                    PostgresDocumentRepository(session).fail_run(job.ingestion_run_id, "WORKER_STALE", "Worker lease expired")
                else:
                    if dry_run: count += 1; continue
                    from app.services.job_errors import retry_delay
                    from datetime import timedelta
                    job.status, job.worker_id, job.lease_expires_at, job.heartbeat_at, job.redis_job_id, job.available_at = "retrying", None, None, None, None, now + timedelta(seconds=retry_delay(job.attempts))
                count += 1
        return count
