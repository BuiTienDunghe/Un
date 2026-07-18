from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Document, DocumentVersion, IngestionRun, Job
from app.postgres.repositories import PostgresDocumentRepository
from app.services.job_recovery_service import JobRecoveryService


URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL for PostgreSQL reconciliation tests")


class FakeQueue:
    def __init__(self) -> None: self.jobs: dict[str, str] = {}; self.calls: list[tuple[str, str]] = []
    def enqueue(self, job_type: str, job_id: str, delay_seconds: int = 0) -> str:
        self.calls.append((job_type, job_id)); self.jobs.setdefault(job_id, job_id); return self.jobs[job_id]


@pytest.fixture
def database():
    factory = create_session_factory(create_postgres_engine(str(URL)))
    suffix = "reconcile-test"
    yield factory
    with factory.begin() as session:
        session.execute(delete(Document).where(Document.original_filename.like(f"{suffix}%")))


def _seed(factory, *, run_cancel=False, version_status="staging", extract_status="completed"):
    with factory.begin() as session:
        repo = PostgresDocumentRepository(session)
        document, version, run = repo.create_upload("doc_reconcile_" + os.urandom(4).hex(), "reconcile-test.txt", "test.txt", "text/plain", 1, os.urandom(32).hex())
        run.current_stage, run.status, run.cancel_requested = "chunking", "processing", run_cancel
        version.status = version_status
        extract = repo.create_job("extract_document", document.id, version.id, run.id, 3)
        extract.status = extract_status
        session.flush()
        return document.id, version.id, run.id, extract.id


def _jobs(factory, run_id: str):
    with factory() as session:
        return list(session.scalars(select(Job).where(Job.ingestion_run_id == run_id)))


def test_reconcile_creates_missing_index_job(database):
    _, version_id, run_id, _ = _seed(database)
    queue = FakeQueue(); service = JobRecoveryService(database, queue)
    assert service.reconcile_queued() == 1
    jobs = _jobs(database, run_id); index = [job for job in jobs if job.job_type == "index_document"]
    assert len(index) == 1 and index[0].idempotency_key == f"index_document:{version_id}:{run_id}"
    service.reconcile_queued()
    assert len([job for job in _jobs(database, run_id) if job.job_type == "index_document"]) == 1


def test_reconcile_enqueues_postgres_job_without_redis_mapping(database):
    document_id, version_id, run_id, _ = _seed(database)
    with database.begin() as session:
        job = PostgresDocumentRepository(session).create_job("index_document", document_id, version_id, run_id, 3); job.available_at = datetime.now(UTC) - timedelta(seconds=1)
        job_id = job.id
    queue = FakeQueue(); JobRecoveryService(database, queue).reconcile_queued()
    job = next(job for job in _jobs(database, run_id) if job.id == job_id)
    assert job.redis_job_id == job_id and queue.calls.count(("index_document", job_id)) == 1


def test_reconcile_repairs_mapping_when_redis_job_already_exists(database):
    document_id, version_id, run_id, _ = _seed(database)
    with database.begin() as session:
        job = PostgresDocumentRepository(session).create_job("index_document", document_id, version_id, run_id, 3); job_id = job.id
    queue = FakeQueue(); queue.jobs[job_id] = job_id
    JobRecoveryService(database, queue).reconcile_queued()
    job = next(job for job in _jobs(database, run_id) if job.id == job_id)
    assert job.redis_job_id == job_id and len(queue.jobs) == 1


def test_reconcile_enqueues_due_retrying_job(database):
    document_id, version_id, run_id, _ = _seed(database)
    with database.begin() as session:
        job = PostgresDocumentRepository(session).create_job("index_document", document_id, version_id, run_id, 3)
        job.status, job.available_at, job.attempts = "retrying", datetime.now(UTC) - timedelta(seconds=1), 2; job_id = job.id
    queue = FakeQueue(); JobRecoveryService(database, queue).reconcile_queued()
    job = next(job for job in _jobs(database, run_id) if job.id == job_id)
    assert job.redis_job_id == job_id and job.attempts == 2
    with database.begin() as session: session.get(Job, job_id).redis_job_id, session.get(Job, job_id).available_at = None, datetime.now(UTC) + timedelta(hours=1)
    assert JobRecoveryService(database, queue).reconcile_queued() == 0
