from __future__ import annotations

from app.services.bm25_service import Bm25Service
from app.services.model_router import ModelRouter
from app.services.reranker_service import RerankerService
from app.stores.qdrant_store import QdrantStore
from app.stores.sqlite_store import SQLiteStore


class RetrievalService:
    def __init__(self, qdrant: QdrantStore, router: ModelRouter, bm25_service: Bm25Service, reranker_service: RerankerService, store: SQLiteStore, mode: str, rrf_k: int) -> None:
        if mode not in {"dense", "bm25", "hybrid"}:
            raise ValueError("rag.retrieval_mode must be dense, bm25, or hybrid")
        self.qdrant = qdrant
        self.router = router
        self.bm25_service = bm25_service
        self.reranker_service = reranker_service
        self.store = store
        self.mode = mode
        self.rrf_k = rrf_k

    def retrieve(self, question: str, top_k: int, document_id: str | None) -> list[dict[str, object]]:
        candidate_limit = self.reranker_service.candidate_limit if self.reranker_service.enabled else top_k
        dense_results: list[dict[str, object]] = []
        if self.mode in {"dense", "hybrid"}:
            vector, _ = self.router.embed(question)
            dense_results = self.qdrant.search(vector, candidate_limit, document_id)
        sparse_results = self.bm25_service.search(question, candidate_limit, document_id) if self.mode in {"bm25", "hybrid"} else []
        if self.mode == "dense":
            combined = dense_results
        elif self.mode == "bm25":
            combined = sparse_results
        else:
            combined = self.rrf(dense_results, sparse_results, candidate_limit)
        reranked = self.reranker_service.rerank(question, combined, top_k)
        return self._resolve_content(reranked)

    def _resolve_content(self, results: list[dict[str, object]]) -> list[dict[str, object]]:
        """Resolve chunk content from SQLite for results that lack it (dense search)."""
        missing_keys = [
            (str(r["document_id"]), int(r["chunk_index"]))
            for r in results if "content" not in r
        ]
        if not missing_keys:
            return results
        lookup = self.store.get_chunks_by_keys(missing_keys)
        resolved = []
        for result in results:
            if "content" not in result:
                key = (str(result["document_id"]), int(result["chunk_index"]))
                chunk = lookup.get(key)
                if chunk:
                    result = {**result, "content": chunk["content"], "filename": chunk.get("filename", result.get("filename"))}
            resolved.append(result)
        return resolved

    def rrf(self, dense_results: list[dict[str, object]], sparse_results: list[dict[str, object]], top_k: int) -> list[dict[str, object]]:
        combined: dict[tuple[str, int], dict[str, object]] = {}
        scores: dict[tuple[str, int], float] = {}
        for results in (dense_results, sparse_results):
            for rank, result in enumerate(results, start=1):
                key = (str(result["document_id"]), int(result["chunk_index"]))
                combined.setdefault(key, result)
                scores[key] = scores.get(key, 0.0) + 1 / (self.rrf_k + rank)
        return [{**combined[key], "score": scores[key]} for key in sorted(scores, key=scores.get, reverse=True)[:top_k]]
