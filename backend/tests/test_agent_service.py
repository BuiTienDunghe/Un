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
            tool_call("search_documents", {"query": "sở thích trả lời"}),
            final("Bạn thích câu trả lời ngắn gọn."),
        ]),
    )

    response = client.post("/chat", json={"message": "Tôi thích kiểu trả lời nào?", "use_tools": True})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Bạn thích câu trả lời ngắn gọn."
    kinds = [step["kind"] for step in body["agent_steps"]]
    assert kinds == ["tool_call", "tool_result", "final"]
    assert body["agent_steps"][0]["tool_name"] == "search_documents"
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

    # The P2-4 timeline lists the tool-using answer with its call count.
    activity = client.get("/agent/activity").json()
    assert any(
        item["kind"] == "agent_answer" and "ngắn gọn" in (item["title"] or "") and item["status"] == "1 lượt công cụ"
        for item in activity
    )

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
            tool_call("search_documents", {"query": "một"}),
            tool_call("search_documents", {"query": "hai"}),
            tool_call("search_documents", {"query": "ba"}),
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
            tool_call("search_documents", {"query": "gu"}),
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


def _bare_agent(history_backend):
    # _execute_tool never touches the router/retrieval/status backends here.
    from app.services.agent_service import AgentService

    return AgentService(
        router=None,
        retrieval_service=None,
        operational_service=None,
        history_service=history_backend,
    )


class _FakeHistoryBackend:
    def __init__(self):
        self.calls = []

    def search(self, *, guild_id, query, author_id=None, days=None, limit=5):
        from datetime import UTC, datetime

        from app.services.discord_history_service import DiscordHistoryHit

        self.calls.append({"guild_id": guild_id, "query": query, "days": days, "limit": limit})
        return [
            DiscordHistoryHit(
                discord_message_id="123",
                channel_id="chan",
                thread_id=None,
                author_id="u9",
                author_display_name="User Nine",
                is_bot=False,
                content="noi dung cu",
                sent_at=datetime(2026, 8, 20, tzinfo=UTC),
                link="https://discord.com/channels/g/chan/123",
            )
        ]


def test_search_history_uses_server_side_guild_never_model_supplied():
    backend = _FakeHistoryBackend()
    agent = _bare_agent(backend)
    output = agent._execute_tool(
        "search_history",
        # A model trying to smuggle its own guild id: ignored.
        {"query": "ai noi gi", "guild_id": "attacker-guild"},
        {"guild_id": "real-guild"},
    )
    assert backend.calls == [
        {"guild_id": "real-guild", "query": "ai noi gi", "days": None, "limit": 5}
    ]
    assert "noi dung cu" in output
    assert "User Nine" in output


def test_search_history_refuses_without_guild_context():
    backend = _FakeHistoryBackend()
    agent = _bare_agent(backend)
    output = agent._execute_tool("search_history", {"query": "ai noi gi"}, None)
    assert backend.calls == []
    assert "Discord" in output


def test_search_history_without_query_returns_recent_in_time_order():
    backend = _FakeHistoryBackend()

    def fake_recent(*, guild_id, limit=20, author_id=None):
        backend.calls.append(
            {"mode": "recent", "guild_id": guild_id, "limit": limit, "author_id": author_id}
        )
        return backend.search(guild_id=guild_id, query="")

    backend.recent = fake_recent
    agent = _bare_agent(backend)
    output = agent._execute_tool(
        "search_history",
        {"limit": 20},
        {"guild_id": "real-guild"},
    )
    assert backend.calls[0] == {
        "mode": "recent", "guild_id": "real-guild", "limit": 20, "author_id": None
    }
    assert "noi dung cu" in output
