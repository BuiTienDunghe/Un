from __future__ import annotations

from uuid import uuid4

from app.services.logging_service import LoggingService
from app.services.model_router import ModelRouter
from app.stores.qdrant_store import QdrantStore
from app.stores.auxiliary_store import AuxiliaryStore


class MemoryNotFoundError(Exception):
    pass


class MemoryService:
    def __init__(self, store: AuxiliaryStore, qdrant: QdrantStore, router: ModelRouter, logging_service: LoggingService) -> None:
        self.store = store
        self.qdrant = qdrant
        self.router = router
        self.logging_service = logging_service

    def add(self, content: str, memory_type: str, importance: float) -> dict[str, object]:
        memory_id = f"mem_{uuid4().hex}"
        vector, _ = self.router.embed(content)
        self.qdrant.upsert_memory(memory_id, content, memory_type, importance, vector)
        try:
            self.store.create_memory(memory_id, content, memory_type, importance)
        except Exception:
            self.qdrant.delete_memory(memory_id)
            raise
        self.logging_service.log_request("/memory/add", None, 0, "ok")
        return self._require(memory_id)

    def upsert_with_id(self, memory_id: str, content: str, memory_type: str, importance: float) -> dict[str, object]:
        """Idempotent add under a caller-chosen id.

        The Discord review bridge derives the id from the canonical Discord
        memory, so retrying a failed mirror overwrites the same entry instead
        of stacking duplicates. Qdrant upsert is naturally idempotent; the
        relational row falls back to update when the insert already happened.
        """
        vector, _ = self.router.embed(content)
        self.qdrant.upsert_memory(memory_id, content, memory_type, importance, vector)
        try:
            if not self.store.update_memory(memory_id, content, memory_type, importance):
                self.store.create_memory(memory_id, content, memory_type, importance)
        except Exception:
            self.qdrant.delete_memory(memory_id)
            raise
        return self._require(memory_id)

    def remove_with_id(self, memory_id: str) -> bool:
        """Idempotent delete for mirrored ids: a missing row counts as done, so
        a revert or supersede retry never fails on work already finished."""
        existed = self.store.get_memory(memory_id) is not None
        self.qdrant.delete_memory(memory_id)
        if existed:
            self.store.delete_memory(memory_id)
        return existed

    def search(self, query: str, top_k: int) -> list[dict[str, object]]:
        vector, _ = self.router.embed(query)
        return self.qdrant.search_memories(vector, top_k)

    def update(self, memory_id: str, content: str, memory_type: str, importance: float) -> dict[str, object]:
        previous = self._require(memory_id)
        vector, _ = self.router.embed(content)
        self.qdrant.upsert_memory(memory_id, content, memory_type, importance, vector)
        try:
            self.store.update_memory(memory_id, content, memory_type, importance)
        except Exception:
            previous_vector, _ = self.router.embed(str(previous["content"]))
            self.qdrant.upsert_memory(memory_id, str(previous["content"]), str(previous["memory_type"]), float(previous["importance"]), previous_vector)
            raise
        self.logging_service.log_request("/memory/update", None, 0, "ok")
        return self._require(memory_id)

    def delete(self, memory_id: str) -> None:
        previous = self._require(memory_id)
        self.qdrant.delete_memory(memory_id)
        try:
            self.store.delete_memory(memory_id)
        except Exception:
            previous_vector, _ = self.router.embed(str(previous["content"]))
            self.qdrant.upsert_memory(memory_id, str(previous["content"]), str(previous["memory_type"]), float(previous["importance"]), previous_vector)
            raise
        self.logging_service.log_request("/memory/delete", None, 0, "ok")

    def _require(self, memory_id: str) -> dict[str, object]:
        memory = self.store.get_memory(memory_id)
        if memory is None:
            raise MemoryNotFoundError(memory_id)
        return memory
