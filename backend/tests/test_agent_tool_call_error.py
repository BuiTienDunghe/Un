"""A tool call Ollama could not parse no longer loses the turn (ticket 27).

doc-44 on 2839b52: the model wrote a call Ollama rejected with a 500 ("XML syntax error on
line 12: element <function> closed by </parameter>"), the client sent the same request three
times, got the same rejection at temperature 0, and the turn ended in "Cannot connect to
Ollama". Now the client raises OllamaToolCallParseError at once, and the agent retries once
with a note, in a round of its own while the final reserve is still free; failing again, or
with no time for it, it answers from what was gathered, without tools. No stack: the backends
are fakes and the model is scripted.
"""
from __future__ import annotations

import json

import pytest

from app.llm_clients.ollama_client import OllamaToolCallParseError, OllamaUnavailableError
from app.services.agent_service import (
    ANSWER_CHECK_STEP,
    STOP_FINAL,
    STOP_TOOL_CALL_ERROR,
    TOOL_CALL_ERROR_LABEL,
    TOOL_CALL_ERROR_STEP,
    TOOL_CALL_PARSE,
    TOOL_CALL_RETRY,
    AgentService,
)

SERVER = "XML syntax error on line 12: element <function> closed by </parameter>"
PARSE = OllamaToolCallParseError(f"Ollama could not parse the model's tool call: {SERVER}")
FORCED = "Không gọi được công cụ nữa. Trả lời ngay bằng những gì đã thu thập được."
INVENTED = "Phụ cấp lưu trú là 100.000 - 200.000 VNĐ/ngày."
HONEST = "Mình chưa tra được tài liệu nào nói về phụ cấp lưu trú."


def final(text: str) -> dict:
    return {"content": text, "tool_calls": [], "raw_tool_calls": []}


def search(query: str) -> dict:
    arguments = {"query": query}
    return {"content": "", "tool_calls": [{"name": "search_documents", "arguments": arguments}], "raw_tool_calls": [{"function": {"name": "search_documents", "arguments": arguments}}]}


class Router:
    """Scripted rounds; an exception in the script is raised by that round."""

    def __init__(self, rounds, forced: str = "đáp án không công cụ"):
        self.rounds, self.forced = list(rounds), forced
        self.prompts: list[list[dict]] = []
        self.forced_prompts: list[list[dict]] = []

    def chat_tools(self, role, messages, tools):
        self.prompts.append([dict(message) for message in messages])
        round_ = self.rounds.pop(0)
        if isinstance(round_, Exception):
            raise round_
        return round_, "fake"

    def chat(self, role, messages):
        self.forced_prompts.append([dict(message) for message in messages])
        return self.forced, "fake"


class Retrieval:
    def retrieve(self, query, top_k, document_id=None):
        return [{"filename": "quy_dinh.pdf", "page": 2, "content": "Phụ cấp lưu trú: 300.000 đồng/người/ngày.", "score": 0.9}]


class Clock:
    def __init__(self, ticks):
        self.ticks = list(ticks)

    def __call__(self):
        return self.ticks.pop(0) if len(self.ticks) > 1 else self.ticks[0]


def run(rounds, **kwargs):
    router = Router(rounds)
    events: list[dict] = []
    agent = AgentService(router, Retrieval(), None, **kwargs)
    messages = [{"role": "system", "content": "Bạn là Ún."}, {"role": "user", "content": "Phụ cấp lưu trú là bao nhiêu?"}]
    answer, _, steps = agent.run(messages, on_step=events.append)
    return answer, steps, router, events


def kinds(steps) -> list[str]:
    return [str(step["kind"]) for step in steps]


def test_a_call_that_will_not_parse_is_retried_once_with_a_note_and_then_answered():
    answer, steps, router, events = run([PARSE, final(HONEST)])

    assert answer == HONEST
    assert kinds(steps) == [TOOL_CALL_ERROR_STEP, "final"] and steps[-1]["stop_reason"] == STOP_FINAL
    assert len(router.prompts) == 2 and router.forced_prompts == []
    # The retry sees what the first round saw, and the note after it; nothing of the broken call.
    assert router.prompts[1][:-1] == router.prompts[0]
    assert router.prompts[1][-1] == {"role": "system", "content": TOOL_CALL_RETRY}
    assert all(message["content"] != TOOL_CALL_RETRY for message in router.prompts[0])
    assert ("tool_call_error", TOOL_CALL_ERROR_LABEL) in [(event["kind"], event.get("label")) for event in events]


