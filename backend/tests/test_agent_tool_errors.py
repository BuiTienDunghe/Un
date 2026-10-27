"""A failed tool call reaches the model as a sentence plus a code (ticket 16, commit 1).

The sentence says what to do next; the code is for the trace. Before this, the model
read free text — "TypeError: ..." for a broken tool, and on the web a search_history
refusal it answered by asking "which server?" (Agent Eval hist-10). No stack: every
backend is a fake, and the loop runs on a scripted router.
"""
from __future__ import annotations

import json

import pytest

from app.discord import agent_tools
from app.services import agent_service as agent_module
from app.services.agent_service import AgentService


class Retrieval:
    def __init__(self, chunks=None, error: Exception | None = None):
        self.chunks, self.error = chunks or [], error

    def retrieve(self, query, top_k, document_id=None):
        if self.error is not None:
            raise self.error
        return self.chunks


class ScriptedRouter:
    """chat_tools answers from a script; chat is the forced final answer."""

    def __init__(self, rounds: list[dict]):
        self.rounds = list(rounds)

    def chat_tools(self, mode, messages, tools):
        if self.rounds:
            return self.rounds.pop(0), "general"
        return {"content": "xong", "tool_calls": [], "raw_tool_calls": []}, "general"

    def chat(self, mode, messages, options=None):
        return "xong", "general"


def call(name: str, arguments: dict) -> dict:
    return {"content": "", "tool_calls": [{"name": name, "arguments": arguments}],
            "raw_tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


def agent(retrieval=None, router=None, history=None) -> AgentService:
    service = AgentService(router=router, retrieval_service=retrieval or Retrieval(), operational_service=None)
    agent_tools.register(service.registry, history)  # search_history, as the API plugs it in (ticket 22, C4)
    return service


@pytest.mark.parametrize(
    ("name", "arguments", "context", "code"),
    [
        ("search_history", {"query": "ai nói gì"}, None, agent_module.TOOL_UNAVAILABLE_HERE),
        ("search_documents", {"query": "   "}, None, agent_module.BAD_ARGUMENTS),
        ("delete_everything", {}, None, agent_module.UNKNOWN_TOOL),
    ],
)
def test_each_refusal_carries_its_code_and_a_sentence(name, arguments, context, code):
    text, error_code, error_type = agent()._run_tool(name, arguments, context)
    payload = json.loads(text)

    assert error_code == code and payload["code"] == code and error_type is None
    assert isinstance(payload["error"], str) and len(payload["error"]) > 20


def test_the_web_refusal_tells_the_model_not_to_ask_which_server():
    payload = json.loads(agent()._execute_tool("search_history", {"query": "ai nói gì"}, None))
    assert "Đừng hỏi người dùng server nào" in payload["error"]


def test_an_unknown_tool_is_told_which_tools_exist():
    payload = json.loads(agent()._execute_tool("delete_everything", {}, None))
    assert all(name in payload["error"] for name in ("search_documents", "search_history", "system_status"))


def test_a_broken_tool_keeps_its_exception_out_of_what_the_model_reads():
    broken = agent(Retrieval(error=RuntimeError("qdrant down at 10.0.0.7")))
    text, error_code, error_type = broken._run_tool("search_documents", {"query": "giá vé"}, None)

    assert error_code == agent_module.TOOL_FAILED and error_type == "RuntimeError"
    assert "RuntimeError" not in text and "qdrant down" not in text and "10.0.0.7" not in text
    assert "Đừng gọi lại" in json.loads(text)["error"]


def test_an_empty_result_is_a_result_not_an_error():
    text, error_code, error_type = agent(Retrieval(chunks=[]))._run_tool("search_documents", {"query": "giá vé"}, None)
    assert error_code is None and error_type is None and "error" not in json.loads(text)


def test_the_loop_records_each_tool_results_code_in_its_step():
    router = ScriptedRouter([call("search_documents", {"query": "giá vé"}), call("delete_everything", {})])
    _, _, steps = agent(Retrieval(error=RuntimeError("down")), router=router).run([{"role": "user", "content": "giá vé?"}])

    results = [step for step in steps if step["kind"] == "tool_result"]
    assert [(step["error_code"], step["error_type"]) for step in results] == [
        (agent_module.TOOL_FAILED, "RuntimeError"), (agent_module.UNKNOWN_TOOL, None)]
    # Only a declared name may reach the content-free trace (fable's review).
    assert [step["tool_declared"] for step in results] == [True, False]
