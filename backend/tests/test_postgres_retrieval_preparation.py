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


def test_replace_chunks_persists_chunker_metadata_t15(factory):
    """T15: real chunker -> real write path must keep locations/heading_path/token_count.

    The prior regression test built ORM chunks by hand with heading_path set,
    so it stayed green while production wrote NULLs; this one goes through
    chunk_pages + replace_chunks exactly like indexing does.
    """
    from app.postgres.repositories import PostgresDocumentRepository
    from app.utils.chunking import chunk_pages

    _cleanup(factory)
    suffix = uuid4().hex
    doc_id, version_id = f"doc_phase6a_{suffix}", f"ver_phase6a_{suffix}"
    with factory.begin() as session:
        document = Document(id=doc_id, original_filename=f"phase6a-{suffix}.md", stored_filename=f"{doc_id}.md", mime_type="text/markdown", content_hash=uuid4().hex * 2, status="indexed", source_available=True)
        version = DocumentVersion(id=version_id, document_id=doc_id, version_number=1, status="active", activated_at=datetime.now(UTC), chunking_config={})
        document.active_version_id = version_id
        session.add_all((document, version))
    chunks = chunk_pages([(1, "# Guide\n\n## Setup\n\nPHASE6A-T15-KEYWORD appears in the setup body.", "native")], 480, 80)
    assert chunks and chunks[0].heading_path == ("Guide", "Setup")
    with factory.begin() as session:
        PostgresDocumentRepository(session).replace_chunks(doc_id, version_id, chunks)
    with factory() as session:
        stored = PostgresDocumentRepository(session).chunks_for_version(version_id)
        assert stored[0].heading_path == ["Guide", "Setup"]
        assert stored[0].locations and set(stored[0].locations[0]) == {"page", "start", "end"}
        assert stored[0].locations[0]["page"] == 1
        assert stored[0].token_count == chunks[0].token_count and stored[0].token_count > 0
    hits = PostgresBm25Service(factory).search("PHASE6A-T15-KEYWORD", 5, doc_id)
    assert hits and hits[0]["heading_path"] == "Guide > Setup"
    assert hits[0]["locations"]
    _cleanup(factory)


def test_bm25_zero_score_fallback_reuses_index_tokens(factory, monkeypatch):
    """The all-zero-score fallback must not re-tokenize the corpus per query.

    A one-document corpus gives every token a non-positive BM25 score, forcing
    the fallback; after the index is built, a search may tokenize exactly one
    string: the question.
    """
    import app.services.postgres_bm25_service as module

    _cleanup(factory)
    doc_id, _, _ = _seed(factory)
    bm25 = PostgresBm25Service(factory)
    assert bm25.search("Transformer", 5) and bm25.rebuild_count == 1  # build outside the counted window
    calls: list[str] = []
    original = module.tokenize_vietnamese
    monkeypatch.setattr(module, "tokenize_vietnamese", lambda text: (calls.append(text), original(text))[1])
    # Single-word question: pyvi may fuse multi-word questions into compound
    # tokens that no longer match the corpus tokens (same behavior before and
    # after the reuse patch — the fallback compares tokenizer output only).
    hits = bm25.search("Transformer", 5)
    assert hits and hits[0]["document_id"] == doc_id
    assert calls == ["Transformer"]
    _cleanup(factory)


def test_backfill_fills_pre_t15_rows_and_skips_drift(factory):
    """Backfill fills NULL metadata from re-chunked stored pages, hash-guarded."""
    from app.postgres.repositories import PostgresDocumentRepository
    from app.utils.chunking import chunk_pages, count_tokens
    from hashlib import sha256
    from scripts.backfill_chunk_metadata import backfill

    _cleanup(factory)
    suffix = uuid4().hex
    doc_id, version_id = f"doc_phase6a_{suffix}", f"ver_phase6a_{suffix}"
    text = "# Guide\n\n## Setup\n\nBackfill body text for the setup section."
    chunks = chunk_pages([(1, text, "native")], 480, 80)
    with factory.begin() as session:
        document = Document(id=doc_id, original_filename=f"phase6a-{suffix}.md", stored_filename=f"{doc_id}.md", mime_type="text/markdown", content_hash=uuid4().hex * 2, status="indexed", source_available=True)
        version = DocumentVersion(id=version_id, document_id=doc_id, version_number=1, status="active", activated_at=datetime.now(UTC), chunking_config={})
        document.active_version_id = version_id
        session.add_all((document, version))
        session.flush()
        PostgresDocumentRepository(session).replace_pages(doc_id, version_id, [(1, text, "native")])
        # Simulate a pre-T15 row: correct content/hash/pages, NULL metadata.
        for index, chunk in enumerate(chunks):
            session.add(DocumentChunk(id=f"chunk_{uuid4().hex}", chunk_uid=f"uid-{suffix}-{index}", document_id=doc_id, version_id=version_id, chunk_index=index, content=chunk.content, content_hash=sha256(chunk.content.encode()).hexdigest(), page_start=chunk.page_start, page_end=chunk.page_end, locations=None, heading_path=None, token_count=None, section_title=chunk.section_title, block_type=chunk.block_type, extraction_method="native", status="staging"))
    report = backfill(factory, 480, 80, apply=False)
    with factory() as session:
        untouched = PostgresDocumentRepository(session).chunks_for_version(version_id)
        assert all(row.token_count is None and row.heading_path is None for row in untouched)
    assert report.versions_matched == 1 and report.chunks_heading_path == len(chunks)
    report = backfill(factory, 480, 80, apply=True)
    assert report.versions_matched == 1
    with factory() as session:
        filled = PostgresDocumentRepository(session).chunks_for_version(version_id)
        assert filled[0].heading_path == ["Guide", "Setup"]
        assert filled[0].locations and filled[0].locations[0]["page"] == 1
        assert all(row.token_count == count_tokens(row.content) for row in filled)
    # Drift guard: a version whose stored hash no longer matches must be left alone.
    drift_doc, drift_ver = f"doc_phase6a_{uuid4().hex}", f"ver_phase6a_{uuid4().hex}"
    with factory.begin() as session:
        document = Document(id=drift_doc, original_filename=f"phase6a-drift-{suffix}.md", stored_filename=f"{drift_doc}.md", mime_type="text/markdown", content_hash=uuid4().hex * 2, status="indexed", source_available=True)
        version = DocumentVersion(id=drift_ver, document_id=drift_doc, version_number=1, status="active", activated_at=datetime.now(UTC), chunking_config={})
        document.active_version_id = drift_ver
        session.add_all((document, version))
        session.flush()
        PostgresDocumentRepository(session).replace_pages(drift_doc, drift_ver, [(1, text, "native")])
        session.add(DocumentChunk(id=f"chunk_{uuid4().hex}", chunk_uid=f"uid-drift-{suffix}", document_id=drift_doc, version_id=drift_ver, chunk_index=0, content="content that no longer matches the pages", content_hash="b" * 64, page_start=1, page_end=1, locations=None, heading_path=None, token_count=None, section_title=None, block_type="paragraph", extraction_method="native", status="staging"))
    report = backfill(factory, 480, 80, apply=True)
    assert report.versions_content_drift == 1
    with factory() as session:
        drifted = PostgresDocumentRepository(session).chunks_for_version(drift_ver)
        assert drifted[0].heading_path is None and drifted[0].locations is None
        assert drifted[0].token_count == count_tokens(drifted[0].content)  # content-derived fill still happens
    _cleanup(factory)
