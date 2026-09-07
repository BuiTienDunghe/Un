"""Model registry: deletes fan out to every registered embedding collection (design §5).

An inactive collection pair is frozen, not mirrored, so a delete that reached only the
active collection would let a revoked memory or a superseded version resurrect the day
the pointer moves back. The fake client models collections as dicts of point id ->
payload and records the calls; the Postgres test runs the real cleanup executor against
the real store (fake client) to prove the raise-before-flip ordering; one round trip
against a live Qdrant (skipped when none answers) checks the client calls the fake
assumes.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from qdrant_client.models import Distance, PointIdsList, VectorParams

from app.config.model_registry import QDRANT_UNREACHABLE
from app.stores.qdrant_store import RETRIEVE_BATCH, QdrantStore, QdrantUnavailableError


def memory_point_id(memory_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"local-ai-core:memory:{memory_id}"))


def chunk_point_id(document_id: str, version_id: str, index: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"local-ai-core:{document_id}:{version_id}:{index}"))


class FakeQdrantClient:
    """Enough of qdrant_client for the store: collections are {point id: payload}."""

    def __init__(self, collections: dict[str, dict[str, dict]], *, failing=(), sizes: dict[str, int] | None = None) -> None:
        self.collections = {name: dict(points) for name, points in collections.items()}
        self.failing = set(failing)
        self.sizes = dict(sizes or {})
        self.calls: list[tuple] = []

    def get_collections(self):
        return SimpleNamespace(collections=[SimpleNamespace(name=name) for name in self.collections])

    def collection_exists(self, name):
        self.calls.append(("exists", name))
        return name in self.collections

    def get_collection(self, name):
        return SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(vectors=VectorParams(size=self.sizes.get(name, 3), distance=Distance.COSINE))))

    def create_collection(self, name, vectors_config):
        self.collections[name] = {}
        self.sizes[name] = vectors_config.size

    def count(self, collection_name, exact=True):
        return SimpleNamespace(count=len(self.collections[collection_name]))

    def delete(self, collection_name, points_selector, wait=True):
        self.calls.append(("delete", collection_name))
        if collection_name in self.failing:
            raise ConnectionError(f"{collection_name} is down")
        points = self.collections[collection_name]
        if isinstance(points_selector, PointIdsList):
            for point_id in points_selector.points:
                points.pop(str(point_id), None)
            return
        wanted = {condition.key: condition.match.value for condition in points_selector.must}
        for point_id in [pid for pid, payload in points.items() if all(payload.get(key) == value for key, value in wanted.items())]:
            points.pop(point_id)

    def upsert(self, collection_name, points, wait=True):
        self.calls.append(("upsert", collection_name, len(points)))
        for point in points:
            self.collections[collection_name][str(point.id)] = dict(point.payload or {})

    def retrieve(self, collection_name, ids, with_payload=True, with_vectors=False):
        self.calls.append(("retrieve", collection_name, len(ids), with_payload, with_vectors))
        return [SimpleNamespace(id=point_id) for point_id in ids if point_id in self.collections[collection_name]]


class DeadClient:
    def collection_exists(self, name):
        raise ConnectionError("qdrant down")


def store(monkeypatch, client, **kwargs) -> QdrantStore:
    monkeypatch.setattr("app.stores.qdrant_store.QdrantClient", lambda url, timeout: client)
    built = QdrantStore("http://fake:6333", 1, **kwargs)
    built.retry_count = 0  # the sweep's raise is under test, not _retry's 0.5 s + 1.5 s sleeps
    return built


MEMORY = "mem_dc_abc"
DOC, OLD, NEW = "doc_x", "ver_old", "ver_new"


def two_documents_collections():
    points = {
        chunk_point_id(DOC, OLD, 0): {"document_id": DOC, "version_id": OLD},
        chunk_point_id(DOC, NEW, 0): {"document_id": DOC, "version_id": NEW},
        chunk_point_id("doc_other", "ver_o", 0): {"document_id": "doc_other", "version_id": "ver_o"},
    }
    return {"documents_test": dict(points), "documents_test_e5l": dict(points)}


def test_delete_memory_empties_every_memories_collection_active_first(monkeypatch):
    point = {memory_point_id(MEMORY): {"memory_id": MEMORY}, memory_point_id("mem_keep"): {"memory_id": "mem_keep"}}
    client = FakeQdrantClient({"memories_test": point, "memories_test_e5l": point})
    qdrant = store(monkeypatch, client, memories_collection="memories_test", memories_sweep=("memories_test", "memories_test_e5l"))

    qdrant.delete_memory(MEMORY)

    assert [call for call in client.calls if call[0] == "delete"] == [("delete", "memories_test"), ("delete", "memories_test_e5l")]
    assert set(client.collections["memories_test"]) == set(client.collections["memories_test_e5l"]) == {memory_point_id("mem_keep")}


def test_document_deletes_sweep_every_collection_and_skip_an_absent_one(monkeypatch):
    collections = two_documents_collections()
    client = FakeQdrantClient(collections)
    qdrant = store(monkeypatch, client, documents_collection="documents_test", documents_sweep=("documents_test", "documents_test_e5l", "documents_test_never_built"))

    qdrant.delete_document_version(DOC, OLD)
    for name in ("documents_test", "documents_test_e5l"):
        assert set(client.collections[name]) == {chunk_point_id(DOC, NEW, 0), chunk_point_id("doc_other", "ver_o", 0)}, name

    qdrant.delete_document(DOC)
    for name in ("documents_test", "documents_test_e5l"):
        assert set(client.collections[name]) == {chunk_point_id("doc_other", "ver_o", 0)}, name
    assert ("delete", "documents_test_never_built") not in client.calls, "an absent collection is skipped, never an error"
    assert ("exists", "documents_test_never_built") in client.calls


def test_the_first_failing_existing_collection_raises_after_the_active_one_was_swept(monkeypatch):
    client = FakeQdrantClient(two_documents_collections(), failing={"documents_test_e5l"})
    qdrant = store(monkeypatch, client, documents_collection="documents_test", documents_sweep=("documents_test", "documents_test_e5l"))

    with pytest.raises(QdrantUnavailableError):
        qdrant.delete_document_version(DOC, OLD)

    assert chunk_point_id(DOC, OLD, 0) not in client.collections["documents_test"], "active collection swept first"
    assert chunk_point_id(DOC, OLD, 0) in client.collections["documents_test_e5l"], "the failing one keeps its point"
    # The retry, once the second collection answers, deletes the already-empty active
    # collection again and finishes: idempotent by construction.
    client.failing.clear()
    qdrant.delete_document_version(DOC, OLD)
    assert chunk_point_id(DOC, OLD, 0) not in client.collections["documents_test_e5l"]

    client.failing.add("memories_test_e5l")
    memories = store(monkeypatch, FakeQdrantClient({"memories_test": {}, "memories_test_e5l": {}}, failing={"memories_test_e5l"}), memories_collection="memories_test", memories_sweep=("memories_test", "memories_test_e5l"))
    with pytest.raises(QdrantUnavailableError):
        memories.delete_memory(MEMORY)


def test_default_sweep_is_the_active_collection_and_follows_a_reassignment(monkeypatch):
    client = FakeQdrantClient({"documents_lab": {}, "memories_lab": {}})
    qdrant = store(monkeypatch, client, memories_collection="memories_lab", documents_collection="documents_lab")
    assert qdrant.documents_sweep == ("documents_lab",) and qdrant.memories_sweep == ("memories_lab",)
    qdrant.collection_name = "phase5b-validation"  # test_sqlite_document_migration.py does this
    assert qdrant.documents_sweep == ("phase5b-validation",)
    bare = store(monkeypatch, client)
    assert bare.documents_sweep == ("documents",) and bare.memories_sweep == ("memories",)
    explicit = store(monkeypatch, client, documents_sweep=["documents_lab", "documents_lab_e5l"], memories_sweep=())
    assert explicit.documents_sweep == ("documents_lab", "documents_lab_e5l") and explicit.memories_sweep == ("memories",)


def test_probe_helpers_decide_or_say_they_could_not_and_never_raise(monkeypatch):
    client = FakeQdrantClient({"documents_test": {"p1": {}, "p2": {}}}, sizes={"documents_test": 1024})
    qdrant = store(monkeypatch, client, documents_collection="documents_test")

    assert qdrant.collection_dimension("documents_test") == 1024
    assert qdrant.collection_dimension("documents_test_e5l") is None, "absent = None, a decided no"
    assert qdrant.point_count("documents_test") == 2
    assert qdrant.point_count("documents_test_e5l") == 0

    dead = store(monkeypatch, DeadClient(), documents_collection="documents_test")
    assert dead.collection_dimension("documents_test") is QDRANT_UNREACHABLE
    assert dead.point_count("documents_test") is QDRANT_UNREACHABLE, "could not decide is never 0"


def test_existing_point_ids_batches_retrieve_and_returns_only_the_present_ones(monkeypatch):
    present = [chunk_point_id(DOC, NEW, index) for index in range(RETRIEVE_BATCH + 10)]
    client = FakeQdrantClient({"documents_test": {point_id: {} for point_id in present[:RETRIEVE_BATCH + 3]}})
    qdrant = store(monkeypatch, client, documents_collection="documents_test")

    found = qdrant.existing_point_ids([*present, str(uuid4())])

    assert found == set(present[:RETRIEVE_BATCH + 3])
    retrieves = [call for call in client.calls if call[0] == "retrieve"]
    assert [call[2] for call in retrieves] == [RETRIEVE_BATCH, 11], "batches of RETRIEVE_BATCH, remainder last"
    assert all(call[3] is False and call[4] is False for call in retrieves), "neither payload nor vectors travel"
    assert qdrant.existing_point_ids([]) == set()
    absent = store(monkeypatch, FakeQdrantClient({}), documents_collection="documents_test")
    assert absent.existing_point_ids(present[:2]) == set(), "an absent collection holds nothing"


def test_upsert_chunks_replace_false_skips_the_delete_by_filter(monkeypatch):
    client = FakeQdrantClient({"documents_test": {}}, sizes={"documents_test": 3})
    qdrant = store(monkeypatch, client, documents_collection="documents_test")
    chunks = [("đoạn một", 1, "native"), ("đoạn hai", 1, "native")]

    qdrant.upsert_chunks(DOC, NEW, "a.md", chunks, [[0.1, 0.2, 0.3]] * 2, chunk_ids=["c0", "c1"])
    assert [call[0] for call in client.calls if call[0] in {"delete", "upsert"}] == ["delete", "upsert"]

    client.calls.clear()
    qdrant.upsert_chunks(DOC, NEW, "a.md", chunks[:1], [[0.1, 0.2, 0.3]], chunk_ids=["c0"], replace=False)
    assert [call[0] for call in client.calls if call[0] in {"delete", "upsert"}] == ["upsert"], "--missing-only must not wipe the points it skipped"
    assert len(client.collections["documents_test"]) == 2


# ── the executor: the row flips only after the whole sweep returned ───────────

URL = os.getenv("POSTGRES_TEST_URL")


@pytest.fixture
def factory():
    if not URL:
        pytest.skip("set POSTGRES_TEST_URL")
    from sqlalchemy import delete

    from app.postgres.database import create_postgres_engine, create_session_factory
    from app.postgres.models import Document

    built = create_session_factory(create_postgres_engine(str(URL)))
    yield built
    with built.begin() as session:
        session.execute(delete(Document).where(Document.original_filename.like("sweep-%")))


def _seed_superseded(factory):
    """One document whose old version was superseded eight days ago: due for cleanup."""
    import hashlib

    from app.postgres.models import DocumentChunk, DocumentVersion, new_id
    from app.postgres.repositories import PostgresDocumentRepository

    document_id = f"doc_sweep_{os.urandom(5).hex()}"
    with factory.begin() as session:
        repo = PostgresDocumentRepository(session)
        document, first, _ = repo.create_upload(document_id, f"sweep-{os.urandom(4).hex()}.txt", "original.txt", "text/plain", 1, os.urandom(32).hex())
        first.status = "active"
        document.status, document.active_version_id = "indexed", first.id
        old = DocumentVersion(id=new_id("ver"), document_id=document_id, version_number=2, status="superseded", chunking_config={}, superseded_at=datetime.now(UTC) - timedelta(days=8))
        session.add(old)
        session.flush()
        for version in (first, old):
            text = f"knowledge {version.id}"
            session.add(DocumentChunk(id=new_id("chunk"), chunk_uid=f"uid-{version.id}", document_id=document_id, version_id=version.id, chunk_index=0, content=text, content_hash=hashlib.sha256(text.encode()).hexdigest(), page_start=1, page_end=1, section_title="s", block_type="paragraph", extraction_method="native", status="staging"))
        return document_id, first.id, old.id


def test_cleanup_keeps_cleanup_pending_while_a_second_documents_collection_fails(factory, monkeypatch, tmp_path):
    from sqlalchemy import select

    from app.postgres.models import DocumentChunk, DocumentVersion, Job
    from app.services.postgres_cleanup_service import PostgresCleanupService

    document_id, active_id, old_id = _seed_superseded(factory)
    points = {chunk_point_id(document_id, version, 0): {"document_id": document_id, "version_id": version} for version in (active_id, old_id)}
    client = FakeQdrantClient({"documents_test": points, "documents_test_e5l": points}, failing={"documents_test_e5l"})
    qdrant = store(monkeypatch, client, documents_collection="documents_test", documents_sweep=("documents_test", "documents_test_e5l"))
    cleanup = PostgresCleanupService(factory, qdrant, tmp_path / "documents", grace_days=7)

    assert cleanup.cleanup_superseded() == 0

    with factory() as session:
        assert session.get(DocumentVersion, old_id).status == "cleanup_pending", "the row must not flip while a registered collection still holds the points"
        assert session.scalar(select(DocumentChunk).where(DocumentChunk.version_id == old_id)) is not None
        assert session.scalar(select(Job).where(Job.idempotency_key == f"cleanup_version:{old_id}")).status == "retrying"
    assert chunk_point_id(document_id, old_id, 0) not in client.collections["documents_test"]
    assert chunk_point_id(document_id, old_id, 0) in client.collections["documents_test_e5l"]

    client.failing.clear()
    assert cleanup.cleanup_superseded() == 1, "the retry finishes the sweep and flips the row"
    with factory() as session:
        assert session.get(DocumentVersion, old_id).status == "deleted"
        assert session.get(DocumentVersion, active_id).status == "active"
        assert session.scalar(select(DocumentChunk).where(DocumentChunk.version_id == old_id)) is None
    for name in ("documents_test", "documents_test_e5l"):
        assert set(client.collections[name]) == {chunk_point_id(document_id, active_id, 0)}, name


# ── one live round trip: the client calls the fake assumes ───────────────────


def test_sweep_round_trip_on_a_live_qdrant():
    from qdrant_client import QdrantClient

    url = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
    try:
        QdrantClient(url=url, timeout=2).get_collections()
    except Exception as error:
        pytest.skip(f"no Qdrant at {url}: {error}")
    suffix = uuid4().hex[:8]
    a, b, docs = f"sweep_test_{suffix}_a", f"sweep_test_{suffix}_b", f"sweep_test_{suffix}_docs"
    client = QdrantClient(url=url, timeout=10)
    try:
        QdrantStore(url, 10, memories_collection=a).upsert_memory(MEMORY, "hai bản sao", "fact", 0.5, [0.1, 0.2, 0.3])
        QdrantStore(url, 10, memories_collection=b).upsert_memory(MEMORY, "hai bản sao", "fact", 0.5, [0.1, 0.2, 0.3])
        swept = QdrantStore(url, 10, memories_collection=a, documents_collection=docs, memories_sweep=(a, b, f"sweep_test_{suffix}_absent"))
        assert swept.point_count(a) == 1 == swept.point_count(b)
        assert swept.collection_dimension(a) == 3 and swept.collection_dimension(f"sweep_test_{suffix}_absent") is None

        swept.delete_memory(MEMORY)

        assert swept.point_count(a) == 0 == swept.point_count(b), "both copies gone in one call"
        chunks = [("đoạn một", 1, "native"), ("đoạn hai", 1, "native")]
        swept.upsert_chunks(DOC, NEW, "a.md", chunks, [[0.1, 0.2, 0.3], [0.3, 0.2, 0.1]], chunk_ids=["c0", "c1"])
        ids = [chunk_point_id(DOC, NEW, 0), chunk_point_id(DOC, NEW, 1), chunk_point_id(DOC, NEW, 2)]
        assert swept.existing_point_ids(ids) == set(ids[:2])
        swept.upsert_chunks(DOC, NEW, "a.md", chunks[:1], [[0.1, 0.2, 0.3]], chunk_ids=["c0"], replace=False)
        assert swept.point_count(docs) == 2, "replace=False kept the point it skipped"
    finally:
        for name in (a, b, docs):
            try:
                client.delete_collection(name)
            except Exception:
                pass
