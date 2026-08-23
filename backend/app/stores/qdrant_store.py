from __future__ import annotations

import time
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5
from collections.abc import Callable
from typing import TypeVar

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, Filter, FieldCondition, MatchValue, PointIdsList, PointStruct, VectorParams
from app.utils.chunking import DocumentChunk, normalize_chunk


class QdrantDimensionMismatchError(Exception):
    pass


class QdrantUnavailableError(Exception):
    pass


T = TypeVar("T")


class QdrantStore:
    collection_name = "documents"
    memories_collection_name = "memories"

    def __init__(self, url: str, timeout: float, memories_collection: str | None = None, documents_collection: str | None = None) -> None:
        self.client = QdrantClient(url=url, timeout=timeout)
        if memories_collection:
            self.memories_collection_name = memories_collection
        # T11: the documents collection is per environment too, so a lab
        # database (DEVELOPMENT_PLAN.md 3d) or the test suite never shares
        # vectors with the operating corpus.
        if documents_collection:
            self.collection_name = documents_collection
        self.retry_count = 2

    def healthcheck(self) -> bool:
        try:
            self._retry(self.client.get_collections)
            return True
        except Exception:
            return False

    def upsert_chunks(self, document_id: str, version_id: str | int, filename: str, chunks: list[DocumentChunk | tuple[str, int | None, str]], vectors: list[list[float]], chunk_ids: list[str] | None = None) -> None:
        if not vectors:
            return
        self._ensure_collection(len(vectors[0]))
        version_key = "version_id" if isinstance(version_id, str) else "index_version"
        self._retry(lambda: self.client.delete(collection_name=self.collection_name, points_selector=Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=document_id)), FieldCondition(key=version_key, match=MatchValue(value=version_id))])))
        points = []
        for index, (raw_chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
            chunk = normalize_chunk(raw_chunk)
            points.append(PointStruct(
                id=str(uuid5(NAMESPACE_URL, f"local-ai-core:{document_id}:{version_id}:{index}")), vector=vector,
                payload={"document_id": document_id, "filename": filename,
                         "chunk_index": index, "page": chunk.page_start, "page_start": chunk.page_start,
                         "page_end": chunk.page_end, "heading_path": chunk.heading_path,
                         "section_title": chunk.section_title, "block_type": chunk.block_type,
                         "extraction_method": chunk.extraction_method,
                         **({"version_id": version_id, "chunk_id": chunk_ids[index], "content_hash": sha256(chunk.content.encode("utf-8")).hexdigest()} if isinstance(version_id, str) and chunk_ids else {"index_version": version_id})},
            ))
        self._retry(lambda: self.client.upsert(collection_name=self.collection_name, points=points, wait=True))

    def search(self, vector: list[float], top_k: int, document_id: str | list[str] | None = None, version_ids: list[str] | None = None) -> list[dict[str, object]]:
        must = []
        if isinstance(document_id, list):
            if not document_id:
                return []
            must.append(Filter(should=[FieldCondition(key="document_id", match=MatchValue(value=value)) for value in document_id]))
        elif document_id:
            must.append(FieldCondition(key="document_id", match=MatchValue(value=document_id)))
        if version_ids is not None:
            if not version_ids:
                return []
            must.append(Filter(should=[FieldCondition(key="version_id", match=MatchValue(value=value)) for value in version_ids]))
        query_filter = Filter(must=must) if must else None
        results = self._retry(lambda: self.client.query_points(collection_name=self.collection_name, query=vector, limit=top_k, query_filter=query_filter)).points
        return [{"score": point.score, **dict(point.payload or {})} for point in results]

    def delete_legacy_document_content(self) -> bool:
        """Remove the pre-storage-optimization content payload from document points."""
        if not self._retry(lambda: self.client.collection_exists(self.collection_name)):
            return False
        self._retry(lambda: self.client.delete_payload(collection_name=self.collection_name, keys=["content"], points=Filter()))
        return True

    def migrate_legacy_document_points(self) -> int:
        """Copy legacy points to deterministic UUID5/versioned points without re-embedding."""
        if not self._retry(lambda: self.client.collection_exists(self.collection_name)):
            return 0
        offset = None
        migrated = 0
        while True:
            records, offset = self._retry(lambda: self.client.scroll(collection_name=self.collection_name, offset=offset, limit=100, with_payload=True, with_vectors=True))
            replacements: list[PointStruct] = []
            legacy_ids: list[object] = []
            for record in records:
                payload = dict(record.payload or {})
                if "document_id" not in payload or "chunk_index" not in payload:
                    continue
                version = int(payload.get("index_version", 1))
                deterministic_id = str(uuid5(NAMESPACE_URL, f"local-ai-core:{payload['document_id']}:{version}:{payload['chunk_index']}"))
                if str(record.id) == deterministic_id:
                    continue
                replacements.append(PointStruct(id=deterministic_id, vector=record.vector, payload={key: value for key, value in {**payload, "index_version": version}.items() if key != "content"}))
                legacy_ids.append(record.id)
            if replacements:
                self._retry(lambda: self.client.upsert(collection_name=self.collection_name, points=replacements, wait=True))
                self._retry(lambda: self.client.delete(collection_name=self.collection_name, points_selector=PointIdsList(points=legacy_ids), wait=True))
                migrated += len(replacements)
            if offset is None:
                break
        return migrated

    def delete_document_version(self, document_id: str, index_version: str | int) -> None:
        if not self._retry(lambda: self.client.collection_exists(self.collection_name)):
            return
        key = "version_id" if isinstance(index_version, str) else "index_version"
        self._retry(lambda: self.client.delete(collection_name=self.collection_name, points_selector=Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=document_id)), FieldCondition(key=key, match=MatchValue(value=index_version))]), wait=True))

    def delete_document(self, document_id: str) -> None:
        if not self._retry(lambda: self.client.collection_exists(self.collection_name)):
            return
        self._retry(lambda: self.client.delete(collection_name=self.collection_name, points_selector=Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]), wait=True))

    def upsert_memory(self, memory_id: str, content: str, memory_type: str, importance: float, vector: list[float]) -> None:
        self._ensure_named_collection(self.memories_collection_name, len(vector))
        point = PointStruct(
            # Qdrant accepts UUID/integer point IDs, while the public memory
            # contract deliberately uses opaque `mem_...` IDs. Keep that ID in
            # payload and derive a stable UUID for the vector-store key.
            id=str(uuid5(NAMESPACE_URL, f"local-ai-core:memory:{memory_id}")),
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
        point_id = str(uuid5(NAMESPACE_URL, f"local-ai-core:memory:{memory_id}"))
        self._retry(lambda: self.client.delete(collection_name=self.memories_collection_name, points_selector=PointIdsList(points=[point_id]), wait=True))

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