def test_the_failed_round_keeps_no_text():
    _, steps, _, events = run([PARSE, final("xong")])

    step = steps[0]
    assert step["error_code"] == TOOL_CALL_PARSE
    assert (step["tool_name"], step["arguments"], step["content"], step["tokens_in"], step["tokens_out"]) == (None, None, None, None, None)
    assert isinstance(step["latency_ms"], int)
    assert "XML" not in json.dumps(steps, ensure_ascii=False) and "XML" not in json.dumps(events, ensure_ascii=False)


def test_after_a_tool_round_the_retry_keeps_what_was_gathered():
    _, steps, router, _ = run([search("phụ cấp lưu trú"), PARSE, final("Phụ cấp lưu trú là 300.000 đồng.")])

    assert kinds(steps) == ["tool_call", "tool_result", TOOL_CALL_ERROR_STEP, "final"]
    assert router.prompts[2][:-1] == router.prompts[1] and router.prompts[1][-1]["role"] == "tool"
    assert steps[-1]["stop_reason"] == STOP_FINAL and "error_code" not in steps[-1], "300.000 came from the tool result"


def test_failing_again_answers_without_tools():
    answer, steps, router, _ = run([PARSE, PARSE])

    assert answer == "đáp án không công cụ"
    assert kinds(steps) == [TOOL_CALL_ERROR_STEP, TOOL_CALL_ERROR_STEP, "final"]
    assert steps[-1]["stop_reason"] == STOP_TOOL_CALL_ERROR
    assert len(router.prompts) == 2, "one retry, never two"
    assert router.forced_prompts[0][-1] == {"role": "system", "content": FORCED}


def test_with_the_reserve_spent_there_is_no_retry():
    # Started at 0, the round fails at 75 s: 15 s left, under the 20 s reserve.
    answer, steps, router, events = run([PARSE, final("không tới đây")], clock=Clock([0.0, 0.0, 75.0]))

    assert answer == "đáp án không công cụ"
    assert kinds(steps) == [TOOL_CALL_ERROR_STEP, "final"] and steps[-1]["stop_reason"] == STOP_TOOL_CALL_ERROR
    assert len(router.prompts) == 1
    assert "tool_call_error" not in [event["kind"] for event in events], "nothing is retried, so nothing says so"


def test_the_retry_has_a_round_of_its_own():
    # One tool round allowed: the retry does not spend it.
    _, steps, router, _ = run([PARSE, final(HONEST)], max_steps=1)

    assert kinds(steps) == [TOOL_CALL_ERROR_STEP, "final"] and steps[-1]["stop_reason"] == STOP_FINAL
    assert router.forced_prompts == []


@pytest.mark.parametrize("script, expected", [
    ([PARSE, final(INVENTED), final(HONEST)], [TOOL_CALL_ERROR_STEP, ANSWER_CHECK_STEP, "final"]),
    ([final(INVENTED), PARSE, final(HONEST)], [ANSWER_CHECK_STEP, TOOL_CALL_ERROR_STEP, "final"]),
])
def test_the_answer_check_and_this_retry_each_have_their_own(script, expected):
    answer, steps, router, _ = run(script, max_steps=1)

    assert answer == HONEST
    assert kinds(steps) == expected and steps[-1]["stop_reason"] == STOP_FINAL
    assert router.forced_prompts == []


def test_any_other_unavailable_model_still_ends_the_turn():
    with pytest.raises(OllamaUnavailableError, match="Cannot connect"):
        run([OllamaUnavailableError("Cannot connect to Ollama")])


def test_without_a_parse_error_the_turn_is_what_it_was():
    _, steps, router, events = run([search("phụ cấp lưu trú"), final("Phụ cấp lưu trú là 300.000 đồng.")])

    assert kinds(steps) == ["tool_call", "tool_result", "final"]
    assert not any(message["content"] == TOOL_CALL_RETRY for prompt in router.prompts for message in prompt)
    assert "tool_call_error" not in [event["kind"] for event in events]
