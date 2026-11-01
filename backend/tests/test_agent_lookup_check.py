"""The lookup check: an answer that gives up before any lookup gets one retry (harness-fix round, 02/11).

doc-25 of Agent Eval v0.8 is the case: asked who may delete an uploaded original, the agent called
no tool and wrote "Tôi không có thông tin ... tôi cần: 1. Tìm kiếm trong các tài liệu đã tải lên".
It named the tool it had not used. With the check on, a turn that has called nothing, with a lookup
tool offered, whose answer says it has no information or needs to search, is sent back once, in a
round of its own, to look. Off by default. No stack: the backends are fakes and the model is scripted.
"""
from __future__ import annotations

import json

import pytest

from app.services.agent_service import (
    ANSWER_CHECK_STEP,
    LOOKUP_CHECK_STEP,
    LOOKUP_GAVE_UP,
    LOOKUP_RETRY,
    AgentService,
    ToolRegistry,
)
from app.services.call_budget import agent_call_cap

GAVE_UP = "Tôi không có thông tin cụ thể về chính sách này. Để trả lời, tôi cần tìm kiếm trong các tài liệu đã tải lên."
FOUND = "Chỉ quản trị viên được xoá, và phải xác nhận hai bước (xuong_in_anh_duong.txt)."


def final(text: str) -> dict:
    return {"content": text, "tool_calls": [], "raw_tool_calls": []}


def call(name: str, arguments: dict) -> dict:
    return {"content": "", "tool_calls": [{"name": name, "arguments": arguments}], "raw_tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


class Router:
    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.prompts: list[list[dict]] = []

    def chat_tools(self, role, messages, tools):
        self.prompts.append([dict(message) for message in messages])
        return self.rounds.pop(0), "fake"

    def chat(self, role, messages):
        self.prompts.append([dict(message) for message in messages])
        return "hết lượt", "fake"


class Retrieval:
    def retrieve(self, query, top_k, document_id=None):
        return [{"filename": "xuong_in_anh_duong.txt", "page": None, "content": "Chỉ quản trị viên được xoá tài liệu gốc.", "score": 0.9}]


class Clock:
    def __init__(self, ticks):
        self.ticks = list(ticks)

    def __call__(self):
        return self.ticks.pop(0) if len(self.ticks) > 1 else self.ticks[0]


def run(rounds, user="Ai được phép xoá tài liệu gốc?", check=True, **kwargs):
    router = Router(rounds)
    agent = AgentService(router, Retrieval(), None, lookup_check=check, **kwargs)
    answer, _, steps = agent.run([{"role": "system", "content": "Bạn là Ún."}, {"role": "user", "content": user}])
    return answer, steps, router


def test_it_is_off_by_default():
    router = Router([final(GAVE_UP)])
    answer, _, steps = AgentService(router, Retrieval(), None).run([{"role": "user", "content": "Ai được phép xoá tài liệu gốc?"}])
    assert answer == GAVE_UP and [s["kind"] for s in steps] == ["final"] and len(router.prompts) == 1


def test_giving_up_before_any_lookup_gets_one_retry_and_the_rejected_text_is_kept_nowhere():
    answer, steps, router = run([final(GAVE_UP), call("search_documents", {"query": "xoá tài liệu gốc"}), final(FOUND)])

    assert answer == FOUND
    assert [s["kind"] for s in steps] == [LOOKUP_CHECK_STEP, "tool_call", "tool_result", "final"]
    rejected = steps[0]
    assert rejected["content"] is None and rejected["arguments"] is None
    assert GAVE_UP not in json.dumps(steps, ensure_ascii=False), "the trace keeps that it happened, not the text"
    retry_prompt = router.prompts[1]
    assert retry_prompt[-2] == {"role": "assistant", "content": GAVE_UP}
    assert retry_prompt[-1] == {"role": "system", "content": LOOKUP_RETRY}


def test_the_retry_asks_for_a_first_answer_with_no_apology_and_no_word_of_the_check():
    assert LOOKUP_RETRY.endswith("không xin lỗi, không nhắc tới việc kiểm tra này.")


def test_one_retry_never_two():
    answer, steps, router = run([final(GAVE_UP), final(GAVE_UP)])
    assert answer == GAVE_UP and len(router.prompts) == 2
    assert [s["kind"] for s in steps] == [LOOKUP_CHECK_STEP, "final"]


def test_an_answer_that_does_not_give_up_is_left_alone():
    _, steps, router = run([final("Chào bạn, mình giúp được gì?")], user="Chào")
    assert [s["kind"] for s in steps] == ["final"] and len(router.prompts) == 1


def test_a_turn_that_already_looked_something_up_is_left_alone():
    _, steps, router = run([call("search_documents", {"query": "x"}), final("Tôi không tìm thấy thông tin này trong tài liệu.")])
    assert [s["kind"] for s in steps] == ["tool_call", "tool_result", "final"] and len(router.prompts) == 2


def test_a_registry_with_no_lookup_tool_is_left_alone():
    # BFCL's registry holds the task's own functions: nothing there to look in.
    router = Router([final(GAVE_UP)])
    agent = AgentService(router, None, None, registry=ToolRegistry(), lookup_check=True)
    answer, _, steps = agent.run([{"role": "user", "content": "Ai được phép xoá tài liệu gốc?"}])
    assert answer == GAVE_UP and [s["kind"] for s in steps] == ["final"] and len(router.prompts) == 1


def test_no_retry_once_the_final_reserve_is_spent():
    # The first round ends 75 s into a 90 s turn: 15 s left, under the 20 s reserve.
    answer, steps, router = run([final(GAVE_UP)], clock=Clock([0.0, 0.0, 75.0]))
    assert answer == GAVE_UP and [s["kind"] for s in steps] == ["final"] and len(router.prompts) == 1


def test_the_retry_does_not_let_the_rejected_answers_figures_vouch_for_themselves():
    gave_up_with_figure = "Tôi không có thông tin, nhưng thường là 100.000 đồng."
    _, steps, _ = run([final(gave_up_with_figure), final("Mức 100.000 đồng."), final("Mình chưa tra được.")])
    assert [s["kind"] for s in steps] == [LOOKUP_CHECK_STEP, ANSWER_CHECK_STEP, "final"], "the rejected text was not something the turn saw"


@pytest.mark.parametrize("text", [
    "Tôi không có thông tin về việc này.",
    "Mình chưa có dữ liệu nào về nội dung đó.",
    "Tôi không tìm thấy quy định đó.",
    "Để chắc chắn, tôi cần tra cứu tài liệu.",
    "Mình không biết ai phụ trách.",
    "Xin lỗi, tôi không có thông tin cụ thể về chính sách này.",
])
def test_the_phrases_that_count_as_giving_up(text):
    assert LOOKUP_GAVE_UP.search(text)


@pytest.mark.parametrize("text", [
    "Chỉ quản trị viên được xoá.",
    "Xin chào, mình là Ún.",
    "Hai cộng hai bằng bốn.",
    "Bạn cần kiểm tra lại quy định cụ thể tại quy_che_nghi_phep_2026.pdf.",
    "Giả định bạn đáp ứng vì không có thông tin ngược lại.",
])
def test_the_phrases_that_do_not(text):
    assert not LOOKUP_GAVE_UP.search(text)


def test_the_cap_has_one_more_call_only_with_the_check_on():
    assert [agent_call_cap(steps) for steps in (1, 3)] == [4, 6]
    assert [agent_call_cap(steps, lookup_check=True) for steps in (1, 3)] == [5, 7]
