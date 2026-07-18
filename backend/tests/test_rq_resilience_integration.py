"""Phase 3C/3D RQ integration tests with real PostgreSQL and Redis."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import sleep
from uuid import uuid4

from rq import SimpleWorker
from redis.exceptions import ConnectionError as RedisConnectionError
import pytest
from sqlalchemy import select

from app.postgres.models import Document, DocumentChunk, DocumentPage, DocumentVersion, IngestionRun, Job
from app.postgres.repositories import PostgresDocumentRepository
from app.services.job_queue_service import JobQueueService
from app.services.job_recovery_service import JobRecoveryService
from app.services.outbox_dispatcher_service import OutboxDispatcherService
from app.services.postgres_retrieval_service import PostgresRetrievalService
from app.utils.chunking import chunk_pages
from tests.worker_integration_support import FakeEmbeddingRouter, FakeQdrantStore, build_worker_service


def _seed(resources, tmp_path: Path, *, stage: str = "queued", source: bool = True):
    document_id = f"doc_{uuid4().hex}"
    filename = f"{resources['filename_prefix']}-{document_id}.txt"
    path = tmp_path / "documents" / document_id / "original.txt"
    if source:
        path.parent.mkdir(parents=True)
        path.write_text("# Resilience\n\nA document for Redis worker integration testing.", encoding="utf-8")
    with resources["factory"].begin() as session:
        repo = PostgresDocumentRepository(session)
        doc, version, run = repo.create_upload(document_id, filename, f"{document_id}.txt", "text/plain", 1, uuid4().hex * 2)
        doc.status = "processing"
        run.current_stage, run.status = stage, "processing" if stage != "queued" else "queued"
        extract = repo.create_job("extract_document", doc.id, version.id, run.id, 3)
        session.flush()
        return doc.id, version.id, run.id, extract.id


def _run_workers(resources, monkeypatch, tmp_path: Path, *, qdrant=None, router=None, ocr=True, index=True, retry_intervals=(10, 30, 90)):
    qdrant, router = qdrant or FakeQdrantStore(), router or FakeEmbeddingRouter()
    service = build_worker_service(resources, tmp_path, qdrant, router)
    queue = JobQueueService(resources["redis_url"], resources["prefix"], retry_intervals=retry_intervals)
    import app.workers.tasks as tasks
    monkeypatch.setattr(tasks, "_service", lambda: (service, resources["factory"], queue))
    if ocr:
        SimpleWorker([resources["ocr_queue"]], connection=resources["redis"]).work(burst=True, logging_level="WARNING", with_scheduler=True)
        OutboxDispatcherService(resources["factory"], queue).dispatch_pending()
    if index:
        SimpleWorker([resources["index_queue"]], connection=resources["redis"]).work(burst=True, logging_level="WARNING", with_scheduler=True)
    return qdrant, router, queue


def test_duplicate_rq_delivery_executes_logical_job_once(worker_integration_resources, monkeypatch, tmp_path):
    r = worker_integration_resources; doc_id, version_id, run_id, extract_id = _seed(r, tmp_path)
    queue = JobQueueService(r["redis_url"], r["prefix"])
    assert queue.enqueue("extract_document", extract_id) == extract_id
    assert queue.enqueue("extract_document", extract_id) == extract_id
    with r["factory"].begin() as session: session.get(Job, extract_id).redis_job_id = extract_id
    qdrant, _, _ = _run_workers(r, monkeypatch, tmp_path)
    with r["factory"]() as session:
        jobs = list(session.scalars(select(Job).where(Job.ingestion_run_id == run_id)))
        pages = list(session.scalars(select(DocumentPage).where(DocumentPage.version_id == version_id)))
        chunks = list(session.scalars(select(DocumentChunk).where(DocumentChunk.version_id == version_id)))
        assert len(jobs) == 2 and all(job.status == "completed" and job.attempts == 1 for job in jobs)
        assert len(pages) == 1 and len(chunks) == 1
    assert len(qdrant.upserts) == 1 and len({p["id"] for p in qdrant.upserts[0]["points"]}) == 1


def test_real_redis_enqueue_failure_is_reconciled(worker_integration_resources, monkeypatch, tmp_path):
    r = worker_integration_resources; _, _, run_id, extract_id = _seed(r, tmp_path)
    queue = JobQueueService(r["redis_url"], r["prefix"])
    original_execute = queue.redis.execute_command
    monkeypatch.setattr(queue.redis, "execute_command", lambda *args, **kwargs: (_ for _ in ()).throw(RedisConnectionError("injected Redis outage")))
    with pytest.raises(RedisConnectionError):
        queue.enqueue("extract_document", extract_id)
    monkeypatch.setattr(queue.redis, "execute_command", original_execute)
    # The durable transaction pre-dates the transport error and is untouched.
    with r["factory"]() as session:
        job = session.get(Job, extract_id); assert job.status == "queued" and job.redis_job_id is None
    assert JobRecoveryService(r["factory"], queue).reconcile_queued() == 1
    _run_workers(r, monkeypatch, tmp_path)
    with r["factory"]() as session:
        jobs = list(session.scalars(select(Job).where(Job.ingestion_run_id == run_id)))
        assert len(jobs) == 2 and all(job.status == "completed" and job.redis_job_id == job.id for job in jobs)


def test_completed_extraction_without_index_job_is_reconciled(worker_integration_resources, monkeypatch, tmp_path):
    r = worker_integration_resources; doc_id, version_id, run_id, extract_id = _seed(r, tmp_path, stage="chunking")
    with r["factory"].begin() as session:
        repo = PostgresDocumentRepository(session)
        repo.replace_pages(doc_id, version_id, [(1, "Recovered page content", "native")])
        session.get(Job, extract_id).status = "completed"
    queue = JobQueueService(r["redis_url"], r["prefix"])
    assert JobRecoveryService(r["factory"], queue).reconcile_queued() == 1
    _run_workers(r, monkeypatch, tmp_path, ocr=False)
    assert JobRecoveryService(r["factory"], queue).reconcile_queued() == 0
    with r["factory"]() as session:
        run, doc = session.get(IngestionRun, run_id), session.get(Document, doc_id)
        jobs = list(session.scalars(select(Job).where(Job.ingestion_run_id == run_id)))
        assert run.current_stage == "completed" and doc.active_version_id == version_id
        assert len([job for job in jobs if job.job_type == "index_document"]) == 1


def test_non_retryable_worker_error_fails_without_retry(worker_integration_resources, monkeypatch, tmp_path):
    r = worker_integration_resources; doc_id, version_id, run_id, extract_id = _seed(r, tmp_path, source=False)
    with r["factory"].begin() as session:
        repo = PostgresDocumentRepository(session)
        old = DocumentVersion(id=f"ver_old_{uuid4().hex}", document_id=doc_id, version_number=0, status="active")
        session.add(old); session.flush()
        old_chunks = chunk_pages([(1, "Previous active version remains retrievable.", "native")])
        repo.replace_chunks(doc_id, old.id, old_chunks); session.flush()
        old_chunk_ids = [row.id for row in repo.chunks_for_version(old.id)]
        doc = session.get(Document, doc_id); doc.active_version_id, doc.status = old.id, "indexed"
    queue = JobQueueService(r["redis_url"], r["prefix"]); queue.enqueue("extract_document", extract_id)
    qdrant, router, _ = _run_workers(r, monkeypatch, tmp_path, index=False)
    qdrant.upsert_chunks(doc_id, old.id, "previous.txt", old_chunks, [[0.1, 0.2, 0.3]], chunk_ids=old_chunk_ids)
    with r["factory"]() as session:
        job, run, version, doc = session.get(Job, extract_id), session.get(IngestionRun, run_id), session.get(DocumentVersion, version_id), session.get(Document, doc_id)
        assert job.status == "failed" and job.attempts == 1 and run.current_stage == "failed" and version.status == "failed"
        assert doc.status == "indexed" and doc.active_version_id != version_id
    results = PostgresRetrievalService(qdrant, router, r["factory"]).retrieve("previous", 1, doc_id)
    assert results and results[0]["version_id"] != version_id


def test_retryable_worker_error_retries_and_completes(worker_integration_resources, monkeypatch, tmp_path):
    r = worker_integration_resources; _, _, run_id, extract_id = _seed(r, tmp_path)
    qdrant, router = FakeQdrantStore(), FakeEmbeddingRouter()
    service = build_worker_service(r, tmp_path, qdrant, router)
    original_extract, calls = service.extract_for_worker, []

    def flaky_extract(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError("temporary OCR dependency timeout")
        return original_extract(*args, **kwargs)

    monkeypatch.setattr(service, "extract_for_worker", flaky_extract)
    queue = JobQueueService(r["redis_url"], r["prefix"], retry_intervals=(1, 1))
    import app.workers.tasks as tasks
    monkeypatch.setattr(tasks, "_service", lambda: (service, r["factory"], queue))
    queue.enqueue("extract_document", extract_id)
    # RQ schedules the retry from the raised retryable delivery.  A second
    # bounded burst consumes the immediate test retry without sleeping.
    SimpleWorker([r["ocr_queue"]], connection=r["redis"]).work(burst=True, logging_level="WARNING")
    with r["factory"]() as session:
        pending = session.get(Job, extract_id)
        assert pending.status == "retrying" and pending.attempts == 1 and pending.available_at is not None
        assert pending.error_code and pending.error_message
    sleep(1.1)
    SimpleWorker([r["ocr_queue"]], connection=r["redis"]).work(burst=True, logging_level="WARNING", with_scheduler=True)
    OutboxDispatcherService(r["factory"], queue).dispatch_pending()
    SimpleWorker([r["index_queue"]], connection=r["redis"]).work(burst=True, logging_level="WARNING", with_scheduler=True)
    with r["factory"]() as session:
        extract = session.get(Job, extract_id)
        run = session.get(IngestionRun, run_id)
        pages = list(session.scalars(select(DocumentPage).where(DocumentPage.version_id == extract.version_id)))
        chunks = list(session.scalars(select(DocumentChunk).where(DocumentChunk.version_id == extract.version_id)))
        assert extract.status == "completed" and extract.attempts == 2 and len(pages) == 1 and len(chunks) == 1
        assert len({chunk.chunk_uid for chunk in chunks}) == len(chunks)
        assert run.current_stage == "completed"
    assert len(calls) == 2 and len(qdrant.upserts) == 1
    assert len({point["id"] for point in qdrant.upserts[0]["points"]}) == len(qdrant.upserts[0]["points"])


def test_stale_worker_job_is_recovered_and_completed(worker_integration_resources, monkeypatch, tmp_path):
    r = worker_integration_resources; _, _, run_id, extract_id = _seed(r, tmp_path)
    with r["factory"].begin() as session:
        repo = PostgresDocumentRepository(session); job = repo.start_job(extract_id, "worker-a", 1)
        old = datetime.now(UTC) - timedelta(seconds=30); job.lease_expires_at = job.heartbeat_at = old
    monkeypatch.setattr("app.services.job_errors.retry_delay", lambda attempts: 0)
    queue = JobQueueService(r["redis_url"], r["prefix"])
    assert JobRecoveryService(r["factory"], queue).recover_stale() == 1
    with r["factory"].begin() as session:
        repo = PostgresDocumentRepository(session)
        assert not repo.heartbeat(extract_id, "worker-a", 30)
        assert not repo.complete_owned_job(extract_id, "worker-a")
    assert JobRecoveryService(r["factory"], queue).reconcile_queued() == 1
    _run_workers(r, monkeypatch, tmp_path)
    with r["factory"]() as session:
        job, run = session.get(Job, extract_id), session.get(IngestionRun, run_id)
        assert job.status == "completed" and job.attempts == 2 and run.current_stage == "completed"
