"""P4-3: /rag/search and /rag/chat must rerank identically.

The D1 gate scores /rag/search, but users read /rag/chat. If only one of them
went through the cross-encoder, every P4-3 number would describe a path nobody
queries. Both already funnel through PostgresRetrievalService.retrieve; these
tests lock that in so a future refactor cannot quietly split them.

No weights are downloaded: the cross-encoder is a fake injected into the app's
own reranker service.
"""
from __future__ import annotations

import pytest

from app.services.reranker_service import RerankerUnavailableError

# Candidates come back from retrieval in this order; the fake scorer inverts it.
CANDIDATES = [
    {"document_id": "doc_a", "filename": "a.md", "chunk_id": "chunk_1", "chunk_index": 0, "index_version": 1, "page": None, "score": 0.9, "content": "đoạn hạng nhất theo retrieval"},
    {"document_id": "doc_b", "filename": "b.md", "chunk_id": "chunk_2", "chunk_index": 0, "index_version": 1, "page": None, "score": 0.5, "content": "đoạn hạng nhì theo retrieval"},
    {"document_id": "doc_c", "filename": "c.md", "chunk_id": "chunk_3", "chunk_index": 0, "index_version": 1, "page": None, "score": 0.1, "content": "đoạn hạng ba theo retrieval"},
]

# Descending retrieval order -> ascending cross-encoder score, so a working
# reranker produces exactly the reverse. Nothing subtler would prove the
# reordering actually happened.
INVERTED_SCORES = [0.1, 0.5, 0.9]


class FakeCrossEncoder:
    def __init__(self, record):
        self.record = record

    def predict(self, pairs):
        self.record.append([question for question, _ in pairs][0])
        return INVERTED_SCORES[: len(pairs)]


@pytest.fixture
def reranking(client, monkeypatch):
    """Turn the app's reranker on with a fake model; record every question it scores."""
    scored: list[str] = []
    service = client.app.state.rag_service.retrieval_service.reranker_service

    monkeypatch.setattr(service, "enabled", True)
    monkeypatch.setattr(service, "candidate_limit", 15)
    monkeypatch.setattr(service, "_model", FakeCrossEncoder(scored))
    monkeypatch.setattr(
        "app.services.postgres_retrieval_service.PostgresRetrievalService._dense",
        lambda self, query, top_k, document_id: [dict(row) for row in CANDIDATES],
    )
    monkeypatch.setattr("app.services.postgres_bm25_service.PostgresBm25Service.search", lambda self, query, top_k, document_id: [])
    return scored


def test_search_returns_cross_encoder_order_not_retrieval_order(reranking, client, mock_ollama):
    response = client.post("/rag/search", json={"message": "câu hỏi thử"})

    assert response.status_code == 200
    filenames = [source["filename"] for source in response.json()["sources"]]
    assert filenames == ["c.md", "b.md", "a.md"], "the reranker did not reorder /rag/search"
    assert reranking == ["câu hỏi thử"]


def test_chat_cites_the_same_reranked_sources_as_search(reranking, client, mock_ollama):
    search = client.post("/rag/search", json={"message": "câu hỏi thử"})
    chat = client.post("/rag/chat", json={"message": "câu hỏi thử"})

    assert chat.status_code == 200
    search_ids = [source["chunk_id"] for source in search.json()["sources"]]
    chat_ids = [source["chunk_id"] for source in chat.json()["sources"]]
    assert chat_ids == search_ids, "/rag/chat cited a different order than /rag/search would"
    # Both endpoints scored the question, so neither skipped the reranker.
    assert reranking == ["câu hỏi thử", "câu hỏi thử"]
    client.delete(f"/conversations/{chat.json()['conversation_id']}")


def test_a_broken_reranker_fails_the_request_loudly_on_both_paths(client, monkeypatch, mock_ollama):
    """Degrading silently to unranked results would make the eval measure one
    thing and production serve another — 503 says which component is at fault."""
    service = client.app.state.rag_service.retrieval_service.reranker_service
    monkeypatch.setattr(service, "enabled", True)
    monkeypatch.setattr(service, "_model", None)
    monkeypatch.setattr(service, "_model_loader", lambda _: (_ for _ in ()).throw(RerankerUnavailableError("no extra")))
    monkeypatch.setattr(
        "app.services.postgres_retrieval_service.PostgresRetrievalService._dense",
        lambda self, query, top_k, document_id: [dict(row) for row in CANDIDATES],
    )
    monkeypatch.setattr("app.services.postgres_bm25_service.PostgresBm25Service.search", lambda self, query, top_k, document_id: [])

    for endpoint in ("/rag/search", "/rag/chat"):
        response = client.post(endpoint, json={"message": "câu hỏi thử"})
        assert response.status_code == 503, endpoint
        # The app's error handler flattens HTTPException detail to the top level.
        assert response.json()["error_code"] == "RERANKER_UNAVAILABLE", endpoint


def test_window_accepts_a_real_long_context_and_still_rejects_the_sentinel():
    """A long-context reranker must keep its context (P4-6 follow-up).

    The first version guarded against HuggingFace's "no limit" sentinel with a
    100_000 ceiling. That number sits BELOW real long contexts — Qwen3-Reranker
    reports 131072, BGE-reranker-m3 8192 — so swapping in such a model would
    have silently fallen back to 512 and thrown away the whole reason for the
    swap, with nothing in the logs to say so.
    """
    from types import SimpleNamespace
    from app.services.reranker_service import RerankerService

    class Tokenizer:
        def __init__(self, limit): self.model_max_length = limit
        def encode(self, text, **kwargs): return [0] * 10

    service = RerankerService(True, "x", 15)

    def window(limit):
        return service._model_window(SimpleNamespace(max_length=None, tokenizer=Tokenizer(limit)), "câu hỏi")

    assert window(512) == 498                    # today's MiniLM, unchanged
    assert window(8192) == 8178                  # BGE-reranker-m3
    assert window(131072) == 131058              # Qwen3-Reranker keeps its context
    assert window(int(1e30)) == 498              # the sentinel still falls back
    assert window(0) == 498 and window(None) == 498
