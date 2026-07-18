"""Reusable fakes and bounded polling for Phase-3 worker integration tests.

These test doubles match the narrow interfaces consumed by the existing
``PostgresDocumentService``.  They intentionally sit behind the service's
already-injected OCR/router/Qdrant constructor dependencies; no production
model configuration is changed for tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic, sleep
from types import SimpleNamespace
from typing import Callable, TypeVar
from uuid import NAMESPACE_URL, uuid5

from app.services.ocr_service import OcrResult
from app.services.logging_service import LoggingService
from app.services.postgres_document_service import PostgresDocumentService
from app.stores.embedding_cache_store import PostgresEmbeddingCacheStore
from app.stores.postgres_auxiliary_store import PostgresAuxiliaryStore


class FakeOcrService:
    def __init__(self, pages: dict[int, str] | None = None) -> None:
        self.pages = pages or {1: "fake OCR page"}
        self.router = SimpleNamespace(models={"ocr": {"enabled": True, "dpi": 200}})
        self.calls: list[tuple[int, ...]] = []

    def recognize_pdf_pages(self, source, dpi: int, page_numbers: list[int]):
        self.calls.append(tuple(page_numbers))
        return [
            (number, OcrResult(self.pages[number], "fake-ocr", "test", False))
            for number in page_numbers
        ]


class FakeEmbeddingRouter:
    def __init__(self) -> None:
        self.models = {"embedding": {"name": "fake-embedding"}}
        self.calls: list[str] = []

    def embed(self, text: str):
        self.calls.append(text)
        return [0.1, 0.2, 0.3], "fake-embedding"


@dataclass
class FakeQdrantStore:
    upserts: list[dict] = field(default_factory=list)

    def upsert_chunks(self, document_id, version_id, filename, chunks, vectors, *, chunk_ids):
        points = [
            {
                "id": str(uuid5(NAMESPACE_URL, f"local-ai-core:{document_id}:{version_id}:{index}")),
                "document_id": document_id,
                "version_id": version_id,
                "filename": filename,
                "chunk_id": chunk_ids[index],
                "chunk_index": index,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "section_title": chunk.section_title,
                "extraction_method": chunk.extraction_method,
            }
            for index, chunk in enumerate(chunks)
        ]
        self.upserts.append(
            {
                "document_id": document_id,
                "version_id": version_id,
                "chunk_ids": list(chunk_ids),
                "vectors": list(vectors),
                "points": points,
            }
        )

    def search(self, vector, top_k: int, document_id=None, version_ids=None):
        points = [point for upsert in self.upserts for point in upsert["points"]]
        if document_id:
            ids = {document_id} if isinstance(document_id, str) else set(document_id)
            points = [point for point in points if point["document_id"] in ids]
        if version_ids is not None:
            points = [point for point in points if point["version_id"] in set(version_ids)]
        return [{"score": 1.0, **point} for point in points[:top_k]]


T = TypeVar("T")


def wait_until(
    predicate: Callable[[], T | None],
    *,
    timeout_seconds: float = 5,
    interval_seconds: float = 0.05,
    diagnostics: Callable[[], str] | None = None,
) -> T:
    """Poll with a bounded timeout and actionable state for later E2E tests."""
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        result = predicate()
        if result:
            return result
        sleep(interval_seconds)
    detail = diagnostics() if diagnostics else "no diagnostic callback supplied"
    raise AssertionError(f"worker integration test timed out after {timeout_seconds}s: {detail}")


def wait_for_pipeline_state(resources: dict, run_id: str, predicate: Callable[[], T | None], *, timeout_seconds: float = 5) -> T:
    """Bounded polling with PostgreSQL/RQ state diagnostics on timeout."""
    def diagnostics() -> str:
        from rq.job import Job as RqJob
        from rq.registry import DeferredJobRegistry, FailedJobRegistry, ScheduledJobRegistry, StartedJobRegistry
        from app.postgres.models import DocumentVersion, IngestionRun, Job
        with resources["factory"]() as session:
            run = session.get(IngestionRun, run_id)
            jobs = list(session.query(Job).filter(Job.ingestion_run_id == run_id))
            version = session.get(DocumentVersion, run.version_id) if run else None
            database = {
                "run": None if not run else {"status": run.status, "stage": run.current_stage, "cancel": run.cancel_requested},
                "version": None if not version else version.status,
                "jobs": [{"id": j.id, "status": j.status, "attempts": j.attempts, "worker": j.worker_id, "heartbeat": j.heartbeat_at, "lease": j.lease_expires_at, "error": j.error_message} for j in jobs],
            }
        queues = []
        for queue in (resources["ocr_queue"], resources["index_queue"]):
            registries = [StartedJobRegistry(queue=queue), FailedJobRegistry(queue=queue), ScheduledJobRegistry(queue=queue), DeferredJobRegistry(queue=queue)]
            queues.append({"queue": queue.name, "length": len(queue), "registries": {type(reg).__name__: reg.get_job_ids() for reg in registries}})
        return f"database={database}; redis={queues}"
    return wait_until(predicate, timeout_seconds=timeout_seconds, diagnostics=diagnostics)


def build_worker_service(resources: dict, tmp_path: Path, qdrant: FakeQdrantStore, router: FakeEmbeddingRouter) -> PostgresDocumentService:
    """Create the real document service with only external model stores faked."""
    return PostgresDocumentService(
        resources["factory"], PostgresEmbeddingCacheStore(resources["factory"]), qdrant, router,
        LoggingService(PostgresAuxiliaryStore(resources["factory"]), tmp_path / "logs"), tmp_path / "documents",
        480, 80, FakeOcrService(),
    )
