from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from app.postgres.repositories import PostgresDocumentRepository
from app.services.postgres_bm25_service import PostgresBm25Service
from app.services.model_router import ModelRouter
from app.services.reranker_service import RerankerService
from app.stores.qdrant_store import QdrantStore


class PostgresRetrievalService:
    """Qdrant supplies candidates; PostgreSQL authoritatively filters active versions."""

    def __init__(self, qdrant: QdrantStore, router: ModelRouter, session_factory: sessionmaker, bm25_service: PostgresBm25Service | None = None, reranker_service: RerankerService | None = None, mode: str = "dense", rrf_k: int = 60, touch_documents: bool = True) -> None:
        if mode not in {"dense", "bm25", "hybrid"}:
            raise ValueError("rag.retrieval_mode must be dense, bm25, or hybrid")
        self.qdrant, self.router, self.sessions = qdrant, router, session_factory
        self.bm25_service = bm25_service or PostgresBm25Service(session_factory)
        self.reranker_service = reranker_service or RerankerService(False, "", 1)
        self.mode, self.rrf_k, self.touch_documents = mode, rrf_k, touch_documents

    def retrieve(self, query: str, top_k: int, document_id: str | list[str] | None) -> list[dict[str, object]]:
        candidate_limit = (self.reranker_service.candidate_limit if self.reranker_service.enabled else top_k) * 3
        dense_results: list[dict[str, object]] = []
        if self.mode in {"dense", "hybrid"}:
            dense_results = self._dense(query, candidate_limit, document_id)
        sparse_results = self.bm25_service.search(query, candidate_limit, document_id) if self.mode in {"bm25", "hybrid"} else []
        if self.mode == "dense":
            combined = dense_results
        elif self.mode == "bm25":
            combined = sparse_results
        else:
            combined = self.rrf(dense_results, sparse_results, candidate_limit)
        reranked = self.reranker_service.rerank(query, combined, top_k)
        if self.touch_documents:
            self._touch_best_effort({str(row["document_id"]) for row in reranked if row.get("document_id")})
        return reranked

    def _dense(self, query: str, top_k: int, document_id: str | list[str] | None) -> list[dict[str, object]]:
        vector, _ = self.router.embed(query)
        with self.sessions() as session:
            repository = PostgresDocumentRepository(session)
            requested = [document_id] if isinstance(document_id, str) else document_id
            active = repository.active_versions(requested)
            candidates = self.qdrant.search(vector, max(top_k * 4, top_k), document_id, version_ids=list(active.values()))
            # A PostgreSQL point must carry both version_id and chunk_id. This
            # deliberately ignores all legacy index_version-only points.
            chunk_ids = [str(row["chunk_id"]) for row in candidates if row.get("version_id") and row.get("chunk_id")]
            chunks = repository.active_chunks_by_ids(chunk_ids)
            result = []
            for row in candidates:
                chunk_id, version_id = row.get("chunk_id"), row.get("version_id")
                if not chunk_id or not version_id:
                    continue
                record = chunks.get(str(chunk_id))
                if not record:
                    continue
                document, version, chunk = record
                if document.id != row.get("document_id") or version.id != version_id or chunk.chunk_index != int(row.get("chunk_index", -1)):
                    continue
                result.append({
                    "document_id": chunk.document_id, "version_id": chunk.version_id,
                    "index_version": version.version_number, "chunk_id": chunk.id,
                    "filename": document.original_filename, "chunk_index": chunk.chunk_index,
                    "page": chunk.page_start, "page_start": chunk.page_start, "page_end": chunk.page_end,
                    "locations": list(chunk.locations or []), "heading_path": " > ".join(chunk.heading_path or []) or None,
                    "section_title": chunk.section_title, "block_type": chunk.block_type,
                    "extraction_method": chunk.extraction_method, "source_available": document.source_available,
                    "verifiable": bool(document.source_available), "content_hash": chunk.content_hash,
                    "content": chunk.content, "score": float(row.get("score", 0.0)),
                })
                if len(result) >= top_k:
                    break
            return result

    def _touch_best_effort(self, document_ids: set[str]) -> None:
        if not document_ids:
            return
        try:
            with self.sessions.begin() as session:
                PostgresDocumentRepository(session).touch_documents(document_ids)
        except Exception:
            # Retrieval remains available when the non-essential audit touch
            # cannot be persisted, matching legacy best-effort semantics.
            return

    def rrf(self, dense_results: list[dict[str, object]], sparse_results: list[dict[str, object]], top_k: int) -> list[dict[str, object]]:
        combined: dict[tuple[str, str, str], dict[str, object]] = {}
        scores: dict[tuple[str, str, str], float] = {}
        for results in (dense_results, sparse_results):
            for rank, result in enumerate(results, start=1):
                key = (str(result["document_id"]), str(result.get("version_id", "")), str(result.get("chunk_id", result.get("chunk_index", ""))))
                combined.setdefault(key, result)
                scores[key] = scores.get(key, 0.0) + 1 / (self.rrf_k + rank)
        return [{**combined[key], "score": scores[key]} for key in sorted(scores, key=scores.get, reverse=True)[:top_k]]
