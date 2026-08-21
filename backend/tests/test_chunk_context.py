"""P4-2 contextual retrieval: generation, degradation, and index-side plumbing.

The retrieval CONTRACT under test: the generated context reaches the embedding
input and the BM25 tokens, while `content` — the citation text — never carries
it. Quality itself is judged by the D1 eval on the heavy machine, not here.
"""
from __future__ import annotations

import time

import pytest
from sqlalchemy import select

from app.services.chunk_context_service import ChunkContextService
from app.utils.chunking import DocumentChunk, chunk_pages, combined_retrieval_text


class _FakeRouter:
    def __init__(self, answer="Ngữ cảnh: tài liệu về quy trình QCX-77.", errors_at=frozenset()):
        self.calls = []
        self.answer = answer
        self.errors_at = errors_at

    def chat(self, mode, messages, **kwargs):
        self.calls.append((mode, messages))
        if len(self.calls) in self.errors_at:
            raise RuntimeError("model unavailable")
        return self.answer, "fake-general"


def _chunks(count=3):
    pages = [(None, "\n\n".join(f"Đoạn văn số {index} nói về chủ đề {index}." for index in range(count)), "native")]
    made = chunk_pages(pages, 12, 2)
    assert made
    return made


def test_annotate_fills_context_on_every_chunk_in_order():
    router = _FakeRouter()
    service = ChunkContextService(router, enabled=True)
    chunks = _chunks()

    annotated = service.annotate(chunks, [(None, "toàn văn tài liệu", "native")], document_id="doc_x")

    assert [chunk.content for chunk in annotated] == [chunk.content for chunk in chunks]
    assert all(chunk.retrieval_context == "Ngữ cảnh: tài liệu về quy trình QCX-77." for chunk in annotated)
    assert len(router.calls) == len(chunks)
    # Every prompt situates the chunk inside the document text.
    assert all("toàn văn tài liệu" in calls[1][1]["content"] for calls in router.calls)


def test_a_failing_chunk_degrades_to_no_context_without_failing_ingestion():
    router = _FakeRouter(errors_at={2})
    service = ChunkContextService(router, enabled=True)
    chunks = _chunks()

    annotated = service.annotate(chunks, [(None, "tài liệu", "native")], document_id="doc_x")

    assert annotated[1].retrieval_context is None
    assert annotated[0].retrieval_context and annotated[2].retrieval_context


def test_disabled_service_is_a_passthrough_with_zero_model_calls():
    router = _FakeRouter()
    service = ChunkContextService(router, enabled=False)
    chunks = _chunks()

    assert service.annotate(chunks, [(None, "tài liệu", "native")]) is chunks
    assert router.calls == []


def test_document_text_is_capped_for_the_prompt():
    router = _FakeRouter()
    service = ChunkContextService(router, enabled=True, document_char_cap=10)

    service.annotate(_chunks(1), [(None, "x" * 500, "native")], document_id="doc_x")

    prompt = router.calls[0][1][1]["content"]
    assert "x" * 10 in prompt and "x" * 11 not in prompt


def test_trim_normalizes_and_cuts_runaway_output():
    service = ChunkContextService(_FakeRouter(), enabled=True, context_tokens=4)

    assert service._trim("  ") is None
    assert service._trim("một\n  hai   ba") == "một hai ba"
    long = " ".join(f"tu{index}" for index in range(50))
    trimmed = service._trim(long)
    assert trimmed is not None and len(trimmed.split()) <= 8


def test_combined_retrieval_text_prefixes_only_when_context_exists():
    assert combined_retrieval_text(None, "nội dung") == "nội dung"
    assert combined_retrieval_text("bối cảnh", "nội dung") == "bối cảnh\n\nnội dung"


def test_contextual_index_embeds_context_but_cites_bare_content(client, mock_ollama, monkeypatch):
    """End to end through upload→index: context reaches the embedding input,
    the chunk row, and the BM25 tokens — and never the citation content."""
    monkeypatch.setattr("app.stores.qdrant_store.QdrantStore.upsert_chunks", lambda *args, **kwargs: None)
    embedded: list[str] = []
    monkeypatch.setattr(
        "app.services.postgres_document_service.PostgresDocumentService._embed_with_cache",
        lambda self, content, model, long_call=None: (embedded.append(content), [0.1, 0.2, 0.3])[1],
    )
    monkeypatch.setattr(
        "app.services.model_router.ModelRouter.chat",
        lambda self, mode, messages, **kwargs: ("Bối cảnh NGUCANHP42 về quy trình in.", "qwen3.5:9b"),
    )
    monkeypatch.setattr(client.app.state.document_service.chunk_context, "enabled", True)

    upload = client.post("/documents/upload", files={"file": ("ctx.txt", "Tài liệu nói về quy trình in ấn và báo giá.".encode(), "text/plain")})
    document_id = upload.json()["document_id"]
    response = client.post("/documents/index", json={"document_id": document_id})
    assert response.status_code == 202
    run = client.get(f"/documents/ingestions/{response.json()['ingestion_run_id']}").json()
    for _ in range(60):
        if run["status"] in {"completed", "failed"}:
            break
        time.sleep(0.03)
        run = client.get(f"/documents/ingestions/{response.json()['ingestion_run_id']}").json()
    assert run["status"] == "completed"

    from app.postgres.models import DocumentChunk as ChunkRow

    with client.app.state.document_service.sessions() as session:
        rows = list(session.scalars(select(ChunkRow).where(ChunkRow.document_id == document_id)))
    assert rows and all(row.retrieval_context == "Bối cảnh NGUCANHP42 về quy trình in." for row in rows)
    assert embedded and all(text.startswith("Bối cảnh NGUCANHP42") for text in embedded)

    from app.services.postgres_bm25_service import PostgresBm25Service

    bm25 = PostgresBm25Service(client.app.state.document_service.sessions)
    hits = bm25.search("NGUCANHP42", 5, document_id)
    assert hits and hits[0]["document_id"] == document_id
    # Citation text stays the verbatim source; the generated context never leaks into it.
    assert "NGUCANHP42" not in hits[0]["content"]

    client.delete(f"/documents/{document_id}")


def test_index_without_the_flag_stays_bytewise_identical(client, mock_ollama, monkeypatch):
    """Flag off (the default): no chat call is made and chunks carry no context."""
    monkeypatch.setattr("app.stores.qdrant_store.QdrantStore.upsert_chunks", lambda *args, **kwargs: None)

    def forbidden_chat(*args, **kwargs):
        raise AssertionError("indexing must not call the general model while the flag is off")

    monkeypatch.setattr("app.services.model_router.ModelRouter.chat", forbidden_chat)

    upload = client.post("/documents/upload", files={"file": ("plain.txt", b"Van ban khong co ngu canh sinh them.", "text/plain")})
    document_id = upload.json()["document_id"]
    response = client.post("/documents/index", json={"document_id": document_id})
    run = client.get(f"/documents/ingestions/{response.json()['ingestion_run_id']}").json()
    for _ in range(60):
        if run["status"] in {"completed", "failed"}:
            break
        time.sleep(0.03)
        run = client.get(f"/documents/ingestions/{response.json()['ingestion_run_id']}").json()
    assert run["status"] == "completed"

    from app.postgres.models import DocumentChunk as ChunkRow

    with client.app.state.document_service.sessions() as session:
        rows = list(session.scalars(select(ChunkRow).where(ChunkRow.document_id == document_id)))
    assert rows and all(row.retrieval_context is None for row in rows)

    client.delete(f"/documents/{document_id}")
