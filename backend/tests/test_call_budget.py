"""A turn's model calls are counted and capped (ticket 43, README.en rule 5).

The rule: one generation call on the default path, and three exceptions of one extra call
each (the follow-up rewrite, the figures retry, the tool-call retry). Each path is driven to
its worst case through the real ModelRouter, with a scripted client under it, so a call
added anywhere in chat_service / rag_service / agent_service shows up as an overrun. The
worst case must also reach the cap exactly: a cap with room in it would let a fourth call
through. No stack: the client is a fake and the model is scripted.
"""
from __future__ import annotations

import pytest

from app.llm_clients.ollama_client import OllamaClient, OllamaToolCallParseError
from app.services.agent_service import AgentService
from app.services.call_budget import (
    CHAT_CALL_CAP,
    OVERRUNS,
    RAG_CALL_CAP,
    agent_call_cap,
    turn_call_budget,
)
from app.services.chat_service import ChatService
from app.services.model_router import ModelRouter
from app.services.rag_service import RagService

PARSE = OllamaToolCallParseError("Ollama could not parse the model's tool call")
INVENTED = "Phụ cấp lưu trú là 100.000 - 200.000 VNĐ/ngày."
QUESTION = "Phụ cấp lưu trú là bao nhiêu?"


def final(text: str) -> dict:
    return {"content": text, "tool_calls": [], "raw_tool_calls": []}


def search(query: str) -> dict:
    arguments = {"query": query}
    return {"content": "", "tool_calls": [{"name": "search_documents", "arguments": arguments}], "raw_tool_calls": [{"function": {"name": "search_documents", "arguments": arguments}}]}


class ScriptedOllama(OllamaClient):
    """Counts what actually reaches the model, the number the router's count must equal."""

    def __init__(self, rounds=(), replies=("trả lời",)):
        self.rounds, self.replies = list(rounds), list(replies)
        self.calls = 0

    def chat(self, model, messages, options, keep_alive, think=None):
        self.calls += 1
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]

    def chat_tools(self, model, messages, tools, options, keep_alive, think=None):
        self.calls += 1
        round_ = self.rounds.pop(0)
        if isinstance(round_, Exception):
            raise round_
        return round_

    def stream_chat(self, model, messages, options, keep_alive, think=None):
        self.calls += 1
        yield "trả lời"


def router_over(client: ScriptedOllama) -> ModelRouter:
    return ModelRouter({"ollama": client}, {"general": {"name": "fake"}})


class Retrieval:
    def retrieve(self, query, top_k, document_id=None):
        return [{"filename": "quy_dinh.pdf", "page": 2, "content": "Phụ cấp lưu trú: 300.000 đồng/người/ngày.", "score": 0.9}]


class Store:
    """Enough of AuxiliaryStore for a follow-up turn: one earlier exchange in the conversation."""

    def conversation_exists(self, conversation_id):
        return True

    def get_messages(self, conversation_id, limit):
        return [{"role": "user", "content": QUESTION}, {"role": "assistant", "content": "300.000 đồng."}]

    def add_message(self, *args, **kwargs):
        return 1

    def delete_conversation(self, conversation_id):
        pass


class Log:
    def log_request(self, *args, **kwargs):
        pass


@pytest.fixture(autouse=True)
def clean_overruns():
    OVERRUNS.clear()
    yield
    OVERRUNS.clear()


def test_the_caps_are_what_rule_5_promises():
    assert CHAT_CALL_CAP == 1, "the default path: the answer"
    assert RAG_CALL_CAP == 2, "the follow-up rewrite, then the answer"
    assert [agent_call_cap(steps) for steps in (1, 3, 5)] == [4, 6, 8], "tool rounds + two retries + the forced answer"


def test_plain_chat_makes_one_call_whether_it_streams_or_not():
    client = ScriptedOllama()
    service = ChatService(Store(), router_over(client), Log(), history_limit=10)

    service.respond("Chào", "conv-1")
    tokens, _, _ = service.stream_response("Chào", "conv-1")
    list(tokens)

    assert client.calls == 2 * CHAT_CALL_CAP
    assert not OVERRUNS


def test_a_rag_follow_up_makes_the_rewrite_and_the_answer_and_no_more():
    client = ScriptedOllama(replies=["Phụ cấp lưu trú là bao nhiêu tiền?", "300.000 đồng."])
    service = RagService(router_over(client), Log(), Retrieval(), store=Store())

    service.respond("Còn bao nhiêu?", 5, None, "conv-1")
    assert client.calls == RAG_CALL_CAP
    tokens, *_ = service.stream_response("Còn bao nhiêu?", 5, None, "conv-1")
    list(tokens)

    assert client.calls == 2 * RAG_CALL_CAP
    assert not OVERRUNS


@pytest.mark.parametrize("max_steps", [1, 3])
def test_the_agent_at_its_worst_reaches_the_cap_exactly(max_steps):
    # A call that will not parse, an answer with figures the turn never saw, then tool rounds
    # until the allowance runs out and the forced answer: every exception used at once.
    client = ScriptedOllama(rounds=[PARSE, final(INVENTED), *[search(QUESTION)] * max_steps], replies=["hết lượt"])
    agent = AgentService(router_over(client), Retrieval(), None, max_steps=max_steps)

    answer, _, _ = agent.run([{"role": "system", "content": "Bạn là Ún."}, {"role": "user", "content": QUESTION}])

    assert answer == "hết lượt"
    assert client.calls == agent_call_cap(max_steps)
    assert not OVERRUNS


def test_the_agent_in_a_chat_turn_leaves_the_count_to_itself():
    client = ScriptedOllama(rounds=[search(QUESTION), final("Phụ cấp lưu trú là 300.000 đồng.")])
    service = ChatService(Store(), router_over(client), Log(), history_limit=10)
    service.agent_service = AgentService(router_over(client), Retrieval(), None, max_steps=3)
    service.store.add_agent_traces = lambda *args, **kwargs: None

    service.respond(QUESTION, "conv-1", use_tools=True)

    assert client.calls == 2
    assert not OVERRUNS


def test_a_call_added_to_a_turn_is_recorded_with_the_turn_and_its_cap():
    class Chattier(RagService):
        def _condense_question(self, question, conversation_id, created):
            self.router.chat("general", [{"role": "user", "content": "một lần nữa"}])
            return super()._condense_question(question, conversation_id, created)

    client = ScriptedOllama(replies=["Phụ cấp lưu trú là bao nhiêu tiền?", "300.000 đồng."])
    Chattier(router_over(client), Log(), Retrieval(), store=Store()).respond("Còn bao nhiêu?", 5, None, "conv-1")

    assert client.calls == RAG_CALL_CAP + 1, "the turn still ran: an overrun is recorded, not blocked"
    assert list(OVERRUNS) == [("rag", RAG_CALL_CAP, RAG_CALL_CAP + 1)]


def test_calls_outside_a_turn_are_not_counted():
    client = ScriptedOllama()
    router = router_over(client)

    for _ in range(5):
        router.chat("general", [{"role": "user", "content": "chỉ mục hoá"}])
    with turn_call_budget("chat", CHAT_CALL_CAP):
        router.chat("general", [{"role": "user", "content": "một"}])

    assert client.calls == 6 and not OVERRUNS
