from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, Filter, FieldCondition, MatchValue, PointIdsList, PointStruct, VectorParams


class QdrantDimensionMismatchError(Exception):
    pass


class QdrantUnavailableError(Exception):
    pass


T = TypeVar("T")


class QdrantStore:
    collection_name = "documents"
    memories_collection_name = "memories"

    def __init__(self, url: str, timeout: float) -> None:
        self.client = QdrantClient(url=url, timeout=timeout)
        self.retry_count = 2

    def healthcheck(self) -> bool:
        try:
            self._retry(self.client.get_collections)
            return True
        except Exception:
            return False

    def upsert_chunks(self, document_id: str, filename: str, chunks: list[tuple[str, int | None, str]], vectors: list[list[float]]) -> None:
        if not vectors:
            return
        self._ensure_collection(len(vectors[0]))
        self._retry(lambda: self.client.delete(collection_name=self.collection_name, points_selector=Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))])))
        points = [
            PointStruct(id=f"{document_id}:{index}", vector=vector, payload={"document_id": document_id, "filename": filename, "chunk_index": index, "page": page, "extraction_method": extraction_method})
            for index, ((content, page, extraction_method), vector) in enumerate(zip(chunks, vectors, strict=True))
        ]
        self._retry(lambda: self.client.upsert(collection_name=self.collection_name, points=points, wait=True))

    def search(self, vector: list[float], top_k: int, document_id: str | None = None) -> list[dict[str, object]]:
        query_filter = None
        if document_id:
            query_filter = Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))])
        results = self._retry(lambda: self.client.query_points(collection_name=self.collection_name, query=vector, limit=top_k, query_filter=query_filter)).points
        return [{"score": point.score, **dict(point.payload or {})} for point in results]

    def delete_legacy_document_content(self) -> bool:
        """Remove the pre-storage-optimization content payload from document points."""
        if not self._retry(lambda: self.client.collection_exists(self.collection_name)):
            return False
        self._retry(lambda: self.client.delete_payload(collection_name=self.collection_name, keys=["content"], points=Filter()))
        return True

    def upsert_memory(self, memory_id: str, content: str, memory_type: str, importance: float, vector: list[float]) -> None:
        self._ensure_named_collection(self.memories_collection_name, len(vector))
        point = PointStruct(
            id=memory_id,
            vector=vector,
            payload={"memory_id": memory_id, "content": content, "memory_type": memory_type, "importance": importance},
        )
        self._retry(lambda: self.client.upsert(collection_name=self.memories_collection_name, points=[point], wait=True))

    def search_memories(self, vector: list[float], top_k: int) -> list[dict[str, object]]:
        if not self._retry(lambda: self.client.collection_exists(self.memories_collection_name)):
            return []
        results = self._retry(lambda: self.client.query_points(collection_name=self.memories_collection_name, query=vector, limit=top_k)).points
        return [{"score": point.score, **dict(point.payload or {})} for point in results]

    def delete_memory(self, memory_id: str) -> None:
        self._retry(lambda: self.client.delete(collection_name=self.memories_collection_name, points_selector=PointIdsList(points=[memory_id]), wait=True))

    def _ensure_collection(self, dimension: int) -> None:
        self._ensure_named_collection(self.collection_name, dimension)

    def _ensure_named_collection(self, collection_name: str, dimension: int) -> None:
        if not self._retry(lambda: self.client.collection_exists(collection_name)):
            self._retry(lambda: self.client.create_collection(collection_name, vectors_config=VectorParams(size=dimension, distance=Distance.COSINE)))
            return
        vectors = self._retry(lambda: self.client.get_collection(collection_name)).config.params.vectors
        existing_dimension = vectors.size if isinstance(vectors, VectorParams) else None
        if existing_dimension != dimension:
            raise QdrantDimensionMismatchError(
                f"Collection {collection_name} uses dimension {existing_dimension}, but the embedding model returned {dimension}"
            )

    def _retry(self, operation: Callable[[], T]) -> T:
        for attempt in range(getattr(self, "retry_count", 2) + 1):
            try:
                return operation()
            except Exception as error:
                if attempt == getattr(self, "retry_count", 2):
                    raise QdrantUnavailableError("Cannot connect to Qdrant") from error
                time.sleep(0.5 + attempt)
        raise QdrantUnavailableError("Cannot connect to Qdrant")
