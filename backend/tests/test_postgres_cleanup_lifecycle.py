from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Document, DocumentChunk, DocumentPage, DocumentVersion, IngestionRun, Job, OcrRun, OutboxEvent, RequestLog, new_id
from app.postgres.repositories import InvalidStateTransition, PostgresDocumentRepository
from app.routers.documents import delete_document as delete_document_endpoint
from app.services.postgres_cleanup_service import PostgresCleanupService
from app.services.postgres_document_service import PostgresDocumentService
from app.services.postgres_retrieval_service import PostgresRetrievalService
from app.stores.embedding_cache_store import PostgresEmbeddingCacheStore


URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")


class Router:
    models = {"ocr": {}}
    def embed(self, text: str):
        return [0.1], "test-embedding"


class Logger:
    def log_request(self, *args, **kwargs):
        pass


class Ocr:
    router = Router()


class CleanupQdrant:
    def __init__(self) -> None:
        self.version_deletes: list[tuple[str, str]] = []
        self.document_deletes: list[str] = []
        self.fail_document_delete = False
        self.points: list[dict[str, object]] = []
        self.search_version_filters: list[object] = []

    def delete_document_version(self, document_id: str, version_id: str) -> None:
        self.version_deletes.append((document_id, version_id))
        self.points = [point for point in self.points if point["version_id"] != version_id]

    def delete_document(self, document_id: str) -> None:
        if self.fail_document_delete:
            raise ConnectionError("qdrant unavailable")
        self.document_deletes.append(document_id)
        self.points = [point for point in self.points if point["document_id"] != document_id]

    def search(self, vector, top_k, document_id=None, version_ids=None):
        self.search_version_filters.append(version_ids)
        return [
            point for point in self.points
            if (document_id is None or point["document_id"] == document_id)
            and (not version_ids or point["version_id"] in version_ids)
        ][:top_k]


@pytest.fixture
def lifecycle(tmp_path: Path):
    factory = create_session_factory(create_postgres_engine(str(URL)))
    qdrant = CleanupQdrant()
    documents = tmp_path / "documents"
    yield factory, qdrant, documents
    with factory.begin() as session:
        session.execute(delete(Document).where(Document.original_filename.like("phase5-%")))
        session.execute(delete(OcrRun).where(OcrRun.filename.like("phase5-%")))
        session.execute(delete(RequestLog).where(RequestLog.endpoint.like("/phase7c-%")))


def _chunk(document_id: str, version_id: str, index: int = 0) -> DocumentChunk:
    text = f"knowledge {version_id}"
    return DocumentChunk(
        id=new_id("chunk"), chunk_uid=f"uid-{version_id}-{index}", document_id=document_id,
        version_id=version_id, chunk_index=index, content=text,
        content_hash=hashlib.sha256(text.encode()).hexdigest(), page_start=1, page_end=1,
        section_title="section", block_type="paragraph", extraction_method="native", status="staging",
    )


def _seed(factory, *, superseded_at: datetime | None = None):
    document_id = f"doc_phase5_{os.urandom(5).hex()}"
    with factory.begin() as session:
        repo = PostgresDocumentRepository(session)
        document, first, first_run = repo.create_upload(
            document_id, f"phase5-{os.urandom(4).hex()}.txt", "original.txt", "text/plain", 1,
            os.urandom(32).hex(),
        )
        first.status = "active"
        document.status, document.active_version_id = "indexed", first.id
        second = DocumentVersion(id=new_id("ver"), document_id=document_id, version_number=2, status="superseded", chunking_config={}, superseded_at=superseded_at)
        session.add(second); session.flush()
        first_chunk, second_chunk = _chunk(document_id, first.id), _chunk(document_id, second.id)
        session.add_all((first_chunk, second_chunk))
        session.add_all((
            DocumentPage(id=new_id("page"), document_id=document_id, version_id=first.id, page_number=1, selected_text="active", extraction_method="native", status="completed"),
            DocumentPage(id=new_id("page"), document_id=document_id, version_id=second.id, page_number=1, selected_text="old", extraction_method="native", status="completed"),
        ))
        qdrant_points = [
            {"document_id": document_id, "version_id": first.id, "chunk_id": first_chunk.id, "chunk_index": 0, "filename": document.original_filename, "score": 1.0},
            {"document_id": document_id, "version_id": second.id, "chunk_id": second_chunk.id, "chunk_index": 0, "filename": document.original_filename, "score": 1.0},
        ]
        return document_id, first.id, second.id, first_run.id, qdrant_points


