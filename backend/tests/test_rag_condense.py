"""Condense-question behaviour (P1-2).

The retrieval monkeypatch records every query, and the Ollama chat mock
branches on the condense prompt's marker line, so each test can see exactly
which question retrieval received and whether a condense call happened.
"""
from __future__ import annotations

import pytest

CONDENSE_MARKER = "câu hỏi độc lập"
REWRITTEN = "Mô hình qwen3.5:9b chiếm khoảng bao nhiêu VRAM?"


@pytest.fixture
def recorded(monkeypatch):
    """Patch retrieval + chat; return the record of retrieval queries and condense calls."""
    record = {"queries": [], "condense_calls": 0, "condense_reply": REWRITTEN, "condense_raises": False}

    def fake_retrieve(self, query, top_k, document_id=None):
        record["queries"].append(query)
        return [{"document_id": "doc_a", "filename": "manual.pdf", "chunk_id": "chunk_1", "chunk_index": 0, "page": 3, "score": 0.9, "content": "GPU RTX A4000 16GB."}]

    def fake_chat(self, model, messages, options, keep_alive, think=None):
        if CONDENSE_MARKER in messages[0]["content"]:
            record["condense_calls"] += 1
            if record["condense_raises"]:
                raise RuntimeError("condense model down")
            return record["condense_reply"]
        return f"Mock response from {model}"

    monkeypatch.setattr("app.services.postgres_retrieval_service.PostgresRetrievalService.retrieve", fake_retrieve)
    monkeypatch.setattr("app.llm_clients.ollama_client.OllamaClient.chat", fake_chat)
    monkeypatch.setattr("app.llm_clients.ollama_client.OllamaClient.embed", lambda self, model, text: [0.1, 0.2, 0.3])
    monkeypatch.setattr("app.llm_clients.ollama_client.OllamaClient.healthcheck", lambda self: True)
    return record


def test_the_first_turn_never_condenses(client, recorded):
    response = client.post("/rag/chat", json={"message": "GPU của máy chủ là loại nào?"})

    assert response.status_code == 200
    assert recorded["condense_calls"] == 0
    assert recorded["queries"] == ["GPU của máy chủ là loại nào?"]
    assert response.json()["retrieval_question"] is None
    client.delete(f"/conversations/{response.json()['conversation_id']}")


def test_a_follow_up_retrieves_with_the_rewritten_question(client, recorded):
    first = client.post("/rag/chat", json={"message": "Mô hình nào phụ trách trò chuyện?"})
    conversation_id = first.json()["conversation_id"]

    follow = client.post("/rag/chat", json={"message": "Nó chiếm bao nhiêu VRAM?", "conversation_id": conversation_id})

    assert follow.status_code == 200
    assert recorded["condense_calls"] == 1
    # Retrieval and the answer both see the standalone question...
    assert recorded["queries"][-1] == REWRITTEN
    assert follow.json()["retrieval_question"] == REWRITTEN
    # ...but the transcript keeps what the user actually typed.
    detail = client.get(f"/conversations/{conversation_id}").json()
    user_texts = [m["content"] for m in detail["messages"] if m["role"] == "user"]
    assert user_texts[-1] == "Nó chiếm bao nhiêu VRAM?"
    client.delete(f"/conversations/{conversation_id}")


def test_condense_failure_falls_back_to_the_original_question(client, recorded):
    first = client.post("/rag/chat", json={"message": "Mô hình nào phụ trách trò chuyện?"})
    conversation_id = first.json()["conversation_id"]
    recorded["condense_raises"] = True

    follow = client.post("/rag/chat", json={"message": "Nó chiếm bao nhiêu VRAM?", "conversation_id": conversation_id})

    # A dead condense model degrades to ordinary single-question RAG.
    assert follow.status_code == 200
    assert recorded["queries"][-1] == "Nó chiếm bao nhiêu VRAM?"
    assert follow.json()["retrieval_question"] is None
    client.delete(f"/conversations/{conversation_id}")


def test_a_degenerate_rewrite_is_discarded(client, recorded):
    first = client.post("/rag/chat", json={"message": "Mô hình nào phụ trách trò chuyện?"})
    conversation_id = first.json()["conversation_id"]
    recorded["condense_reply"] = "   "

    follow = client.post("/rag/chat", json={"message": "Nó chiếm bao nhiêu VRAM?", "conversation_id": conversation_id})

    assert follow.status_code == 200
    assert recorded["queries"][-1] == "Nó chiếm bao nhiêu VRAM?"
    assert follow.json()["retrieval_question"] is None
    client.delete(f"/conversations/{conversation_id}")


def test_the_stream_path_condenses_identically(client, recorded, monkeypatch):
    monkeypatch.setattr(
        "app.llm_clients.ollama_client.OllamaClient.stream_chat",
        lambda *args, **kwargs: iter(["câu ", "trả lời"]),
    )
    first = client.post("/rag/chat", json={"message": "Mô hình nào phụ trách trò chuyện?"})
    conversation_id = first.json()["conversation_id"]

    follow = client.post("/rag/chat", json={"message": "Nó chiếm bao nhiêu VRAM?", "conversation_id": conversation_id, "stream": True})

    assert follow.status_code == 200
    assert recorded["condense_calls"] == 1
    assert recorded["queries"][-1] == REWRITTEN
    assert f'"retrieval_question": "{REWRITTEN}"' in follow.text
    client.delete(f"/conversations/{conversation_id}")
