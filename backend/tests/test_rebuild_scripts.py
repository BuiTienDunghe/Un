"""rebuild_qdrant / rebuild_memories against the test database and a live Qdrant.

What is locked (design §4 "rebuild_qdrant", §5): a dry run writes nothing; a
full pass embeds every active chunk as a PASSAGE and lands points_after ==
chunks; re-embedding into a built collection needs --confirm; --missing-only
embeds only the absent points, at their true positions (the point id and the
chunk_index payload are the chunk's position in its version), and keeps the
rest; and no rebuild ever writes document_versions.embedding_model.
"""
from __future__ import annotations

import asyncio
import io
import os
import time
from uuid import uuid4

import pytest
from fastapi import UploadFile
from qdrant_client import QdrantClient
from sqlalchemy import delete, select

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Document, DocumentChunk, DocumentVersion, Memory
from app.services.postgres_document_service import PostgresDocumentService
from app.stores.embedding_cache_store import PostgresEmbeddingCacheStore
from app.stores.qdrant_store import QdrantStore
from scripts.rebuild_memories import rebuild as rebuild_memories
from scripts.rebuild_qdrant import RebuildRefused, rebuild

POSTGRES_URL = os.getenv("POSTGRES_TEST_URL")
QDRANT_URL = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="set POSTGRES_TEST_URL to run PostgreSQL integration tests")

# ~1.2k words: the 64-token chunker of the fixture below cuts it into a handful of chunks.
TEXT = ("Điều 24. Trình tự, thủ tục cấp lại thẻ căn cước công dân khi bị mất, hư hỏng. " * 8 + "\n\n") * 6


class Router:
    """A recording embedding router: 3-d vectors, every call's side kept."""

    models = {"embedding": {"name": "test-embedding"}}

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def embed(self, text: str, *, side=None):
        self.calls.append((text, side))
        return [float(len(text) % 7), 1.0, 0.5], "test-embedding"


class IndexQdrant:
    """What the index path needs and nothing more; the rebuild uses the real store."""

    def upsert_chunks(self, *args, **kwargs) -> None: pass
    def search(self, *args, **kwargs): return []
    def delete_document(self, document_id) -> None: pass


class Ocr:
    router = Router()


class Logger:
    def log_request(self, *args: object, **kwargs: object) -> None: pass


@pytest.fixture
def qdrant():
    try:
        QdrantClient(url=QDRANT_URL, timeout=5).get_collections()
    except Exception as error:
        pytest.skip(f"no Qdrant at {QDRANT_URL}: {error}")
    suffix = uuid4().hex[:8]
    documents, memories = f"documents_rebuild_{suffix}", f"memories_rebuild_{suffix}"
    store = QdrantStore(QDRANT_URL, 10.0, memories, documents)
    yield store, documents, memories
    for name in (documents, memories):
        if store.client.collection_exists(name):
            store.client.delete_collection(name)


@pytest.fixture
def indexed_document(tmp_path):
    """One indexed document with its active version's chunks in the test database."""
    factory = create_session_factory(create_postgres_engine(str(POSTGRES_URL)))
    service = PostgresDocumentService(factory, PostgresEmbeddingCacheStore(factory), IndexQdrant(), Router(), Logger(), tmp_path / "documents", 64, 8, Ocr())
    upload = asyncio.run(service.upload(UploadFile(filename=f"rebuild-{uuid4().hex[:6]}.txt", file=io.BytesIO(TEXT.encode("utf-8")), headers={"content-type": "text/plain"}), 10_000_000))
    run = service.enqueue_index(str(upload["document_id"]))
    for _ in range(200):
        state = service.get_ingestion(str(run["id"]))
        if state["stage"] in {"completed", "failed"}:
            break
        time.sleep(0.03)
    assert state["stage"] == "completed", state
    document_id = str(upload["document_id"])
    with factory() as session:
        document = session.get(Document, document_id)
        version_id = str(document.active_version_id)
        chunks = list(session.scalars(select(DocumentChunk).where(DocumentChunk.version_id == document.active_version_id).order_by(DocumentChunk.chunk_index)))
        chunk_ids = [chunk.id for chunk in chunks]
    assert len(chunks) >= 3, "the fixture text must yield several chunks"
    yield factory, document_id, version_id, chunk_ids
    with factory.begin() as session:
        session.execute(delete(Document).where(Document.id == document_id))


def embedding_model_column(factory, version_id: str):
    with factory() as session:
        return session.get(DocumentVersion, version_id).embedding_model