def test_deleting_document_is_excluded_from_dense_retrieval_and_reindex(lifecycle):
    factory, qdrant, documents = lifecycle
    document_id, active_id, _, _, points = _seed(factory)
    qdrant.points = points
    retrieval = PostgresRetrievalService(qdrant, Router(), factory)
    assert retrieval.retrieve("knowledge", 3, document_id)[0]["version_id"] == active_id
    # Exercise the endpoint handler with the PostgreSQL service, without
    # starting the unrelated application lifespan dependencies.
    service = PostgresDocumentService(factory, PostgresEmbeddingCacheStore(factory), qdrant, Router(), Logger(), documents, 64, 8, Ocr())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(document_service=service)))
    delete_document_endpoint(document_id, request)
    with factory() as session:
        assert session.get(Document, document_id).status == "deleting"
        assert session.scalar(select(Job).where(Job.document_id == document_id, Job.job_type == "delete_document"))
    # `active_versions` filters first, so Qdrant candidates cannot reach the
    # PostgreSQL batch chunk loader for a deleting document.
    assert retrieval.retrieve("knowledge", 3, document_id) == []
    assert qdrant.search_version_filters[-1] == []
    with factory.begin() as session:
        with pytest.raises(InvalidStateTransition):
            PostgresDocumentRepository(session).create_reindex(document_id)


def test_active_and_not_due_superseded_versions_are_preserved(lifecycle):
    factory, qdrant, documents = lifecycle
    document_id, active_id, old_id, _, _ = _seed(factory, superseded_at=datetime.now(UTC))
    (documents / document_id).mkdir(parents=True)
    (documents / document_id / "original.txt").write_text("source")
    cleanup = PostgresCleanupService(factory, qdrant, documents, grace_days=7)
    assert cleanup.cleanup_superseded() == 0
    with factory() as session:
        assert session.get(DocumentVersion, active_id).status == "active"
        assert session.get(DocumentVersion, old_id).status == "superseded"
        assert session.scalar(select(DocumentChunk).where(DocumentChunk.version_id == old_id)) is not None
    assert qdrant.version_deletes == []
    assert (documents / document_id / "original.txt").exists()


def test_due_superseded_version_removes_vectors_pages_and_chunks(lifecycle):
    factory, qdrant, documents = lifecycle
    document_id, active_id, old_id, _, _ = _seed(factory, superseded_at=datetime.now(UTC) - timedelta(days=8))
    cleanup = PostgresCleanupService(factory, qdrant, documents, grace_days=7)
    assert cleanup.cleanup_superseded() == 1
    with factory() as session:
        assert session.get(DocumentVersion, active_id).status == "active"
        assert session.get(DocumentVersion, old_id).status == "deleted"
        assert session.scalar(select(DocumentChunk).where(DocumentChunk.version_id == old_id)) is None
        assert session.scalar(select(DocumentPage).where(DocumentPage.version_id == old_id)) is None
    assert qdrant.version_deletes == [(document_id, old_id)]


def test_delete_retries_qdrant_failure_then_is_idempotent(lifecycle):
    factory, qdrant, documents = lifecycle
    document_id, active_id, old_id, _, _ = _seed(factory, superseded_at=datetime.now(UTC) - timedelta(days=8))
    folder = documents / document_id
    folder.mkdir(parents=True); (folder / "original.txt").write_text("source")
    with factory.begin() as session:
        document = session.get(Document, document_id)
        document.status = "deleting"
        job = PostgresDocumentRepository(session).create_document_delete_job(document_id, 3)
        job_id = job.id
    cleanup = PostgresCleanupService(factory, qdrant, documents, grace_days=7)
    qdrant.fail_document_delete = True
    assert cleanup.cleanup_deleting_documents() == 0
    with factory() as session:
        assert session.get(Document, document_id).status == "deleting"
        assert session.get(Job, job_id).status == "retrying"
    qdrant.fail_document_delete = False
    assert cleanup.cleanup_deleting_documents() == 1
    with factory() as session:
        document = session.get(Document, document_id)
        assert document.status == "deleted" and not document.source_available
        assert session.get(DocumentVersion, active_id).status == "deleted"
        assert session.get(DocumentVersion, old_id).status == "deleted"
        assert session.scalar(select(DocumentChunk).where(DocumentChunk.document_id == document_id)) is None
        assert session.get(Job, job_id).status == "completed"
    assert not folder.exists()
    # Missing Qdrant points/files/rows are success conditions on a repeated run.
    assert cleanup.cleanup_deleting_documents() == 0
    with factory() as session:
        assert session.get(Document, document_id).status == "deleted"


