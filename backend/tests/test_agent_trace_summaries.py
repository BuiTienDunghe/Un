"""The content-free trace outlives the conversation, and carries no content (ticket 16, commit 4).

The owner's option (b): the skeleton of every agent step — tool, latency, error code,
tokens, hashes — survives deleting the conversation; the arguments, results and answer
still go with it. The strongest check is a bait: a distinctive string planted in the
question, the tool result and the answer, then looked for in every text and JSONB
column the summary table has, read off information_schema so a column added later is
scanned too. Real PostgreSQL; the model is scripted at the OllamaClient seam.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import delete, func, select, text

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import AgentTrace, AgentTraceSummary
from app.discord import agent_tools
from app.services.agent_service import arguments_shape, core_tools

URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")

QUESTION_BAIT = "mồi-câu-hỏi-7Q4ZK"
RESULT_BAIT = "mồi-kết-quả-9R2XW"
ANSWER_BAIT = "mồi-câu-trả-lời-3T8LM"


@pytest.fixture
def factory():
    return create_session_factory(create_postgres_engine(str(URL)))


def scripted(responses: list[dict]):
    queue = list(responses)

    def fake(self, model, messages, tools, options, keep_alive, think=None):
        return queue.pop(0) if queue else {"content": "hết", "tool_calls": [], "raw_tool_calls": []}

    return fake


class BaitedRetrieval:
    def retrieve(self, query, top_k, document_id=None):
        return [{"filename": "bang_gia.pdf", "page": 1, "content": f"Giá vé {RESULT_BAIT} là 120.000 đồng", "score": 0.9}]


def run_baited_turn(client, monkeypatch) -> dict:
    arguments = {"query": f"giá vé {QUESTION_BAIT}", "top_k": 3, QUESTION_BAIT: "khoá do model bịa"}
    # A tool name is model output too (fable's review): an invented one carrying the bait.
    invented = f"tra_cuu_{QUESTION_BAIT}"
    calls = [{"name": "search_documents", "arguments": arguments}, {"name": invented, "arguments": {}}]
    monkeypatch.setattr(client.app.state.agent_service, "retrieval_service", BaitedRetrieval())
    monkeypatch.setattr("app.llm_clients.ollama_client.OllamaClient.chat_tools", scripted([
        {"content": "", "tool_calls": calls,
         "raw_tool_calls": [{"function": call} for call in calls]},
        {"content": f"Vé 120.000 đồng {ANSWER_BAIT}", "tool_calls": [], "raw_tool_calls": []},
    ]))
    response = client.post("/chat", json={"message": f"Giá vé bao nhiêu? {QUESTION_BAIT}", "use_tools": True})
    assert response.status_code == 200
    return response.json()


def summaries(factory, conversation_id: str) -> list[AgentTraceSummary]:
    with factory() as session:
        return list(session.scalars(
            select(AgentTraceSummary).where(AgentTraceSummary.conversation_id == conversation_id).order_by(AgentTraceSummary.step_index)
        ))


def test_the_summary_keeps_no_string_from_the_question_the_result_or_the_answer(client, mock_ollama, factory, monkeypatch):
    body = run_baited_turn(client, monkeypatch)
    conversation_id = body["conversation_id"]
    try:
        with factory() as session:
            columns = [row[0] for row in session.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'agent_trace_summaries' AND data_type IN ('text', 'character varying', 'jsonb')"
            ))]
            assert {"conversation_id", "arguments_shape", "content_sha256"} <= set(columns)
            for column in columns:
                values = session.execute(text(
                    f'SELECT "{column}"::text FROM agent_trace_summaries WHERE conversation_id = :c'
                ), {"c": conversation_id}).scalars().all()
                assert values, f"no summary rows to scan in {column}"
                for value in values:
                    for bait in (QUESTION_BAIT, RESULT_BAIT, ANSWER_BAIT):
                        assert bait not in (value or ""), f"{column} carries {bait!r}: {value!r}"
            # The full trace really did carry them: the scan above is not vacuous.
            stored = " ".join(str(row.tool_name) + str(row.arguments) + str(row.content) for row in session.scalars(
                select(AgentTrace).where(AgentTrace.conversation_id == conversation_id)))
            assert QUESTION_BAIT in stored and RESULT_BAIT in stored and ANSWER_BAIT in stored
    finally:
        client.delete(f"/conversations/{conversation_id}")
        with factory.begin() as session:
            session.execute(delete(AgentTraceSummary).where(AgentTraceSummary.conversation_id == conversation_id))


def test_deleting_the_conversation_takes_the_content_and_keeps_the_skeleton(client, mock_ollama, factory, monkeypatch):
    body = run_baited_turn(client, monkeypatch)
    conversation_id = body["conversation_id"]
    try:
        before = summaries(factory, conversation_id)
        assert [(row.kind, row.tool_name) for row in before] == [
            ("tool_call", "search_documents"), ("tool_result", "search_documents"),
            ("tool_call", "unknown"), ("tool_result", "unknown"), ("final", None)]
        assert before[3].error_code == "UNKNOWN_TOOL"
        assert before[0].arguments_shape == {"query": f"str:{len('giá vé ' + QUESTION_BAIT)}", "top_k": 3, "_undeclared": 1}
        assert before[1].content_sha256 and before[1].error_code is None
        assert before[-1].stop_reason == "final" and before[0].source == "web"
        assert before[0].message_id is not None

        assert client.delete(f"/conversations/{conversation_id}").status_code in (200, 204)

        with factory() as session:
            traces = session.scalar(select(func.count()).select_from(AgentTrace).where(AgentTrace.conversation_id == conversation_id))
        after = summaries(factory, conversation_id)
        assert traces == 0, "the content went with the conversation"
        assert [(row.step_index, row.kind, row.content_sha256) for row in after] == [
            (row.step_index, row.kind, row.content_sha256) for row in before], "the skeleton did not"
    finally:
        with factory.begin() as session:
            session.execute(delete(AgentTraceSummary).where(AgentTraceSummary.conversation_id == conversation_id))


def test_a_discord_turn_is_marked_as_such(client, factory):
    store = client.app.state.auxiliary_store
    conversation_id = "ticket16-discord-source"
    store.create_conversation(conversation_id, "discord")
    message_id = store.add_message(conversation_id, "assistant", "xong")
    try:
        store.add_agent_traces(conversation_id, message_id, [
            {"kind": "final", "content": "xong", "latency_ms": 5, "stop_reason": "final"}], source="discord")
        assert [row.source for row in summaries(factory, conversation_id)] == ["discord"]
    finally:
        store.delete_conversation(conversation_id)
        with factory.begin() as session:
            session.execute(delete(AgentTraceSummary).where(AgentTraceSummary.conversation_id == conversation_id))


def test_the_shape_of_arguments_keeps_types_and_lengths_only():
    registry = core_tools()
    agent_tools.register(registry, None)  # the API's tool list (ticket 22, C4)
    declared = registry.declared()
    assert arguments_shape("search_history", {"query": "ai nói", "limit": 5, "days": "7", "author_id": "1001"}, declared) == {
        "query": "str:6", "limit": 5, "days": "str:1", "author_id": "str:4"}
    assert arguments_shape("search_documents", {"query": None, "top_k": True}, declared) == {"query": "NoneType", "top_k": "bool"}
    assert arguments_shape("no_such_tool", {"anything": "bí mật"}, declared) == {"_undeclared": 1}
    assert arguments_shape("search_documents", "not a dict", declared) is None
