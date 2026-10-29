"""The answer check: figures must come from what the turn saw, one retry if not (ticket 20 #2).

doc-10 of Agent Eval v0.3 is the case: asked for an allowance, the agent searched nothing and
wrote "100.000 - 200.000 VNĐ/ngày" from nowhere. Every figure in an answer must appear in the
question, the conversation or the turn's tool results; when one does not, the model gets one
retry, with tools, in a round of its own, while the final reserve is still free. No stack:
the backends are fakes and the model is scripted.
"""
from __future__ import annotations

import json

import pytest

import app.services.agent_service as agent_module
from app.services.agent_service import ANSWER_CHECK_STEP, STOP_MAX_STEPS, UNSUPPORTED_FIGURES, AgentService
from app.services.answer_figures import retry_instruction, turn_texts, unsupported_figures

INVENTED = "Phụ cấp lưu trú là 100.000 - 200.000 VNĐ/ngày, theo quy định hiện hành."
HONEST = "Mình chưa tra được tài liệu nào nói về phụ cấp lưu trú."


def final(text: str) -> dict:
    return {"content": text, "tool_calls": [], "raw_tool_calls": []}


def call(name: str, arguments: dict) -> dict:
    return {"content": "", "tool_calls": [{"name": name, "arguments": arguments}], "raw_tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


class Router:
    def __init__(self, rounds, forced: str = "hết lượt"):
        self.rounds, self.forced = list(rounds), forced
        self.prompts: list[list[dict]] = []

    def chat_tools(self, role, messages, tools):
        self.prompts.append([dict(message) for message in messages])
        return self.rounds.pop(0), "fake"

    def chat(self, role, messages):
        self.prompts.append([dict(message) for message in messages])
        return self.forced, "fake"


class Retrieval:
    def retrieve(self, query, top_k, document_id=None):
        return [{"filename": "quy_dinh_cong_tac_phi_2026.pdf", "page": 2, "content": "Phụ cấp lưu trú: 300.000 đồng/người/ngày.", "score": 0.9}]


class Clock:
    def __init__(self, ticks):
        self.ticks = list(ticks)

    def __call__(self):
        return self.ticks.pop(0) if len(self.ticks) > 1 else self.ticks[0]


def run(rounds, user="Phụ cấp lưu trú khi đi công tác là bao nhiêu?", history=(), **kwargs):
    router = Router(rounds, kwargs.pop("forced", "hết lượt"))
    agent = AgentService(router, Retrieval(), None, **kwargs)
    messages = [{"role": "system", "content": "Bạn là Ún."}, *history, {"role": "user", "content": user}]
    answer, _, steps = agent.run(messages)
    return answer, steps, router


def test_figures_compare_as_numbers_and_single_digits_are_not_claims():
    assert unsupported_figures("Mức 300.000 đồng", ["300000 đồng/ngày"]) == []
    assert unsupported_figures("Mức 300,000 đồng", ["300.000 đồng/ngày"]) == []
    assert unsupported_figures("1. Bước một 2. Bước hai, mất 3 ngày", []) == [], "list numbering is not a claim"
    assert unsupported_figures("Từ 100.000 tới 200.000, cũ là 100.000", ["không có số"]) == ["100.000", "200.000"], "as written, once each"
    assert unsupported_figures("Hạn 31/03/2026", ["hạn cuối 31/3 năm 2026"]) == [], "a leading zero is the same figure"


def test_a_number_before_a_scale_word_is_its_full_value_both_ways():
    # Ticket 28 #3: "54 triệu" was 54 to the check, which 54.000.000 never matched.
    assert unsupported_figures("Lương là 54 triệu đồng", ["Mức lương 54.000.000 đồng"]) == []
    assert unsupported_figures("Lương là 54.000.000 đồng", ["Mức lương 54 triệu đồng"]) == []
    assert unsupported_figures("Vốn 1.500.000.000 đồng", ["vốn điều lệ 1,5 tỷ"]) == [], "a decimal comma before a scale word"
    # "1,5 tỷ" in an answer is not checked at all (its digits are single, see the blind spots).
    assert unsupported_figures("Vốn 12,5 tỷ đồng", ["vốn điều lệ 12.500.000.000"]) == []
    assert unsupported_figures("Vốn 2.000.000.000 đồng", ["vốn 2 tỉ"]) == [] and unsupported_figures("Hỗ trợ 12.000 đồng", ["hỗ trợ 12 ngàn"]) == []
    assert unsupported_figures("Dự toán 2.500.000.000.000 đồng", ["dự toán 2.500 tỷ"]) == [], "three digits after a separator are thousands still"
    assert unsupported_figures("Mức 300.000 đồng", ["mức 3 trăm nghìn"]) == [], "a run of scale words multiplies"
    _, steps, _ = run([final("Đúng, lương của bạn là 54 triệu đồng.")], user="Lương tháng của mình là 54.000.000 đồng phải không?")
    assert [s["kind"] for s in steps] == ["final"], "no retry"


def test_the_digits_as_written_still_count_so_nothing_found_before_is_flagged_now():
    assert unsupported_figures("Lương 54 triệu đồng", ["Đơn vị: triệu đồng | Lương | 54"]) == [], "a table states its unit once"
    assert unsupported_figures("Lương 54 đồng", ["lương 54 triệu"]) == []
    assert unsupported_figures("Lương 54 triệu", ["Lương 45.000.000"]) == ["54 triệu"], "flagged as written, scale word and all"
    assert unsupported_figures("Lãi suất 10,5%", []) == ["10"], "with no scale word a decimal splits as before"


def test_the_checks_own_messages_never_vouch_for_a_figure():
    messages = [{"role": "user", "content": "phụ cấp?"}, {"role": "assistant", "content": INVENTED}, {"role": "system", "content": retry_instruction(["100.000"])}]
    shown, tools = turn_texts(messages, skip={1, 2})
    assert unsupported_figures(INVENTED, shown) == ["100.000", "200.000"] and tools == []


def test_an_invented_figure_gets_one_retry_and_the_rejected_text_is_kept_nowhere():
    answer, steps, router = run([final(INVENTED), final(HONEST)])

    assert answer == HONEST
    assert [s["kind"] for s in steps] == [ANSWER_CHECK_STEP, "final"]
    rejected = steps[0]
    assert rejected["content"] is None and rejected["error_code"] == UNSUPPORTED_FIGURES
    assert rejected["arguments_shape"] == {"unsupported_figures": 2}
    assert INVENTED not in json.dumps(steps, ensure_ascii=False), "the trace keeps figures, not the invented text"
    retry_prompt = router.prompts[1]
    assert retry_prompt[-2] == {"role": "assistant", "content": INVENTED}
    assert "100.000, 200.000" in retry_prompt[-1]["content"] and "gọi công cụ" in retry_prompt[-1]["content"]
    assert steps[1]["arguments_shape"] == {"unsupported_figures": 0} and "error_code" not in steps[1]


def test_the_rejected_step_names_its_figures_where_content_lives_and_the_summary_keeps_the_count():
    # Ticket 28 #1: `arguments` goes to agent_traces, deleted with the conversation;
    # arguments_shape is all the content-free summary reads, so it stays a count.
    invented = "Mức 100.000, 120.000, 140.000, 160.000, 180.000 hay 200.000 đồng/ngày."
    _, steps, router = run([final(invented), final(HONEST)])

    rejected = steps[0]
    figures = ["100.000", "120.000", "140.000", "160.000", "180.000", "200.000"]
    assert rejected["arguments"] == {"unsupported_figures": figures}, "every figure, past the five the retry names"
    assert rejected["arguments_shape"] == {"unsupported_figures": 6} and rejected["content"] is None
    assert "200.000" not in router.prompts[1][-1]["content"], "the retry still names five"


def test_the_retry_asks_for_a_first_answer_with_no_apology_and_no_word_of_the_check():
    # Ticket 28 #2: the user never saw the rejected answer, but read the retry's "Xin lỗi, tôi đã nhầm lẫn…".
    _, _, router = run([final(INVENTED), final(HONEST)])
    instruction = router.prompts[1][-1]["content"]
    assert instruction == retry_instruction(["100.000", "200.000"])
    assert instruction.endswith("Rồi viết lại câu trả lời như khi trả lời lần đầu: không xin lỗi, không nhắc tới việc kiểm tra này.")


def test_figures_from_the_question_the_history_or_a_tool_need_no_retry():
    answer, steps, _ = run([final("Bạn vừa nói 450.000 đồng, mình ghi nhận.")], user="Mình được 450.000 đồng mỗi ngày")
    assert [s["kind"] for s in steps] == ["final"]

    earlier = [{"role": "assistant", "content": "Phần phép chuyển sang hết hạn ngày 31/3."}]
    _, steps, _ = run([final("Hạn cuối là ngày 31/3.")], history=earlier, user="Vậy hạn cuối là ngày nào?")
    assert [s["kind"] for s in steps] == ["final"], "a follow-up repeats a figure the conversation already gave"

    answer, steps, _ = run([call("search_documents", {"query": "phụ cấp lưu trú"}), final("Phụ cấp lưu trú là 300.000 đồng/người/ngày (quy_dinh_cong_tac_phi_2026.pdf, trang 2).")])
    assert [s["kind"] for s in steps] == ["tool_call", "tool_result", "final"]
    shape = steps[-1]["arguments_shape"]
    assert shape["unsupported_figures"] == 0 and shape["grounding"] in {"grounded", "weak", "ungrounded"}, "K1 recorded when the turn looked something up"


def test_a_retry_that_repeats_the_invention_is_marked_not_retried_again():
    answer, steps, router = run([final(INVENTED), final(INVENTED)])

    assert answer == INVENTED and len(router.prompts) == 2, "one retry, never two"
    assert [s["kind"] for s in steps] == [ANSWER_CHECK_STEP, "final"]
    assert steps[1]["error_code"] == UNSUPPORTED_FIGURES and steps[1]["arguments_shape"]["unsupported_figures"] == 2


def test_no_retry_once_the_final_reserve_is_spent():
    # The first round ends 75 s into a 90 s turn: 15 s left, under the 20 s reserve.
    answer, steps, router = run([final(INVENTED)], clock=Clock([0.0, 0.0, 75.0]))

    assert answer == INVENTED and len(router.prompts) == 1
    assert [s["kind"] for s in steps] == ["final"] and steps[0]["error_code"] == UNSUPPORTED_FIGURES


def test_the_retry_gets_a_round_of_its_own_with_tools():
    # max_steps 1: the invented answer used the only round; the retry may still search,
    # and the forced final then answers from what it found.
    answer, steps, router = run(
        [final(INVENTED), call("search_documents", {"query": "phụ cấp lưu trú"})],
        max_steps=1, forced="Theo quy_dinh_cong_tac_phi_2026.pdf trang 2, phụ cấp lưu trú là 300.000 đồng/người/ngày.",
    )
    assert [s["kind"] for s in steps] == [ANSWER_CHECK_STEP, "tool_call", "tool_result", "final"]
    assert steps[-1]["stop_reason"] == STOP_MAX_STEPS and "error_code" not in steps[-1]
    assert "300.000" in answer


def test_the_fixed_out_of_time_reply_is_not_checked():
    # The forced final finds no time left: the reply is ours ("... 90 giây"), not the model's.
    _, steps, _ = run([], clock=Clock([0.0, 89.5, 91.0]))
    assert steps[-1]["stop_reason"] == "turn_budget_exhausted" and "arguments_shape" not in steps[-1]


def test_the_check_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(agent_module, "ANSWER_CHECK", False)
    answer, steps, _ = run([final(INVENTED)])
    assert answer == INVENTED and [s["kind"] for s in steps] == ["final"] and "arguments_shape" not in steps[0]


@pytest.mark.parametrize("text", ["2 giờ", "hai trăm nghìn đồng", "khoảng 3,5 triệu đồng", "Ông Khoa phụ trách hệ thống"])
def test_the_stated_blind_spots_pass_unflagged(text):
    # A one-digit result, a figure in words, a short decimal (one before a scale word only
    # vouches, ticket 28 #3), a claim with no figure: not seen, as documented.
    assert unsupported_figures(text, []) == []
