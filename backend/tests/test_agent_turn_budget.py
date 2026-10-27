"""The agent's whole turn has a wall clock, and running out stops it cleanly (ticket 16, commit 3).

The structured-stop family (Claude SDK, smolagents, Inspect), not the throw-it-away one:
short of time, the loop opens no new tool round and answers from what it gathered; if
even that answer does not fit, the user gets a fixed sentence naming the budget, and the
steps done so far stay in the trace. No stack and no sleeping: the agent's clock is a
fake that the scripted router advances, and the backends are fakes.
"""
from __future__ import annotations

import pytest

from app.llm_clients.deadline import request_timeout
from app.llm_clients.ollama_client import OllamaTimeoutError, OllamaUnavailableError
from app.services import agent_service as agent_module
from app.services.agent_service import AgentService
from app.services.chat_service import ChatService


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def tool_round() -> dict:
    return {"content": "", "tool_calls": [{"name": "search_documents", "arguments": {"query": "giá vé"}}],
            "raw_tool_calls": [{"function": {"name": "search_documents", "arguments": {"query": "giá vé"}}}]}


def answer(text: str) -> dict:
    return {"content": text, "tool_calls": [], "raw_tool_calls": []}


class Router:
    """Each chat_tools/chat call costs `cost` seconds of the fake clock and records the
    deadline it ran under; an Exception in the script is raised instead of returned."""

    def __init__(self, clock: Clock, rounds: list, final="đáp từ những gì đã có", cost: float = 1.0) -> None:
        self.clock, self.rounds, self.final, self.cost = clock, list(rounds), final, cost
        self.deadlines: list[float] = []
        self.final_messages: list[dict] = []

    def _spend(self) -> None:
        self.deadlines.append(request_timeout(10_000.0))
        self.clock.now += self.cost

    def chat_tools(self, mode, messages, tools):
        self._spend()
        step = self.rounds.pop(0) if self.rounds else answer("xong")
        if isinstance(step, Exception):
            raise step
        return step, "general"

    def chat(self, mode, messages, options=None):
        self._spend()
        self.final_messages = list(messages)
        if isinstance(self.final, Exception):
            raise self.final
        return self.final, "general"


class Retrieval:
    def retrieve(self, query, top_k, document_id=None):
        return [{"filename": "bang_gia.pdf", "page": 2, "content": "Vé 120.000 đồng", "score": 0.9}]


def agent(router: Router, clock: Clock, max_steps: int = 3, **budget) -> AgentService:
    return AgentService(router, Retrieval(), operational_service=None, max_steps=max_steps, clock=clock, **budget)


def final_step(steps):
    assert steps[-1]["kind"] == "final"
    return steps[-1]


def test_a_quick_answer_ends_as_final_and_its_round_ran_under_budget_minus_reserve():
    clock = Clock()
    router = Router(clock, [answer("chào bạn")])
    text, _, steps = agent(router, clock).run([{"role": "user", "content": "chào"}])

    assert text == "chào bạn" and final_step(steps)["stop_reason"] == agent_module.STOP_FINAL
    assert router.deadlines[0] == pytest.approx(90 - 20, abs=0.5)


def test_slow_rounds_stop_opening_new_ones_once_only_the_reserve_is_left():
    clock = Clock()
    router = Router(clock, [tool_round(), tool_round(), tool_round()], cost=40.0)
    text, _, steps = agent(router, clock).run([{"role": "user", "content": "giá vé?"}])

    # 40 s: 50 left, a second round may start; 80 s: 10 left < 20 reserved, it may not.
    assert len([step for step in steps if step["kind"] == "tool_call"]) == 2
    assert final_step(steps)["stop_reason"] == agent_module.STOP_TURN_BUDGET and text == "đáp từ những gì đã có"
    assert router.final_messages[-1]["content"].startswith("Hết thời gian dùng công cụ")
    assert router.deadlines[-1] == pytest.approx(10, abs=0.5), "the final answer gets what is left, not more"


def test_a_round_that_times_out_still_ends_in_an_answer_from_what_was_gathered():
    clock = Clock()
    router = Router(clock, [tool_round(), OllamaTimeoutError("slow")])
    text, _, steps = agent(router, clock).run([{"role": "user", "content": "giá vé?"}])

    assert final_step(steps)["stop_reason"] == agent_module.STOP_TURN_BUDGET and text == "đáp từ những gì đã có"
    assert any(step["kind"] == "tool_result" for step in steps), "the gathered result is kept"


def test_when_even_the_answer_does_not_fit_the_reply_names_the_configured_budget():
    clock = Clock()
    router = Router(clock, [tool_round(), OllamaTimeoutError("slow")], final=OllamaTimeoutError("slow"))
    text, _, steps = agent(router, clock, turn_budget_seconds=45, final_reserve_seconds=10).run(
        [{"role": "user", "content": "giá vé?"}])

    assert text == "Mình chưa trả lời kịp trong 45 giây. Bạn hỏi lại, hoặc hỏi hẹp hơn nhé."
    assert final_step(steps)["stop_reason"] == agent_module.STOP_TURN_BUDGET_EXHAUSTED
    assert [step["kind"] for step in steps[:2]] == ["tool_call", "tool_result"], "the work done stays in the trace"