def test_postgres_log_and_ocr_retention_execute_only_due_rows(lifecycle):
    factory, qdrant, documents = lifecycle
    now = datetime.now(UTC)
    old_run, new_run = f"ocr-{os.urandom(4).hex()}", f"ocr-{os.urandom(4).hex()}"
    with factory.begin() as session:
        session.add_all((
            RequestLog(endpoint="/phase7c-old", latency_ms=1, status="ok", created_at=now - timedelta(days=8)),
            RequestLog(endpoint="/phase7c-new", latency_ms=1, status="ok", created_at=now),
            OcrRun(id=old_run, filename="phase5-old.pdf", status="completed", model="test", result_json={}, created_at=now - timedelta(days=15), updated_at=now - timedelta(days=15)),
            OcrRun(id=new_run, filename="phase5-new.pdf", status="completed", model="test", result_json={}, created_at=now, updated_at=now),
        ))
    (documents.parent / "ocr_runs" / old_run).mkdir(parents=True)
    cleanup = PostgresCleanupService(factory, qdrant, documents, request_log_retention_days=7, ocr_runs_path=documents.parent / "ocr_runs", ocr_runs_ttl_days=14)
    assert cleanup.cleanup_expired_logs() >= 1
    assert cleanup.cleanup_expired_ocr_runs() == 1
    with factory() as session:
        assert session.scalar(select(RequestLog).where(RequestLog.endpoint == "/phase7c-old")) is None
        assert session.scalar(select(RequestLog).where(RequestLog.endpoint == "/phase7c-new")) is not None
        assert session.get(OcrRun, old_run) is None
        assert session.get(OcrRun, new_run) is not None


def test_source_cleanup_revalidates_and_missing_artifact_is_idempotent(lifecycle):
    factory, qdrant, documents = lifecycle
    document_id, _, _, _, _ = _seed(factory)
    with factory.begin() as session:
        row = session.get(Document, document_id)
        row.status, row.retention_policy, row.pinned, row.source_available = "uploaded", "temporary", False, True
        row.created_at = datetime.now(UTC) - timedelta(days=8)
    cleanup = PostgresCleanupService(factory, qdrant, documents, temporary_sources_ttl_days=7)
    # No directory exists: the executor treats the missing source as an
    # idempotent outcome and finalizes metadata without touching a source-less doc.
    assert cleanup.cleanup_expired_sources() == 1
    assert cleanup.cleanup_expired_sources() == 0
    with factory() as session:
        assert session.get(Document, document_id).source_available is False


def test_pending_outbox_and_reactivated_version_are_revalidation_guards(lifecycle):
    factory, qdrant, documents = lifecycle
    document_id, active_id, old_id, _, _ = _seed(factory, superseded_at=datetime.now(UTC) - timedelta(days=8))
    with factory.begin() as session:
        job = Job(id=new_id("job"), job_type="index_document", document_id=document_id, version_id=old_id, status="queued", idempotency_key=f"phase7c-{os.urandom(4).hex()}")
        session.add(job); session.flush()
        session.add(OutboxEvent(id=new_id("outbox"), event_type="JOB_ENQUEUE_REQUESTED", aggregate_type="job", aggregate_id=job.id, job_id=job.id, idempotency_key=f"phase7c-outbox-{os.urandom(4).hex()}", payload={}, status="pending"))
    cleanup = PostgresCleanupService(factory, qdrant, documents, grace_days=7)
    assert cleanup.cleanup_superseded() == 0
    with factory.begin() as session:
        session.execute(delete(OutboxEvent).where(OutboxEvent.job_id == job.id)); session.delete(session.get(Job, job.id))
        # Candidate changed after its prior plan: activation wins and cleanup
        # must refuse it at the executor's locked revalidation point.
        document = session.get(Document, document_id); old = session.get(DocumentVersion, old_id)
        document.active_version_id, old.status = old_id, "active"
    assert cleanup.cleanup_superseded() == 0
    with factory() as session:
        assert session.get(DocumentVersion, old_id).status == "active"


def test_competing_executors_claim_superseded_version_once(lifecycle):
    factory, qdrant, documents = lifecycle
    document_id, _, old_id, _, _ = _seed(factory, superseded_at=datetime.now(UTC) - timedelta(days=8))
    first = PostgresCleanupService(factory, qdrant, documents, grace_days=7)
    second = PostgresCleanupService(factory, qdrant, documents, grace_days=7)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda service: service.cleanup_superseded(), (first, second)))
    assert sum(outcomes) == 1
    assert qdrant.version_deletes == [(document_id, old_id)]
