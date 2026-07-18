from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest
from fastapi import UploadFile
from sqlalchemy import delete, select

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Document, DocumentChunk, DocumentVersion, IngestionRun
from app.postgres.repositories import InvalidStateTransition, PostgresDocumentRepository
from app.services.postgres_document_service import PostgresDocumentService
from app.services.postgres_retrieval_service import PostgresRetrievalService
from app.stores.qdrant_store import QdrantStore
from app.stores.embedding_cache_store import PostgresEmbeddingCacheStore


POSTGRES_URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="set POSTGRES_TEST_URL to run PostgreSQL integration tests")


class Router:
    models = {"embedding": {"name": "test-embedding"}}
    def embed(self, text: str): return [float(len(text) or 1)], "test-embedding"


class Ocr:
    router = Router()


class Logger:
    def log_request(self, *args: object, **kwargs: object) -> None: pass


class Qdrant:
    def __init__(self, fail: bool = False) -> None: self.points, self.fail = [], fail
    def upsert_chunks(self, document_id, version_id, filename, chunks, vectors, chunk_ids=None):
        if self.fail: raise RuntimeError("qdrant unavailable")
        self.points = [{"document_id": document_id, "version_id": version_id, "chunk_id": chunk_ids[i], "chunk_index": i, "filename": filename, "score": 1.0} for i in range(len(chunks))]
    def search(self, vector, top_k, document_id=None, version_ids=None): return [point for point in self.points if not version_ids or point["version_id"] in version_ids][:top_k]
    def delete_document(self, document_id): self.points = []


@pytest.fixture
def pg_service(tmp_path: Path):
    factory = create_session_factory(create_postgres_engine(str(POSTGRES_URL)))
    qdrant = Qdrant()
    service = PostgresDocumentService(factory, PostgresEmbeddingCacheStore(factory), qdrant, Router(), Logger(), tmp_path / "documents", 64, 8, Ocr())
    yield service, factory, qdrant
    with factory.begin() as session:
        session.execute(delete(Document).where(Document.original_filename.like("phase2-%")))


def _wait(service: PostgresDocumentService, run_id: str) -> dict[str, object]:
    for _ in range(100):
        run = service.get_ingestion(run_id)
        if run["stage"] in {"completed", "failed"}: return run
        time.sleep(0.03)
    raise AssertionError("ingestion did not finish")


def test_upload_index_reindex_and_active_retrieval(pg_service):
    service, factory, qdrant = pg_service
    upload = asyncio.run(service.upload(UploadFile(filename="phase2-a.txt", file=__import__("io").BytesIO(b"first version knowledge"), headers={"content-type": "text/plain"}), 10000))
    assert upload["version_id"] and upload["run_id"]
    first = service.enqueue_index(str(upload["document_id"]))
    assert _wait(service, str(first["id"]))["stage"] == "completed"
    first_status = service.status(str(upload["document_id"]))
    assert first_status["status"] == "indexed"
    second = service.enqueue_index(str(upload["document_id"]))
    assert second["version_id"] != first["version_id"]
    assert _wait(service, str(second["id"]))["stage"] == "completed"
    with factory() as session:
        versions = list(session.scalars(select(DocumentVersion).where(DocumentVersion.document_id == upload["document_id"])))
        assert sorted(version.status for version in versions) == ["active", "superseded"]
        assert len(list(session.scalars(select(DocumentChunk)))) >= 1
    result = PostgresRetrievalService(qdrant, Router(), factory).retrieve("knowledge", 3, str(upload["document_id"]))
    assert result and result[0]["version_id"] == second["version_id"]


def test_failed_reindex_keeps_old_active_version(pg_service):
    service, factory, qdrant = pg_service
    upload = asyncio.run(service.upload(UploadFile(filename="phase2-b.txt", file=__import__("io").BytesIO(b"stable knowledge"), headers={"content-type": "text/plain"}), 10000))
    first = service.enqueue_index(str(upload["document_id"]))
    assert _wait(service, str(first["id"]))["stage"] == "completed"
    qdrant.fail = True
    second = service.enqueue_index(str(upload["document_id"]))
    assert _wait(service, str(second["id"]))["stage"] == "failed"
    status = service.status(str(upload["document_id"]))
    assert status["active_version_id"] == first["version_id"]
    assert status["status"] == "indexed"
    qdrant.fail = False
    retry = service.retry_ingestion(str(second["id"]))
    assert retry["version_id"] == second["version_id"]
    assert _wait(service, str(retry["id"]))["stage"] == "completed"
    with factory() as session:
        assert session.query(DocumentChunk).filter(DocumentChunk.version_id == second["version_id"]).count() == 1


def test_invalid_activation_transition_is_rejected(pg_service):
    service, factory, _ = pg_service
    upload = asyncio.run(service.upload(UploadFile(filename="phase2-c.txt", file=__import__("io").BytesIO(b"transition"), headers={"content-type": "text/plain"}), 10000))
    with factory.begin() as session:
        repository = PostgresDocumentRepository(session)
        with pytest.raises(InvalidStateTransition):
            repository.set_stage(str(upload["run_id"]), "embedding")
        with pytest.raises(InvalidStateTransition):
            repository.activate(str(upload["run_id"]))


def test_versioned_qdrant_points_are_deterministic_and_lightweight():
    class Client:
        def delete(self, **kwargs): pass
        def upsert(self, **kwargs): self.points = kwargs["points"]
    store = QdrantStore.__new__(QdrantStore)
    store.client, store.collection_name, store.retry_count = Client(), "documents", 0
    store._ensure_collection = lambda dimension: None
    chunks = [("private content", 1, "native")]
    store.upsert_chunks("doc_one", "ver_one", "one.txt", chunks, [[0.1]], chunk_ids=["chunk_one"])
    first = store.client.points[0]
    store.upsert_chunks("doc_one", "ver_one", "one.txt", chunks, [[0.1]], chunk_ids=["chunk_one"])
    second = store.client.points[0]
    assert first.id == second.id
    assert first.payload["version_id"] == "ver_one"
    assert first.payload["chunk_id"] == "chunk_one"
    assert "content" not in first.payload
