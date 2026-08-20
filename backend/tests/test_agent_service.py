"""P2-2: the agent loop — tool selection, tracing, exhaustion, and fallbacks.

The model is scripted at the OllamaClient boundary (the same seam mock_ollama
uses), so these tests exercise the real AgentService, ChatService persistence,
the SSE contract and the trace table against real PostgreSQL.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import select

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import AgentTrace

URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")


@pytest.fixture
def factory():
    return create_session_factory(create_postgres_engine(str(URL)))


def scripted_chat_tools(responses: list[dict]):
    queue = list(responses)

    def fake(self, model, messages, tools, options, keep_alive, think=None):
        if not queue:
            return {"content": "Hết kịch bản", "tool_calls": [], "raw_tool_calls": []}
        return queue.pop(0)

    return fake


def tool_call(name: str, arguments: dict) -> dict:
    return {
        "content": "",
        "tool_calls": [{"name": name, "arguments": arguments}],
        "raw_tool_calls": [{"function": {"name": name, "arguments": arguments}}],
    }


def final(text: str) -> dict:
    return {"content": text, "tool_calls": [], "raw_tool_calls": []}


def test_agent_calls_a_tool_then_answers_and_the_trace_is_replayable(client, mock_ollama, factory, monkeypatch):
    monkeypatch.setattr(
        "app.llm_clients.ollama_client.OllamaClient.chat_tools",
        scripted_chat_tools([
            tool_call("search_memory", {"query": "sở thích trả lời"}),
            final("Bạn thích câu trả lời ngắn gọn."),
        ]),
    )

    response = client.post("/chat", json={"message": "Tôi thích kiểu trả lời nào?", "use_tools": True})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Bạn thích câu trả lời ngắn gọn."
    kinds = [step["kind"] for step in body["agent_steps"]]
    assert kinds == ["tool_call", "tool_result", "final"]
    assert body["agent_steps"][0]["tool_name"] == "search_memory"
    assert body["agent_steps"][0]["arguments"] == {"query": "sở thích trả lời"}

    # The same steps persist, attached to the assistant message (P2-2 trace).
    with factory() as session:
        rows = list(session.scalars(
            select(AgentTrace).where(AgentTrace.conversation_id == body["conversation_id"]).order_by(AgentTrace.step_index)
        ))
    assert [row.kind for row in rows] == ["tool_call", "tool_result", "final"]
    assert rows[0].message_id is not None
    replay = client.get(f"/agent/traces/{rows[0].message_id}")
    assert replay.status_code == 200
    assert [step["kind"] for step in replay.json()] == ["tool_call", "tool_result", "final"]

    client.delete(f"/conversations/{body['conversation_id']}")


def test_plain_questions_skip_tools_entirely(client, mock_ollama, monkeypatch):
    monkeypatch.setattr(
        "app.llm_clients.ollama_client.OllamaClient.chat_tools",
        scripted_chat_tools([final("Chào bạn!")]),
    )

    response = client.post("/chat", json={"message": "chào", "use_tools": True})

    body = response.json()
    assert body["answer"] == "Chào bạn!"
    assert [step["kind"] for step in body["agent_steps"]] == ["final"]
    client.delete(f"/conversations/{body['conversation_id']}")


def test_exhausted_tool_budget_forces_a_plain_answer(client, mock_ollama, monkeypatch):
    # max_steps is 3 in models.yaml: three tool rounds, then the loop must stop
    # calling tools and answer from what it has (via the plain chat path).
    monkeypatch.setattr(
        "app.llm_clients.ollama_client.OllamaClient.chat_tools",
        scripted_chat_tools([
            tool_call("search_memory", {"query": "một"}),
            tool_call("search_memory", {"query": "hai"}),
            tool_call("search_memory", {"query": "ba"}),
        ]),
    )

    response = client.post("/chat", json={"message": "Câu hỏi khó", "use_tools": True})

    body = response.json()
    assert body["answer"].startswith("Mock response from")
    steps = body["agent_steps"]
    assert [step["kind"] for step in steps] == ["tool_call", "tool_result"] * 3 + ["final"]
    client.delete(f"/conversations/{body['conversation_id']}")


def test_tool_failures_become_data_instead_of_errors(client, mock_ollama, monkeypatch):
    class BrokenRetrieval:
        def retrieve(self, query, top_k, document_id=None):
            raise RuntimeError("qdrant down")

    monkeypatch.setattr(client.app.state.agent_service, "retrieval_service", BrokenRetrieval())
    monkeypatch.setattr(
        "app.llm_clients.ollama_client.OllamaClient.chat_tools",
        scripted_chat_tools([
            tool_call("search_documents", {"query": "tài liệu"}),
            tool_call("does_not_exist", {}),
            final("Xin lỗi, công cụ đang lỗi nhưng đây là câu trả lời."),
        ]),
    )

    response = client.post("/chat", json={"message": "Trong tài liệu nói gì?", "use_tools": True})

    body = response.json()
    assert response.status_code == 200
    results = [step for step in body["agent_steps"] if step["kind"] == "tool_result"]
    assert "RuntimeError" in results[0]["content"]
    assert "không tồn tại" in results[1]["content"]
    assert body["answer"].startswith("Xin lỗi")
    client.delete(f"/conversations/{body['conversation_id']}")


def test_streaming_agent_mode_emits_steps_then_the_whole_answer(client, mock_ollama, monkeypatch):
    monkeypatch.setattr(
        "app.llm_clients.ollama_client.OllamaClient.chat_tools",
        scripted_chat_tools([
            tool_call("search_memory", {"query": "gu"}),
            final("Câu trả lời cuối."),
        ]),
    )

    response = client.post("/chat", json={"message": "Tôi thích gì?", "use_tools": True, "stream": True})

    assert response.status_code == 200
    text = response.text
    assert "event: meta" in text
    assert "event: steps" in text
    assert "event: token" in text and "Câu trả lời cuối." in text
    assert "event: done" in text

    import re

    conversation_id = re.search(r'"conversation_id":\s*"([^"]+)"', text).group(1)
    client.delete(f"/conversations/{conversation_id}")


def test_without_an_agent_service_use_tools_degrades_to_plain_chat(client, mock_ollama, monkeypatch):
    monkeypatch.setattr(client.app.state.chat_service, "agent_service", None)

    response = client.post("/chat", json={"message": "xin chào", "use_tools": True})

    body = response.json()
    assert body["answer"].startswith("Mock response from")
    assert body["agent_steps"] is None
    client.delete(f"/conversations/{body['conversation_id']}")
