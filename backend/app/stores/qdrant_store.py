from __future__ import annotations

import time
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5
from collections.abc import Callable, Mapping, Sequence
from typing import TypeVar

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, Filter, FieldCondition, MatchValue, PointIdsList, PointStruct, VectorParams
from app.config.model_registry import QDRANT_UNREACHABLE, QdrantUnreachable
from app.utils.chunking import DocumentChunk, normalize_chunk


class QdrantDimensionMismatchError(Exception):
    pass


class QdrantUnavailableError(Exception):
    pass


T = TypeVar("T")

# existing_point_ids: one retrieve per batch. 256 ids keeps the request small enough
# for the HTTP client's default limits while a full rebuild (tens of thousands of
# chunks) still needs only a few hundred round-trips.
RETRIEVE_BATCH = 256


class QdrantStore:
    collection_name = "documents"
    memories_collection_name = "memories"

    def __init__(
        self, url: str, timeout: float, memories_collection: str | None = None, documents_collection: str | None = None, *,
        documents_sweep: Sequence[str] | None = None, memories_sweep: Sequence[str] | None = None,
    ) -> None:
        self.client = QdrantClient(url=url, timeout=timeout)
        if memories_collection:
            self.memories_collection_name = memories_collection
        # T11: the documents collection is per environment too, so a lab
        # database (DEVELOPMENT_PLAN.md 3d) or the test suite never shares
        # vectors with the operating corpus.
        if documents_collection:
            self.collection_name = documents_collection
        # Model registry: one embedding version == one collection pair, and an
        # inactive pair is FROZEN, not mirrored — writes go to the active collection
        # only. Deletes therefore have to reach every registered collection, or a
        # revoked memory / superseded version resurrects the day the pointer moves
        # back. The sweep is `QdrantCollections.all_documents / all_memories`, active
        # first; without one it is the active collection alone (today's behaviour).
        self._documents_sweep = tuple(documents_sweep or ())
        self._memories_sweep = tuple(memories_sweep or ())
        self.retry_count = 2

    @property
    def documents_sweep(self) -> tuple[str, ...]:
        # Resolved at use time so a caller that reassigns collection_name after
        # construction (test_sqlite_document_migration.py) still sweeps that name.
        return self._documents_sweep or (self.collection_name,)

    @property
    def memories_sweep(self) -> tuple[str, ...]:
        return self._memories_sweep or (self.memories_collection_name,)

    def healthcheck(self) -> bool:
        try:
            self._retry(self.client.get_collections)
            return True
        except Exception:
            return False

    @staticmethod
    def chunk_point_id(document_id: str, version_id: str | int, index: int) -> str:
        """The point id of chunk `index` of one document version — the same uuid5 the
        live index path mints below, exposed so rebuild_qdrant --missing-only can ask
        existing_point_ids() about chunks it has not embedded yet."""
        return str(uuid5(NAMESPACE_URL, f"local-ai-core:{document_id}:{version_id}:{index}"))

    def upsert_chunks(self, document_id: str, version_id: str | int, filename: str, chunks: list[DocumentChunk | tuple[str, int | None, str]], vectors: list[list[float]], chunk_ids: list[str] | None = None, replace: bool = True, *, chunk_indices: Sequence[int] | None = None) -> None:
        if not vectors:
            return
        self._ensure_collection(len(vectors[0]))
        version_key = "version_id" if isinstance(version_id, str) else "index_version"
        if replace:
            self._retry(lambda: self.client.delete(collection_name=self.collection_name, points_selector=Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=document_id)), FieldCondition(key=version_key, match=MatchValue(value=version_id))])))
        # replace=False is rebuild_qdrant --missing-only: the caller already filtered
        # to points absent from the collection (existing_point_ids), and the
        # delete-by-filter would wipe the points it deliberately skipped.
        # chunk_indices is the other half of that mode: the point id and the
        # chunk_index payload are the chunk's POSITION in its version, so a partial
        # list must name the positions it carries or every point would be minted as
        # chunk 0, 1, 2 ... and collide with the ones already there. Absent = the
        # list is complete and positional (the live index path).
        if chunk_indices is not None and len(chunk_indices) != len(chunks):
            raise ValueError(f"chunk_indices names {len(chunk_indices)} positions for {len(chunks)} chunks")
        points = []
        for position, (raw_chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
            index = int(chunk_indices[position]) if chunk_indices is not None else position
            chunk = normalize_chunk(raw_chunk)
            points.append(PointStruct(
                id=self.chunk_point_id(document_id, version_id, index), vector=vector,
                payload={"document_id": document_id, "filename": filename,
                         "chunk_index": index, "page": chunk.page_start, "page_start": chunk.page_start,
                         # The payload keeps the joined display form every existing
                         # point already carries; the structured list lives in Postgres (T15).
                         "page_end": chunk.page_end, "heading_path": " > ".join(chunk.heading_path) if chunk.heading_path else None,
                         "section_title": chunk.section_title, "block_type": chunk.block_type,
                         "extraction_method": chunk.extraction_method,
                         **({"version_id": version_id, "chunk_id": chunk_ids[position], "content_hash": sha256(chunk.content.encode("utf-8")).hexdigest()} if isinstance(version_id, str) and chunk_ids else {"index_version": version_id})},
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
        key = "version_id" if isinstance(index_version, str) else "index_version"
        selector = Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=document_id)), FieldCondition(key=key, match=MatchValue(value=index_version))])
        self._sweep(self.documents_sweep, lambda name: self.client.delete(collection_name=name, points_selector=selector, wait=True))

    def delete_document(self, document_id: str) -> None:
        selector = Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))])
        self._sweep(self.documents_sweep, lambda name: self.client.delete(collection_name=name, points_selector=selector, wait=True))

    def upsert_memory(self, memory_id: str, content: str, memory_type: str, importance: float, vector: list[float]) -> None:
        self._ensure_named_collection(self.memories_collection_name, len(vector))
        point = PointStruct(
            # Qdrant accepts UUID/integer point IDs, while the public memory
            # contract deliberately uses opaque `mem_...` IDs. Keep that ID in
            # payload and derive a stable UUID for the vector-store key.
            id=self.memory_point_id(memory_id),
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
        point_id = self.memory_point_id(memory_id)
        self._sweep(self.memories_sweep, lambda name: self.client.delete(collection_name=name, points_selector=PointIdsList(points=[point_id]), wait=True))

    def collection_dimension(self, name: str) -> int | None | QdrantUnreachable:
        """Startup probe: the vector width of `name`; None when the collection is absent.

        Single attempt, no _retry: on a dead Qdrant the retry sleeps (0.5 s + 1.5 s)
        would land on every boot, and the answer has to keep "could not decide"
        (QDRANT_UNREACHABLE) apart from "no such collection" (None) — the resolver
        marks the embedding role unverified on the first and, with a non-empty
        corpus, degraded on the second.
        """
        try:
            if not self.client.collection_exists(name):
                return None
            vectors = self.client.get_collection(name).config.params.vectors
        except Exception:
            return QDRANT_UNREACHABLE
        size = getattr(vectors, "size", None)
        if size is None and isinstance(vectors, Mapping) and len(vectors) == 1:
            # Named-vector layout with one vector; the store itself only ever creates
            # the unnamed layout, so this is a courtesy for hand-built collections.
            size = getattr(next(iter(vectors.values())), "size", None)
        return int(size) if size is not None else QDRANT_UNREACHABLE

    def point_count(self, name: str) -> int | QdrantUnreachable:
        """Exact point count of `name`; 0 when absent; QDRANT_UNREACHABLE when Qdrant did
        not answer. Single attempt, same reasoning as collection_dimension. The resolver
        compares it with the Postgres corpus (active chunks / memories rows): fewer
        points than rows is the `incomplete` state, the frozen-collection signal."""
        try:
            if not self.client.collection_exists(name):
                return 0
            return int(self.client.count(collection_name=name, exact=True).count)
        except Exception:
            return QDRANT_UNREACHABLE

    @staticmethod
    def memory_point_id(memory_id: str) -> str:
        """The point id of one memory — the uuid5 upsert_memory/delete_memory derive from
        the public `mem_...` id, exposed for rebuild_memories --missing-only."""
        return str(uuid5(NAMESPACE_URL, f"local-ai-core:memory:{memory_id}"))

    def existing_point_ids(self, point_ids: Sequence[str], *, collection: str | None = None) -> set[str]:
        """Which of `point_ids` a collection already holds (rebuild_qdrant / rebuild_memories
        --missing-only); the documents collection unless `collection` names another one
        (the memories collection). client.retrieve in batches of RETRIEVE_BATCH with
        neither payload nor vectors; an absent collection holds nothing."""
        name = collection or self.collection_name
        if not point_ids or not self._retry(lambda: self.client.collection_exists(name)):
            return set()
        found: set[str] = set()
        for start in range(0, len(point_ids), RETRIEVE_BATCH):
            batch = list(point_ids[start:start + RETRIEVE_BATCH])
            records = self._retry(lambda: self.client.retrieve(collection_name=name, ids=batch, with_payload=False, with_vectors=False))
            found.update(str(record.id) for record in records)
        return found

    def _sweep(self, names: Sequence[str], delete: Callable[[str], object]) -> None:
        """Run one delete against every collection of a sweep, active collection first.

        An absent collection is skipped (a version's pair may never have been built on
        this stack); the first failure of an EXISTING collection raises
        QdrantUnavailableError out of the loop. Callers see one call and one exception
        before any Postgres write: PostgresCleanupService flips the row only after this
        returns, so a half-swept version stays cleanup_pending and the retry, which
        deletes the already-empty collections again, is idempotent.
        """
        for name in names:
            if not self._retry(lambda: self.client.collection_exists(name)):
                continue
            self._retry(lambda: delete(name))

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
