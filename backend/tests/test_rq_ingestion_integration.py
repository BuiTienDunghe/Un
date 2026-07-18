"""Phase 3B happy-path: real PostgreSQL/Redis/RQ, fake model dependencies."""

from __future__ import annotations

from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from rq import SimpleWorker
from sqlalchemy import select

from app.postgres.models import Document, DocumentChunk, DocumentPage, DocumentVersion, IngestionRun, Job
from app.postgres.repositories import PostgresDocumentRepository
from app.services.job_queue_service import JobQueueService
from app.services.logging_service import LoggingService
from app.services.outbox_dispatcher_service import OutboxDispatcherService
from app.services.postgres_document_service import PostgresDocumentService
from app.services.postgres_retrieval_service import PostgresRetrievalService
from app.stores.embedding_cache_store import PostgresEmbeddingCacheStore
from app.stores.postgres_auxiliary_store import PostgresAuxiliaryStore
from tests.worker_integration_support import FakeEmbeddingRouter, FakeOcrService, FakeQdrantStore


def _worker_service(resources, tmp_path: Path, qdrant: FakeQdrantStore, router: FakeEmbeddingRouter) -> PostgresDocumentService:
    return PostgresDocumentService(
        resources["factory"],
        PostgresEmbeddingCacheStore(resources["factory"]),
        qdrant,
        router,
        LoggingService(PostgresAuxiliaryStore(resources["factory"]), tmp_path / "logs"),
        tmp_path / "documents",
        480,
        80,
        FakeOcrService(),
    )


def test_rq_ingestion_end_to_end(worker_integration_resources, monkeypatch, tmp_path: Path):
    """Workers chain OCR -> Index through Redis and activate only after indexing."""
    resources = worker_integration_resources
    factory = resources["factory"]
    document_id = f"doc_{uuid4().hex}"
    filename = f"{resources['filename_prefix']}.txt"
    source = tmp_path / "documents" / document_id / "original.txt"
    source.parent.mkdir(parents=True)
    source.write_text("# Integration\n\nPostgreSQL and RQ process this document through active version retrieval.", encoding="utf-8")

    with factory.begin() as session:
        repo = PostgresDocumentRepository(session)
        document, version, run = repo.create_upload(
            document_id, filename, f"{document_id}.txt", "text/plain", source.stat().st_size, uuid4().hex * 2
        )
        document.status = "processing"
        extract = repo.create_job("extract_document", document.id, version.id, run.id, 3)
        session.flush()
        extract_id, version_id, run_id = extract.id, version.id, run.id

    qdrant, router = FakeQdrantStore(), FakeEmbeddingRouter()
    service = _worker_service(resources, tmp_path, qdrant, router)
    queue = JobQueueService(resources["redis_url"], resources["prefix"])
    import app.workers.tasks as tasks

    monkeypatch.setattr(tasks, "_service", lambda: (service, factory, queue))
    assert OutboxDispatcherService(factory, queue).dispatch_pending() == 1

    SimpleWorker([resources["ocr_queue"]], connection=resources["redis"]).work(burst=True, logging_level="WARNING")
    assert OutboxDispatcherService(factory, queue).dispatch_pending() == 1
    SimpleWorker([resources["index_queue"]], connection=resources["redis"]).work(burst=True, logging_level="WARNING")

    with factory() as session:
        document = session.get(Document, document_id)
        run = session.get(IngestionRun, run_id)
        versions = list(session.scalars(select(DocumentVersion).where(DocumentVersion.document_id == document_id)))
        pages = list(session.scalars(select(DocumentPage).where(DocumentPage.version_id == version_id)))
        chunks = list(session.scalars(select(DocumentChunk).where(DocumentChunk.version_id == version_id)))
        jobs = list(session.scalars(select(Job).where(Job.ingestion_run_id == run_id)))

        assert document.status == "indexed"
        assert document.active_version_id == version_id
        assert run.current_stage == "completed" and run.status == "completed"
        assert len([item for item in versions if item.status == "active"]) == 1
        assert pages and chunks
        assert all(item.document_id == document_id and item.version_id == version_id for item in [*pages, *chunks])
        assert {job.status for job in jobs} == {"completed"}
        assert not [job for job in jobs if job.status in {"queued", "running"}]

    assert len(qdrant.upserts) == 1
    assert router.calls
    points = qdrant.upserts[0]["points"]
    assert points
    assert [point["id"] for point in points] == [
        str(uuid5(NAMESPACE_URL, f"local-ai-core:{document_id}:{version_id}:{index}"))
        for index in range(len(points))
    ]

    retrieval = PostgresRetrievalService(qdrant, router, factory)
    results = retrieval.retrieve("integration document", top_k=3, document_id=document_id)
    assert results and all(result["version_id"] == version_id for result in results)
    assert "PostgreSQL and RQ" in results[0]["content"]