def test_dry_run_full_pass_confirm_and_missing_only(indexed_document, qdrant):
    factory, document_id, version_id, chunk_ids = indexed_document
    store, documents, _ = qdrant
    router = Router()
    common = dict(embedding_version="embedding-v0", collection=documents, active_chunks=len(chunk_ids), document_id=document_id)

    # Dry run: counts, no embed, no collection.
    summary = rebuild(factory, router, store, dry_run=True, **common)
    assert summary == {"embedding_version": "embedding-v0", "collection": documents, "documents": 1, "chunks": len(chunk_ids),
                       "embedded": 0, "skipped_existing": 0, "points_after": 0, "active_chunks": len(chunk_ids), "dry_run": True}
    assert router.calls == [] and not store.client.collection_exists(documents)

    # Full pass: every chunk embedded as a passage, points_after == active_chunks.
    summary = rebuild(factory, router, store, **common)
    assert (summary["embedded"], summary["skipped_existing"], summary["points_after"]) == (len(chunk_ids), 0, len(chunk_ids))
    assert {side for _, side in router.calls} == {"passage"} and len(router.calls) == len(chunk_ids)
    assert embedding_model_column(factory, version_id) is None, "a rebuild never writes document_versions.embedding_model"

    # A second full pass into a built collection is a decision: --confirm or --missing-only.
    with pytest.raises(RebuildRefused, match="--missing-only .* --confirm"):
        rebuild(factory, router, store, **common)
    router.calls.clear()
    assert rebuild(factory, router, store, confirm=True, **common)["embedded"] == len(chunk_ids)

    # Drop one point in the middle; --missing-only puts exactly that one back, where it was.
    gone = 1
    gone_id = store.chunk_point_id(document_id, version_id, gone)
    store.client.delete(collection_name=documents, points_selector=[gone_id], wait=True)
    assert store.point_count(documents) == len(chunk_ids) - 1
    router.calls.clear()
    summary = rebuild(factory, router, store, missing_only=True, **common)
    assert (summary["embedded"], summary["skipped_existing"], summary["points_after"]) == (1, len(chunk_ids) - 1, len(chunk_ids))
    assert len(router.calls) == 1 and router.calls[0][1] == "passage"
    (point,) = store.client.retrieve(collection_name=documents, ids=[gone_id], with_payload=True)
    assert point.payload["chunk_index"] == gone and point.payload["chunk_id"] == chunk_ids[gone] and point.payload["version_id"] == version_id
    # Nothing left to do: a complete collection is a no-op, not a re-embed.
    router.calls.clear()
    summary = rebuild(factory, router, store, missing_only=True, **common)
    assert (summary["embedded"], summary["skipped_existing"], router.calls) == (0, len(chunk_ids), [])
    assert embedding_model_column(factory, version_id) is None


def test_memories_full_pass_and_missing_only(qdrant):
    store, _, memories = qdrant
    factory = create_session_factory(create_postgres_engine(str(POSTGRES_URL)))
    ids = [f"mem_rebuild_{uuid4().hex[:8]}" for _ in range(3)]
    with factory.begin() as session:
        for index, memory_id in enumerate(ids):
            session.add(Memory(id=memory_id, content=f"ghi nhớ số {index}", memory_type="fact", importance=0.5, metadata_json={}))
    try:
        router = Router()
        dry = rebuild_memories(factory, router, store, embedding_version="embedding-v0", collection=memories, dry_run=True)
        assert dry["embedded"] == 0 and dry["memories_rows"] >= 3 and dry["points_after"] == 0 and router.calls == []

        full = rebuild_memories(factory, router, store, embedding_version="embedding-v0", collection=memories)
        rows = full["memories_rows"]
        assert (full["embedded"], full["skipped_existing"], full["points_after"]) == (rows, 0, rows)
        assert {side for _, side in router.calls} == {"passage"}
        found = store.client.retrieve(collection_name=memories, ids=[store.memory_point_id(ids[0])], with_payload=True)
        assert found[0].payload["memory_id"] == ids[0] and found[0].payload["content"] == "ghi nhớ số 0"

        store.client.delete(collection_name=memories, points_selector=[store.memory_point_id(ids[1])], wait=True)
        router.calls.clear()
        partial = rebuild_memories(factory, router, store, embedding_version="embedding-v0", collection=memories, missing_only=True)
        assert (partial["embedded"], partial["skipped_existing"], partial["points_after"]) == (1, rows - 1, rows)
        assert router.calls == [("ghi nhớ số 1", "passage")]
    finally:
        with factory.begin() as session:
            session.execute(delete(Memory).where(Memory.id.in_(ids)))
