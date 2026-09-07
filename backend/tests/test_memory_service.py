"""MemoryService embeds every WRITE as a passage and every search as a query.

Model registry: ModelRouter.embed(side=) prefixes the two ends of a retrieval pair
differently for versions that need it (multilingual-e5: "query: " / "passage: "). A
memory written with the query prefix would be searched against passages it never
resembled, so every write path — including the two rollbacks — must say passage.
"""
from __future__ import annotations

import pytest

from app.services.memory_service import MemoryNotFoundError, MemoryService


class RecordingRouter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def embed(self, text: str, *, side: str):
        self.calls.append((side, text))
        return [float(len(text))], "fake-embedding"


class FakeQdrant:
    def __init__(self) -> None:
        self.vectors: dict[str, tuple[str, list[float]]] = {}
        self.deleted: list[str] = []

    def upsert_memory(self, memory_id, content, memory_type, importance, vector):
        self.vectors[memory_id] = (content, vector)

    def delete_memory(self, memory_id):
        self.deleted.append(memory_id)
        self.vectors.pop(memory_id, None)

    def search_memories(self, vector, top_k):
        return [{"memory_id": memory_id, "content": content} for memory_id, (content, _) in self.vectors.items()][:top_k]


class FakeStore:
    """The relational side; `fail` names the one method that raises (rollback tests)."""

    def __init__(self, *, fail: str | None = None) -> None:
        self.rows: dict[str, dict] = {}
        self.fail = fail

    def _maybe_fail(self, name: str) -> None:
        if self.fail == name:
            raise RuntimeError(f"{name} failed")

    def create_memory(self, memory_id, content, memory_type, importance):
        self._maybe_fail("create_memory")
        self.rows[memory_id] = {"id": memory_id, "content": content, "memory_type": memory_type, "importance": importance}

    def update_memory(self, memory_id, content, memory_type, importance):
        self._maybe_fail("update_memory")
        if memory_id not in self.rows:
            return False
        self.rows[memory_id].update(content=content, memory_type=memory_type, importance=importance)
        return True

    def get_memory(self, memory_id):
        return dict(self.rows[memory_id]) if memory_id in self.rows else None

    def delete_memory(self, memory_id):
        self._maybe_fail("delete_memory")
        return self.rows.pop(memory_id, None) is not None


class FakeLogging:
    def log_request(self, *args, **kwargs):
        pass


def build(store: FakeStore | None = None):
    router, qdrant = RecordingRouter(), FakeQdrant()
    return MemoryService(store or FakeStore(), qdrant, router, FakeLogging()), router, qdrant


def test_add_and_upsert_embed_the_content_as_a_passage():
    service, router, qdrant = build()
    created = service.add("người dùng thích cà phê", "preference", 0.7)
    service.upsert_with_id("mem_dc_1", "sinh nhật 12/03", "fact", 0.9)
    service.upsert_with_id("mem_dc_1", "sinh nhật 12/03 (đã sửa)", "fact", 0.9)  # second call takes the update branch

    assert router.calls == [
        ("passage", "người dùng thích cà phê"),
        ("passage", "sinh nhật 12/03"),
        ("passage", "sinh nhật 12/03 (đã sửa)"),
    ]
    assert qdrant.vectors[str(created["id"])][0] == "người dùng thích cà phê"


def test_search_embeds_the_question_as_a_query_and_nothing_else():
    service, router, _ = build()
    service.add("fact", "fact", 0.5)
    router.calls.clear()

    service.search("cà phê?", 3)

    assert router.calls == [("query", "cà phê?")]


def test_update_embeds_the_new_content_as_a_passage():
    service, router, _ = build()
    created = service.add("cũ", "fact", 0.5)
    router.calls.clear()

    assert service.update(str(created["id"]), "mới", "fact", 0.6)["content"] == "mới"

    assert router.calls == [("passage", "mới")]


def test_update_rollback_re_embeds_the_previous_content_as_a_passage():
    store = FakeStore()
    service, router, qdrant = build(store)
    created = service.add("trước", "fact", 0.5)
    memory_id = str(created["id"])
    store.fail = "update_memory"
    router.calls.clear()

    with pytest.raises(RuntimeError):
        service.update(memory_id, "sau", "fact", 0.6)

    assert router.calls == [("passage", "sau"), ("passage", "trước")]
    assert qdrant.vectors[memory_id][0] == "trước", "the vector store holds the row's content again"


def test_delete_rollback_re_embeds_the_previous_content_as_a_passage():
    store = FakeStore()
    service, router, qdrant = build(store)
    created = service.add("giữ lại", "fact", 0.5)
    memory_id = str(created["id"])
    store.fail = "delete_memory"
    router.calls.clear()

    with pytest.raises(RuntimeError):
        service.delete(memory_id)

    assert router.calls == [("passage", "giữ lại")]
    assert qdrant.vectors[memory_id][0] == "giữ lại" and qdrant.deleted == [memory_id]


def test_remove_with_id_and_a_missing_memory_never_embed():
    service, router, _ = build()
    assert service.remove_with_id("mem_dc_absent") is False
    with pytest.raises(MemoryNotFoundError):
        service.update("mem_absent", "x", "fact", 0.1)
    assert router.calls == []


def test_only_search_ever_uses_the_query_side():
    """The whole CRUD surface: writes are passages, the one read is a query."""
    store = FakeStore()
    service, router, _ = build(store)
    created = service.add("a", "fact", 0.5)
    memory_id = str(created["id"])
    service.upsert_with_id("mem_dc_2", "b", "fact", 0.5)
    service.update(memory_id, "c", "fact", 0.5)
    service.search("d", 2)
    service.delete(memory_id)
    service.remove_with_id("mem_dc_2")

    assert {side for side, _ in router.calls} == {"passage", "query"}
    assert [text for side, text in router.calls if side == "query"] == ["d"]
