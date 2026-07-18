from __future__ import annotations

import os
import threading
from datetime import UTC, datetime, timedelta

import pytest
from redis import Redis
from sqlalchemy import delete, select

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Document, IngestionRun, Job
from app.postgres.repositories import PostgresDocumentRepository
from app.services.job_queue_service import JobQueueService
from app.services.job_recovery_service import JobRecoveryService

URL = os.getenv("POSTGRES_TEST_URL")
REDIS_URL = os.getenv("REDIS_TEST_URL", "redis://127.0.0.1:6379/15")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")

@pytest.fixture
def resources():
    factory = create_session_factory(create_postgres_engine(str(URL))); prefix = "local-ai:test-concurrency"; redis = Redis.from_url(REDIS_URL); redis.flushdb()
    yield factory, prefix
    redis.flushdb()
    with factory.begin() as session: session.execute(delete(Document).where(Document.original_filename == "concurrency-test.txt"))

def _seed(factory, stale=False):
    with factory.begin() as session:
        repo = PostgresDocumentRepository(session); doc, ver, run = repo.create_upload("doc_con_" + os.urandom(4).hex(), "concurrency-test.txt", "x.txt", "text/plain", 1, os.urandom(32).hex())
        run.current_stage, run.status = "chunking", "processing"; extract = repo.create_job("extract_document", doc.id, ver.id, run.id, 3); extract.status = "completed"
        if stale:
            job = repo.create_job("index_document", doc.id, ver.id, run.id, 3); old = datetime.now(UTC)-timedelta(seconds=30); job.status, job.attempts, job.worker_id, job.lease_expires_at, job.heartbeat_at = "running", 1, "old", old, old; return run.id, job.id
        return run.id, None

def _parallel(function):
    barrier = threading.Barrier(2); results=[]
    def call(): barrier.wait(); results.append(function())
    threads=[threading.Thread(target=call) for _ in range(2)]
    [thread.start() for thread in threads]; [thread.join(10) for thread in threads]; assert all(not thread.is_alive() for thread in threads)
    return results

def test_concurrent_reconciliation_creates_one_index_job(resources):
    factory, prefix = resources; run_id, _ = _seed(factory); _parallel(lambda: JobRecoveryService(factory, JobQueueService(REDIS_URL, prefix)).reconcile_queued())
    with factory() as session:
        jobs=list(session.scalars(select(Job).where(Job.ingestion_run_id == run_id, Job.job_type == "index_document"))); assert len(jobs)==1 and jobs[0].redis_job_id == jobs[0].id

def test_concurrent_stale_recovery_processes_job_once(resources):
    factory, prefix = resources; _, job_id = _seed(factory, stale=True); _parallel(lambda: JobRecoveryService(factory, JobQueueService(REDIS_URL, prefix)).recover_stale())
    with factory() as session:
        job=session.get(Job, job_id); assert job.status == "retrying" and job.attempts == 1

def test_duplicate_redis_enqueue_uses_existing_job(resources):
    factory, prefix = resources; run_id, _ = _seed(factory)
    with factory.begin() as session:
        run=session.get(IngestionRun, run_id); job=PostgresDocumentRepository(session).create_job("index_document", run.document_id, run.version_id, run.id, 3); job_id=job.id
    queue=JobQueueService(REDIS_URL, prefix); _parallel(lambda: queue.enqueue("index_document", job_id))
    assert Redis.from_url(REDIS_URL).exists(f"rq:job:{job_id}")
