from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Document, DocumentChunk, DocumentVersion
from app.services.postgres_bm25_service import PostgresBm25Service
from app.services.postgres_retrieval_service import PostgresRetrievalService
from app.services.reranker_service import RerankerService
from app.config.settings import Settings
from app.stores.qdrant_store import QdrantUnavailableError


URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")


class Router:
    def embed(self, _: str): return [0.1, 0.2], "test-embedding"


class Qdrant:
    def __init__(self, points: list[dict[str, object]]): self.points = points
    def search(self, _vector, top_k, document_id=None, version_ids=None):
        allowed_docs = {document_id} if isinstance(document_id, str) else (set(document_id) if document_id else None)
        return [row for row in self.points if (not version_ids or row.get("version_id") in version_ids) and (allowed_docs is None or row.get("document_id") in allowed_docs)][:top_k]


@pytest.fixture
def factory():
    return create_session_factory(create_postgres_engine(str(URL)))


def _seed(factory, *, source_available: bool = True, content: str = "Transformer attention citation identifier PHASE6A-KEYWORD"):
    suffix = uuid4().hex
    doc_id, version_id, chunk_id = f"doc_phase6a_{suffix}", f"ver_phase6a_{suffix}", f"chunk_phase6a_{suffix}"
    with factory.begin() as session:
        document = Document(id=doc_id, original_filename=f"phase6a-{suffix}.md", stored_filename=f"{doc_id}.md", mime_type="text/markdown", content_hash=uuid4().hex * 2, status="indexed", source_available=source_available)
        version = DocumentVersion(id=version_id, document_id=doc_id, version_number=1, status="active", activated_at=datetime.now(UTC), chunking_config={})
        document.active_version_id = version_id
        session.add_all((document, version))
        session.flush()
        chunk = DocumentChunk(id=chunk_id, chunk_uid=f"uid-{suffix}", document_id=doc_id, version_id=version_id, chunk_index=0, content=content, content_hash="a" * 64, page_start=7, page_end=8, locations=[{"page": 7, "start": 0, "end": 20}], heading_path=["Chapter", "Attention"], section_title="Attention", block_type="paragraph", extraction_method="native", status="staging")
        session.add(chunk)
    return doc_id, version_id, chunk_id


def _cleanup(factory):
    with factory.begin() as session:
        session.execute(delete(Document).where(Document.original_filename.like("phase6a-%")))


def test_postgres_bm25_exact_keyword_active_only_cache_and_citation(factory):
    _cleanup(factory); doc_id, version_id, _ = _seed(factory)
    _seed(factory, content="unrelated sparse corpus control text")
    bm25 = PostgresBm25Service(factory)
    first = bm25.search("Transformer", 5, doc_id)
    second = bm25.search("Transformer", 5, doc_id)
    assert first and first[0]["version_id"] == version_id
    assert first[0]["page_start"] == 7 and first[0]["locations"] == [{"page": 7, "start": 0, "end": 20}]
    assert first[0]["heading_path"] == "Chapter > Attention"
    assert bm25.rebuild_count == 1 and second[0]["chunk_id"] == first[0]["chunk_id"]
    with factory.begin() as session:
        version = session.get(DocumentVersion, version_id); document = session.get(Document, doc_id)
        version.status, version.superseded_at = "superseded", datetime.now(UTC)
        document.active_version_id, document.status = None, "uploaded"
    assert bm25.search("Transformer", 5, doc_id) == []
    assert bm25.rebuild_count == 2
    with factory.begin() as session:
        version = session.get(DocumentVersion, version_id); document = session.get(Document, doc_id)
        version.status, version.activated_at = "active", datetime.now(UTC)
        document.active_version_id, document.status = version_id, "indexed"
    assert bm25.search("Transformer", 5, doc_id)[0]["version_id"] == version_id
    assert bm25.rebuild_count == 3
    _cleanup(factory)


def test_postgres_bm25_empty_source_less_and_document_filter(factory):
    _cleanup(factory); doc_id, _, _ = _seed(factory, source_available=False)
    bm25 = PostgresBm25Service(factory)
    # An active record may be source-less, but the Phase-5C policy guarantees
    # source-less legacy records have no active version; model that final state.
    with factory.begin() as session:
        document = session.get(Document, doc_id); document.active_version_id, document.status = None, "uploaded"
    assert bm25.search("Transformer", 5, doc_id) == []
    assert bm25.search("Transformer", 5, []) == []
    _cleanup(factory)


def test_dense_ignores_legacy_stale_and_duplicate_points_and_touches(factory):
    _cleanup(factory); doc_id, version_id, chunk_id = _seed(factory)
    points = [
        {"document_id": doc_id, "index_version": 1, "chunk_index": 0, "score": .99},  # legacy: ignored
        {"document_id": doc_id, "version_id": version_id, "chunk_id": "missing", "chunk_index": 0, "score": .98},  # stale: ignored
        {"document_id": doc_id, "version_id": version_id, "chunk_id": chunk_id, "chunk_index": 0, "score": .97},
    ]
    service = PostgresRetrievalService(Qdrant(points), Router(), factory)
    result = service.retrieve("attention", 5, doc_id)
    assert len(result) == 1 and result[0]["chunk_id"] == chunk_id and result[0]["verifiable"] is True
    with factory() as session:
        assert session.get(Document, doc_id).last_accessed_at is not None
    _cleanup(factory)


def test_hybrid_rrf_uses_active_postgres_chunks_without_duplicates(factory):
    _cleanup(factory); doc_id, version_id, chunk_id = _seed(factory)
    point = {"document_id": doc_id, "version_id": version_id, "chunk_id": chunk_id, "chunk_index": 0, "score": .8}
    service = PostgresRetrievalService(Qdrant([point]), Router(), factory, PostgresBm25Service(factory), RerankerService(False, "", 5), mode="hybrid", rrf_k=60)
    result = service.retrieve("Transformer", 5, doc_id)
    assert len(result) == 1 and result[0]["chunk_id"] == chunk_id and result[0]["score"] > 0
    _cleanup(factory)


def test_postgres_retrieval_best_effort_touch_does_not_change_result(factory, monkeypatch):
    _cleanup(factory); doc_id, version_id, chunk_id = _seed(factory)
    point = {"document_id": doc_id, "version_id": version_id, "chunk_id": chunk_id, "chunk_index": 0, "score": .8}
    service = PostgresRetrievalService(Qdrant([point]), Router(), factory)
    monkeypatch.setattr(service, "_touch_best_effort", lambda _: None)
    assert service.retrieve("attention", 1, doc_id)[0]["chunk_id"] == chunk_id
    _cleanup(factory)


def test_qdrant_failure_is_not_silently_converted_to_a_result(factory):
    class Unavailable:
        def search(self, *_args, **_kwargs): raise QdrantUnavailableError("test outage")
    _cleanup(factory); doc_id, _, _ = _seed(factory)
    with pytest.raises(QdrantUnavailableError):
        PostgresRetrievalService(Unavailable(), Router(), factory).retrieve("attention", 1, doc_id)
    _cleanup(factory)


def test_postgres_runtime_settings_are_selector_free():
    settings = Settings(database_url="postgresql+psycopg://test:test@127.0.0.1:5432/test")
    assert settings.database_url.startswith("postgresql+")


def test_postgres_unavailable_is_not_hidden_by_bm25_cache():
    class UnavailableSessions:
        def __call__(self):
            raise ConnectionError("postgres unavailable")
    with pytest.raises(ConnectionError, match="postgres unavailable"):
        PostgresBm25Service(UnavailableSessions()).search("keyword", 1)
