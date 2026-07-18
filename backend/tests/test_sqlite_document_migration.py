from __future__ import annotations

import hashlib
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Document, DocumentChunk, DocumentVersion, IngestionRun
from app.postgres.repositories import PostgresDocumentRepository
from app.services.postgres_retrieval_service import PostgresRetrievalService
from app.stores.qdrant_store import QdrantStore
from scripts import migrate_sqlite_documents_to_postgres as tool


URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")


def _source(path: Path, *, source_less: bool = False, bad_locations: bool = False) -> Path:
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE documents (id TEXT PRIMARY KEY, original_filename TEXT, stored_filename TEXT, content_type TEXT, status TEXT, chunks_count INTEGER, error_message TEXT, created_at TEXT, updated_at TEXT, ocr_pages_count INTEGER, content_hash TEXT, active_index_version INTEGER, active_ingestion_run_id TEXT, source_available INTEGER, source_removed_at TEXT, pinned INTEGER, retention_policy TEXT, last_accessed_at TEXT);
        CREATE TABLE document_ingestion_runs (id TEXT PRIMARY KEY, document_id TEXT, index_version INTEGER, status TEXT, stage TEXT, total_pages INTEGER, processed_pages INTEGER, chunks_count INTEGER, vectors_count INTEGER, cancel_requested INTEGER, error_code TEXT, error_message TEXT, created_at TEXT, updated_at TEXT, completed_at TEXT);
        CREATE TABLE document_chunk_versions (id INTEGER PRIMARY KEY, document_id TEXT, index_version INTEGER, chunk_index INTEGER, content TEXT, page INTEGER, page_start INTEGER, page_end INTEGER, locations_json TEXT, heading_path TEXT, section_title TEXT, block_type TEXT, extraction_method TEXT, content_hash TEXT, created_at TEXT);
    """)
    now = datetime.now(UTC).isoformat(); doc_id = "phase5b-doc"; run_id = "phase5b-run"; content = "canonical document chunk"
    digest = hashlib.sha256(content.encode()).hexdigest()
    connection.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (doc_id, "phase5b.txt", "phase5b-doc.txt", "text/plain", "indexed", 1, None, now, now, 0, None if source_less else "d" * 64, 1, run_id, 0 if source_less else 1, None, 0, "permanent", None))
    connection.execute("INSERT INTO document_ingestion_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (run_id, doc_id, 1, "indexed", "indexed", 1, 1, 1, 1, 0, None, None, now, now, now))
    locations = "not-json" if bad_locations else '[{"page":1,"start":0,"end":24}]'
    connection.execute("INSERT INTO document_chunk_versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (1, doc_id, 1, 0, content, 1, 1, 1, locations, "Heading", "Heading", "paragraph", "native", digest, now))
    connection.commit(); connection.close(); return path


@pytest.fixture
def factory():
    return create_session_factory(create_postgres_engine(str(URL)))


def _cleanup(factory) -> None:
    with factory.begin() as session:
        session.execute(delete(Document).where(Document.id == "phase5b-doc"))


def test_document_dry_run_does_not_write(factory, tmp_path):
    _cleanup(factory); report = tool.migrate(_source(tmp_path / "source.db"), factory, dry_run=True)
    assert report["documents"].source_rows == 1
    with factory() as session: assert session.get(Document, "phase5b-doc") is None


def test_document_version_run_and_chunk_mapping_preserves_jsonb(factory, tmp_path):
    _cleanup(factory); source = _source(tmp_path / "source.db")
    report = tool.migrate(source, factory)
    assert sum(item.failed + item.mismatch for item in report.values()) == 0
    verified = tool.verify(source, factory)
    assert all(item["valid"] for item in verified.values())
    with factory() as session:
        document = session.get(Document, "phase5b-doc"); version = session.get(DocumentVersion, "ver_phase5b-doc_1")
        run = session.get(IngestionRun, "phase5b-run")
        chunk = session.scalar(select(DocumentChunk).where(DocumentChunk.version_id == version.id))
        assert document.status == "uploaded" and document.active_version_id is None
        assert version.status == "staging" and run.completed_at is not None
        assert chunk.locations == [{"page": 1, "start": 0, "end": 24}] and chunk.heading_path == ["Heading"]
    second = tool.migrate(source, factory)
    assert sum(item.inserted for item in second.values()) == 0
    _cleanup(factory)


def test_source_less_is_policy_controlled_not_activated(factory, tmp_path):
    _cleanup(factory); source = _source(tmp_path / "source.db", source_less=True)
    report = tool.migrate(source, factory)
    assert report["documents"].policy_controlled == 1
    with factory() as session:
        document = session.get(Document, "phase5b-doc")
        assert document.content_hash is None and document.source_available is False and document.active_version_id is None
    _cleanup(factory)


def test_post_cutover_verification_accepts_only_verified_legacy_activation(factory, tmp_path):
    """The Phase-5C flag is fail-closed outside the audited active mapping."""
    _cleanup(factory); source = _source(tmp_path / "source.db")
    tool.migrate(source, factory)
    with factory.begin() as session:
        PostgresDocumentRepository(session).activate_verified_legacy_migration("phase5b-run")
    rejected = tool.verify(source, factory)
    accepted = tool.verify(source, factory, allow_activated_legacy=True)
    assert rejected["documents"]["mismatch"] == 1
    assert rejected["versions"]["mismatch"] == 1
    assert all(item["valid"] for item in accepted.values())
    _cleanup(factory)


def test_document_or_chunk_hash_mismatch_is_not_hidden(factory, tmp_path):
    _cleanup(factory); source = _source(tmp_path / "source.db")
    with factory.begin() as session:
        session.add(Document(id="phase5b-doc", original_filename="phase5b.txt", stored_filename="phase5b-doc.txt", mime_type="text/plain", content_hash="f" * 64, status="uploaded", source_available=True, retention_policy="permanent"))
    report = tool.migrate(source, factory)
    assert report["documents"].mismatch == 1 and report["documents"].failed >= 1
    _cleanup(factory)


def test_bad_chunk_batch_rolls_back(factory, tmp_path):
    _cleanup(factory); source = _source(tmp_path / "source.db", bad_locations=True)
    report = tool.migrate(source, factory, batch_size=10)
    assert report["chunks"].failed >= 1
    with factory() as session:
        assert session.scalar(select(DocumentChunk).where(DocumentChunk.document_id == "phase5b-doc")) is None
    _cleanup(factory)


def test_qdrant_validation_mapping_only_writes_verified_target(factory, tmp_path, monkeypatch):
    _cleanup(factory); source = _source(tmp_path / "source.db"); tool.migrate(source, factory)
    old_id = tool.legacy_point_id("phase5b-doc", 1, 0)
    clients = []

    class Client:
        def __init__(self, **_):
            self.created, self.writes = [], []; clients.append(self)
        def collection_exists(self, name): return name == "documents"
        def retrieve(self, collection, ids, **_):
            assert collection == "documents" and ids == [old_id]
            return [SimpleNamespace(payload={"document_id": "phase5b-doc", "index_version": 1, "chunk_index": 0, "filename": "phase5b.txt"}, vector=[0.1, 0.2])]
        def get_collection(self, _): return SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=2))))
        def create_collection(self, name, **_): self.created.append(name)
        def upsert(self, name, points, **_): self.writes.append((name, points))

    monkeypatch.setattr(tool, "QdrantClient", Client)
    result = tool.qdrant_mapping(source, factory, mode="validation-upsert", validation_collection="phase5b-test", qdrant_url="fake")
    assert result["mapped"] == 1 and result["mappings"][0]["legacy_point_id"] == old_id
    assert clients[0].writes[0][0] == "phase5b-test"
    point = clients[0].writes[0][1][0]
    assert point.payload["version_id"] == "ver_phase5b-doc_1" and point.payload["chunk_id"]
    _cleanup(factory)


def test_validation_collection_payload_batch_loads_postgres_chunk(factory, monkeypatch):
    """Uses the isolated validation collection without activating any version."""
    collection = os.getenv("PHASE5B_QDRANT_VALIDATION_COLLECTION")
    if not collection:
        pytest.skip("set PHASE5B_QDRANT_VALIDATION_COLLECTION")
    document_id = "doc_8eea844701b041b980e8142a2793f3ee"
    version_id = "ver_doc_8eea844701b041b980e8142a2793f3ee_1"
    store = QdrantStore(os.getenv("QDRANT_URL", "http://127.0.0.1:6333"), 30)
    store.collection_name = collection
    record = store.client.retrieve(collection, [tool.target_point_id(document_id, version_id, 0)], with_vectors=True, with_payload=True)
    if not record:
        pytest.skip("Phase 5B validation collection is not populated")
    vector = record[0].vector
    router = type("Router", (), {"embed": lambda self, _: (vector, "validation")})()
    monkeypatch.setattr(PostgresDocumentRepository, "active_versions", lambda self, requested=None: {document_id: version_id})
    result = PostgresRetrievalService(store, router, factory).retrieve("validation", 1, document_id)
    assert result and result[0]["document_id"] == document_id and result[0]["version_id"] == version_id