def test_a_broken_model_is_not_reported_as_a_slow_one():
    clock = Clock()
    router = Router(clock, [tool_round()], final=OllamaUnavailableError("down"))
    with pytest.raises(OllamaUnavailableError):
        agent(router, clock, max_steps=1).run([{"role": "user", "content": "giá vé?"}])


def test_used_up_tool_rounds_keep_their_old_note_and_reason():
    clock = Clock()
    router = Router(clock, [tool_round(), tool_round(), tool_round()])
    _, _, steps = agent(router, clock).run([{"role": "user", "content": "giá vé?"}])

    assert final_step(steps)["stop_reason"] == agent_module.STOP_MAX_STEPS
    assert router.final_messages[-1]["content"].startswith("Đã dùng tối đa số lượt công cụ")


def test_the_deadline_does_not_outlive_the_turn():
    clock = Clock()
    agent(Router(clock, [answer("chào")]), clock).run([{"role": "user", "content": "chào"}])
    assert request_timeout(120.0) == 120.0


class Store:
    def __init__(self) -> None:
        self.traces: list = []

    def conversation_exists(self, conversation_id):
        return True

    def get_messages(self, conversation_id, limit):
        return []

    def add_message(self, conversation_id, role, content, model_used=None, sources=None):
        return 7

    def add_agent_traces(self, conversation_id, message_id, steps, source="web"):
        self.traces.append(steps)


class Logging:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def log_request(self, endpoint, model_used, latency_ms, status, error_code=None, **kwargs):
        self.calls.append((status, error_code))


@pytest.mark.parametrize(
    ("final", "logged"),
    [("đáp từ những gì đã có", ("ok", None)), (OllamaTimeoutError("slow"), ("error", "AGENT_TURN_BUDGET"))],
)
def test_the_request_log_counts_an_out_of_time_reply_as_an_error(final, logged):
    clock = Clock()
    logging = Logging()
    chat = ChatService(Store(), router=None, logging_service=logging, history_limit=10)
    chat.agent_service = agent(Router(clock, [tool_round(), OllamaTimeoutError("slow")], final=final), clock)

    chat.respond("giá vé?", "c1", use_tools=True)
    assert logging.calls == [logged]


class CountingRouter(Router):
    """Reports usage the way OllamaClient does: one record_usage per call."""

    def __init__(self, clock: Clock, rounds: list) -> None:
        super().__init__(clock, rounds)
        self.calls = 0

    def chat_tools(self, mode, messages, tools):
        from app.llm_clients.usage import record_usage

        self.calls += 1
        record_usage(100 * self.calls, 10 * self.calls)
        return super().chat_tools(mode, messages, tools)


def test_each_model_round_records_its_tokens_once_and_the_request_log_still_reads_the_last():
    from app.llm_clients.usage import consume_usage

    clock = Clock()
    two_calls = {"content": "", "tool_calls": [{"name": "search_documents", "arguments": {"query": "a"}},
                                               {"name": "search_documents", "arguments": {"query": "b"}}],
                 "raw_tool_calls": []}
    _, _, steps = agent(CountingRouter(clock, [two_calls, answer("xong")]), clock).run([{"role": "user", "content": "?"}])

    calls = [step for step in steps if step["kind"] == "tool_call"]
    assert [(step["tokens_in"], step["tokens_out"]) for step in calls] == [(100, 10), (None, None)]
    assert (steps[-1]["tokens_in"], steps[-1]["tokens_out"]) == (200, 20)
    # Ticket 16 (k2): what ChatService logs is the last call's usage, as before.
    assert consume_usage() == {"tokens_in": 200, "tokens_out": 20}


class SlowRetrieval(Retrieval):
    """A tool that takes `cost` seconds of the agent's clock: time spent outside any model call."""

    def __init__(self, clock: Clock, cost: float) -> None:
        self.clock, self.cost = clock, cost

    def retrieve(self, query, top_k, document_id=None):
        self.clock.now += self.cost
        return super().retrieve(query, top_k, document_id)


def test_time_eaten_by_slow_tools_ends_in_the_fixed_reply_not_a_crash():
    # 35 s model + 30 s tool per round: after two rounds 130 s are gone, so the final
    # answer has nothing left — the reserve rule only guards rounds it can see start.
    clock = Clock()
    router = Router(clock, [tool_round(), tool_round(), tool_round()], cost=35.0)
    service = AgentService(router, SlowRetrieval(clock, 30.0), operational_service=None, max_steps=3, clock=clock)
    text, _, steps = service.run([{"role": "user", "content": "giá vé?"}])

    assert text == "Mình chưa trả lời kịp trong 90 giây. Bạn hỏi lại, hoặc hỏi hẹp hơn nhé."
    assert final_step(steps)["stop_reason"] == agent_module.STOP_TURN_BUDGET_EXHAUSTED
    assert len([step for step in steps if step["kind"] == "tool_result"]) == 2
    assert len(router.deadlines) == 2, "no final model call was even attempted with no time left"
