from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Document, Job
from app.postgres.repositories import PostgresDocumentRepository
from app.services.job_recovery_service import JobRecoveryService

URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL for stale recovery tests")

class Queue:
    def __init__(self): self.calls = []
    def enqueue(self, kind, job_id, delay_seconds=0): self.calls.append((kind, job_id, delay_seconds)); return job_id

@pytest.fixture
def factory():
    value = create_session_factory(create_postgres_engine(str(URL))); yield value
    with value.begin() as session: session.execute(delete(Document).where(Document.original_filename == "stale-test.txt"))

def _stale(factory, attempts=1, max_attempts=3):
    with factory.begin() as session:
        repo = PostgresDocumentRepository(session)
        doc, version, run = repo.create_upload("doc_stale_" + os.urandom(4).hex(), "stale-test.txt", "x.txt", "text/plain", 1, os.urandom(32).hex())
        job = repo.create_job("extract_document", doc.id, version.id, run.id, max_attempts)
        old = datetime.now(UTC) - timedelta(seconds=30)
        job.status, job.attempts, job.worker_id, job.lease_expires_at, job.heartbeat_at, job.redis_job_id = "running", attempts, "old-worker", old, old, job.id
        return job.id, run.id, version.id, doc.id

def test_stale_running_job_moves_to_retrying(factory):
    job_id, run_id, _, _ = _stale(factory)
    queue = Queue(); assert JobRecoveryService(factory, queue).recover_stale() == 1
    with factory() as session:
        job = session.get(Job, job_id)
        assert job.status == "retrying" and job.worker_id is None and job.lease_expires_at is None and job.heartbeat_at is None and job.redis_job_id is None
        assert job.available_at > datetime.now(UTC)
        assert PostgresDocumentRepository(session).get_run(run_id).current_stage != "failed"

def test_stale_job_exhausted_attempts_fails_staging_run(factory):
    job_id, run_id, version_id, _ = _stale(factory, attempts=3, max_attempts=3)
    JobRecoveryService(factory, Queue()).recover_stale()
    with factory() as session:
        repo = PostgresDocumentRepository(session)
        assert session.get(Job, job_id).status == "failed"
        assert repo.get_run(run_id).current_stage == "failed"
        assert session.get(__import__("app.postgres.models", fromlist=["DocumentVersion"]).DocumentVersion, version_id).status == "failed"

def test_non_stale_job_is_not_recovered(factory):
    job_id, _, _, _ = _stale(factory)
    with factory.begin() as session:
        job = session.get(Job, job_id); job.lease_expires_at = datetime.now(UTC) + timedelta(hours=1)
    assert JobRecoveryService(factory, Queue()).recover_stale() == 0
    with factory() as session: assert session.get(Job, job_id).status == "running"

def test_old_worker_loses_ownership_after_recovery(factory):
    job_id, _, _, _ = _stale(factory)
    JobRecoveryService(factory, Queue()).recover_stale()
    with factory.begin() as session:
        repo = PostgresDocumentRepository(session)
        assert not repo.heartbeat(job_id, "old-worker", 60)
        assert not repo.worker_owns_job(job_id, "old-worker")

def test_deterministic_redis_id_after_stale_retry(factory):
    job_id, _, _, _ = _stale(factory)
    queue = Queue(); JobRecoveryService(factory, queue).recover_stale()
    with factory.begin() as session: session.get(Job, job_id).available_at = datetime.now(UTC) - timedelta(seconds=1)
    JobRecoveryService(factory, queue).reconcile_queued()
    assert any(call[1] == job_id for call in queue.calls)
