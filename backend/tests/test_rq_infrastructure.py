"""Phase 3A smoke coverage for the real RQ transport and worker runtime."""

from __future__ import annotations

from rq import SimpleWorker
from sqlalchemy import select

from app.postgres.models import Job
from app.postgres.repositories import PostgresDocumentRepository
from app.services.job_queue_service import JobQueueService
from app.services.outbox_dispatcher_service import OutboxDispatcherService


class _FakeExtractService:
    """Keeps the smoke test off Ollama/OCR/Qdrant while exercising RQ tasks."""

    def __init__(self, document_id: str, version_id: str) -> None:
        self.document_id = document_id
        self.version_id = version_id

    def extract_for_worker(self, run_id, checkpoint, long_call):
        assert checkpoint()
        return self.document_id, self.version_id

    def mark_cancelled(self, run_id):
        raise AssertionError("the smoke task unexpectedly lost its job lease")


def test_rq_simple_worker_executes_serialized_extract_task(worker_integration_resources, monkeypatch):
    """A real Redis queue serializes and executes the production OCR task import."""
    resources = worker_integration_resources
    factory = resources["factory"]
    filename = f"{resources['filename_prefix']}.txt"
    with factory.begin() as session:
        repo = PostgresDocumentRepository(session)
        document, version, run = repo.create_upload(
            "doc_worker_smoke",
            filename,
            "original.txt",
            "text/plain",
            1,
            "a" * 64,
        )
        job = repo.create_job("extract_document", document.id, version.id, run.id, 3)
        job_id = job.id

    import app.workers.tasks as tasks

    monkeypatch.setattr(
        tasks,
        "_service",
        lambda: (
            _FakeExtractService("doc_worker_smoke", version.id),
            factory,
            JobQueueService(resources["redis_url"], resources["prefix"]),
        ),
    )
    queue = JobQueueService(resources["redis_url"], resources["prefix"])
    assert queue.enqueue("extract_document", job_id) == job_id

    worker = SimpleWorker([resources["ocr_queue"]], connection=resources["redis"])
    worker.work(burst=True, logging_level="WARNING")
    assert OutboxDispatcherService(factory, queue).dispatch_pending() == 1

    with factory() as session:
        extract = session.get(Job, job_id)
        index_jobs = list(
            session.scalars(
                select(Job).where(Job.ingestion_run_id == extract.ingestion_run_id, Job.job_type == "index_document")
            )
        )
        assert extract.status == "completed"
        assert len(index_jobs) == 1
        assert index_jobs[0].status == "queued"
        assert index_jobs[0].redis_job_id == index_jobs[0].id
        assert resources["redis"].exists(f"rq:job:{index_jobs[0].id}")
