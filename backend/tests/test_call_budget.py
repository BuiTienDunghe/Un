"""A turn's model calls are counted and capped (ticket 43, README.en rule 5).

The rule: one generation call on the default path, and three exceptions of one extra call
each (the follow-up rewrite, the figures retry, the tool-call retry), and a fourth that ships
off (ticket 45): a paste too long for the window read in parts, one call per part, in a
budget of its own so the agent's cap is not touched. Each path is driven to
its worst case through the real ModelRouter, with a scripted client under it, so a call
added anywhere in chat_service / rag_service / agent_service shows up as an overrun. The
worst case must also reach the cap exactly: a cap with room in it would let a fourth call
through. No stack: the client is a fake and the model is scripted.
"""
from __future__ import annotations

import pytest

from app.llm_clients.ollama_client import OllamaClient, OllamaToolCallParseError
from app.services.agent_service import AgentService
from app.services import long_input
from app.services.call_budget import (
    CHAT_CALL_CAP,
    OVERRUNS,
    RAG_CALL_CAP,
    agent_call_cap,
    long_input_call_cap,
    turn_call_budget,
)
from app.services.chat_service import ChatService
from app.services.long_input import LONG_INPUT_MAX_PARTS, part_chars, split_parts
from app.services.model_router import ModelRouter
from app.services.pastes import INLINE_MAX_TOKENS, PASTE_MAX
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
    assert [long_input_call_cap(parts) for parts in (1, 3, LONG_INPUT_MAX_PARTS)] == [1, 3, 8], "one call per part read"


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
def test_the_agent_with_the_lookup_check_on_reaches_its_one_larger_cap_exactly(max_steps):
    # Harness-fix round: the lookup check is one more retry, off by default. Every retry at once:
    # a call that will not parse, an answer that gave up before any lookup, one with invented
    # figures, then tool rounds until the allowance runs out and the forced answer.
    gave_up = final("Tôi không có thông tin về việc này, tôi cần tìm kiếm trong tài liệu.")
    client = ScriptedOllama(rounds=[PARSE, gave_up, final(INVENTED), *[search(QUESTION)] * max_steps], replies=["hết lượt"])
    agent = AgentService(router_over(client), Retrieval(), None, max_steps=max_steps, lookup_check=True)

    answer, _, steps = agent.run([{"role": "system", "content": "Bạn là Ún."}, {"role": "user", "content": QUESTION}])

    assert answer == "hết lượt" and "lookup_check" in [step["kind"] for step in steps]
    assert client.calls == agent_call_cap(max_steps, lookup_check=True) == agent_call_cap(max_steps) + 1
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


# --- the fourth exception: a paste read in parts (ticket 45) ---------------------------------

# 100 000 characters, the longest paste the API takes: three parts at the shipped 16k window.
PASTE = ("Mục họp thường lệ, không có gì đáng chú ý. " * 24 + "\n\n") * (PASTE_MAX // 1_000)
PASTE = PASTE[: PASTE_MAX - 60] + "\n\nPhụ cấp lưu trú là bao nhiêu?"
NOTE = "Ghi chú: phụ cấp lưu trú là 300.000 đồng."


def reading_agent(client: ScriptedOllama, router_class=ModelRouter) -> AgentService:
    return AgentService(router_class({"ollama": client}, {"general": {"name": "fake"}}), Retrieval(), None, max_steps=3, long_input=True)


def capture_reading_budget(monkeypatch) -> list:
    """The reading pass's own budget, caught as it is opened so the test can read its count."""
    opened = []

    class Capturing:
        def __init__(self, turn, cap):
            self.inner = turn_call_budget(turn, cap)

        def __enter__(self):
            opened.append(self.inner.__enter__())
            return opened[-1]

        def __exit__(self, *exc):
            return self.inner.__exit__(*exc)

    monkeypatch.setattr(long_input, "turn_call_budget", Capturing)
    return opened


def test_a_paste_read_in_parts_at_its_worst_uses_its_own_cap_exactly_and_leaves_the_agents_alone(monkeypatch):
    opened = capture_reading_budget(monkeypatch)
    parts = len(split_parts(PASTE, part_chars(INLINE_MAX_TOKENS)))
    client = ScriptedOllama(rounds=[final("Phụ cấp lưu trú là 300.000 đồng.")], replies=[NOTE])

    answer, _, steps = reading_agent(client).run([{"role": "user", "content": PASTE}])

    assert answer == "Phụ cấp lưu trú là 300.000 đồng."
    assert parts == 3 and client.calls == parts + 1, "a call a part, and the agent's one round"
    assert [(turn.turn, turn.used, turn.cap) for turn in opened] == [("agent_long_input", parts, long_input_call_cap(parts))], "no room in the cap"
    assert not OVERRUNS


def test_the_agents_own_cap_is_still_reached_exactly_with_the_reading_on(monkeypatch):
    # Every exception of the agent at once after the reading: an unparseable call, figures never seen,
    # then tool rounds until the allowance runs out and the forced answer. The reading adds to none of it.
    opened = capture_reading_budget(monkeypatch)
    client = ScriptedOllama(rounds=[PARSE, final(INVENTED), *[search(QUESTION)] * 3], replies=[NOTE, NOTE, NOTE, "hết lượt"])

    reading_agent(client).run([{"role": "user", "content": PASTE}])

    assert client.calls == 3 + agent_call_cap(3), "the parts, then exactly the agent's cap"
    assert opened[0].used == opened[0].cap == 3
    assert not OVERRUNS


def test_a_call_added_to_a_part_is_recorded_against_the_reading_and_not_the_agent():
    class Chattier(ModelRouter):
        def chat(self, mode, messages, options=None):
            if str(messages[0]["content"]).startswith(long_input.NOTE_INSTRUCTION[:20]):
                super().chat(mode, messages, options)
            return super().chat(mode, messages, options)

    client = ScriptedOllama(rounds=[final("Phụ cấp lưu trú là 300.000 đồng.")], replies=[NOTE])

    reading_agent(client, Chattier).run([{"role": "user", "content": PASTE}])

    assert client.calls == 2 * 3 + 1, "the turn still ran: an overrun is recorded, not blocked"
    assert OVERRUNS[0] == ("agent_long_input", 3, 4)
    assert {turn for turn, _, _ in OVERRUNS} == {"agent_long_input"}


def test_with_the_reading_off_the_same_paste_costs_the_agents_calls_only():
    client = ScriptedOllama(rounds=[final("Không đọc được.")])
    agent = AgentService(router_over(client), Retrieval(), None, max_steps=3)

    agent.run([{"role": "user", "content": PASTE}])

    assert client.calls == 1 and not OVERRUNS
