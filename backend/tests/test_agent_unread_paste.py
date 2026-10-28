"""An answer that asks for the paste the turn holds, or says it read all of one, while a chunk
is unread goes back once to read on (ticket 20 #3-D, step 1).

On #3-C's slip doc-40 and doc-44 asked the user for "phần giữa của văn bản" without opening
the paste, and doc-47 said "đã đọc được văn bản hợp đồng đầy đủ" after one read
(kept/agent-eval-v0.6-paste-slip-c/). The step needs both the words and a chunk no
read_document result of the turn carried; it has a retry of its own, apart from #2's, and
never touches the forced answer. No database, no model: the backends are fakes and the
model is scripted.
"""
from __future__ import annotations

import json
import re

import pytest

from app.services.agent_service import (
    ANSWER_CHECK_STEP,
    READ_MAX_CHUNKS,
    STOP_MAX_STEPS,
    UNREAD_PASTE,
    UNREAD_PASTE_LABEL,
    UNREAD_PASTE_STEP,
    AgentService,
)
from app.services.pastes import _chunks, paste_id
from app.services.unread_paste import ASKS_FOR_PASTE, CLAIMS_READ_ALL, claim, read_on_instruction

QUESTION = "Theo biên bản trên, hạn nộp hồ sơ là ngày nào?"
SECRET = "Hạn nộp hồ sơ dự thầu là ngày 14/11, chị Thu Hà phụ trách."
ASKS = "Phần giữa chưa hiện ra. Bạn vui lòng dán lại toàn bộ văn bản để mình trả lời chính xác."
READ_ALL = "Tôi đã đọc toàn bộ văn bản nhưng không thấy hạn nộp hồ sơ."
PLAIN = "Biên bản không nêu hạn nộp hồ sơ."


def paste(length: int = 12_000) -> str:
    filler = "Mục họp thường lệ, không có gì đáng chú ý trong đoạn này. " * (length // 60)
    half = len(filler) // 2
    return "Mình dán biên bản dưới đây.\n\n" + filler[:half] + "\n\n" + SECRET + "\n\n" + filler[half:] + "\n\n" + QUESTION


PASTED = paste()
PID = paste_id(PASTED)
TOTAL = len(_chunks(PASTED))


def final(text: str) -> dict:
    return {"content": text, "tool_calls": [], "raw_tool_calls": []}


def calls(*arguments: dict) -> dict:
    """One model round asking read_document once per argument set."""
    return {
        "content": "",
        "tool_calls": [{"name": "read_document", "arguments": a} for a in arguments],
        "raw_tool_calls": [{"function": {"name": "read_document", "arguments": a}} for a in arguments],
    }


class Router:
    def __init__(self, rounds, forced: str = "hết lượt"):
        self.rounds, self.forced = list(rounds), forced
        self.prompts: list[list[dict]] = []

    def chat_tools(self, role, messages, tools):
        self.prompts.append([dict(m) for m in messages])
        return self.rounds.pop(0), "fake"

    def chat(self, role, messages):
        self.prompts.append([dict(m) for m in messages])
        return self.forced, "fake"


class Clock:
    def __init__(self, ticks):
        self.ticks = list(ticks)

    def __call__(self):
        return self.ticks.pop(0) if len(self.ticks) > 1 else self.ticks[0]


def run(rounds, user=PASTED, **kwargs):
    router = Router(rounds, kwargs.pop("forced", "hết lượt"))
    events: list[dict] = []
    answer, _, steps = AgentService(router, None, None, **kwargs).run([{"role": "user", "content": user}], on_step=events.append)
    return answer, steps, router, events


def kinds(steps) -> list[str]:
    return [s["kind"] for s in steps]


def returned(steps) -> set[int]:
    """The paste chunks the turn's read_document results actually carried."""
    return {c["chunk_index"] for s in steps if s["kind"] == "tool_result" for c in json.loads(s["content"]).get("chunks", [])}


@pytest.mark.parametrize(("answer", "pattern"), [
    # The kept answers, word for word where the pattern looks.
    ("Vì văn bản bị cắt ở giữa, **Tôi cần bạn cung cấp phần giữa của văn bản**, hoặc lưu thành tệp.", ASKS_FOR_PASTE),
    ("Để tôi trả lời chính xác hơn, bạn vui lòng:\n1. Cung cấp phần giữa của văn bản lịch trình tour, hoặc\n2. Dán lại toàn bộ văn bản đầy đủ", ASKS_FOR_PASTE),
    ("Tôi đã đọc được văn bản hợp đồng đầy đủ. Dựa trên Điều 2 khoản 2 của hợp đồng:", CLAIMS_READ_ALL),
    ("Bạn gửi lại cho mình văn bản đầy đủ nhé.", ASKS_FOR_PASTE),
    ("Sau khi đọc hết văn bản, mình thấy hạn là 14/11.", CLAIMS_READ_ALL),
    # References and partial reads are not requests or claims.
    ("Dựa trên nội dung văn bản bạn cung cấp (Quy chế học bổng), bạn thuộc hạng Sóng Biếc.", None),
    ("Theo phần đầu và cuối của văn bản bạn cung cấp: người dẫn là chị Diệp.", None),
    ("Dựa trên nội dung văn bản đã đọc, tôi có thể trả lời câu hỏi của bạn.", None),
    ("Bạn đã dán lại toàn bộ văn bản, cảm ơn bạn.", None),
    ("Bạn không cần dán lại toàn bộ văn bản, mình đọc được.", None),
    ("Mình đã đọc phần đầu nhưng chưa đầy đủ.", None),
    ("Mình đã đọc hết phần đầu và phần cuối bạn dán.", None),
    ("Bạn có muốn tôi đọc toàn bộ văn bản không?", None),
])
def test_the_words_the_step_looks_for(answer, pattern):
    assert claim(answer) == pattern


def test_asking_for_the_paste_gets_one_round_with_the_exact_call_and_keeps_no_text():
    answer, steps, router, events = run([final(ASKS), calls({"document_id": PID, "from_chunk": 0, "n": 3}), final(PLAIN)])

    assert answer == PLAIN
    assert kinds(steps) == [UNREAD_PASTE_STEP, "tool_call", "tool_result", "final"]
    sent_back = steps[0]
    assert sent_back["content"] is None and sent_back["error_code"] == UNREAD_PASTE
    assert sent_back["arguments_shape"] == {"pattern": ASKS_FOR_PASTE, "read_chunks": 0}
    assert ASKS not in json.dumps(steps, ensure_ascii=False) + json.dumps(events, ensure_ascii=False), "the trace keeps counts, not the text"
    retry_prompt = router.prompts[1]
    assert retry_prompt[-2] == {"role": "assistant", "content": ASKS}
    instruction = retry_prompt[-1]
    assert instruction["role"] == "system" and f'read_document(document_id="{PID}", from_chunk=0, n={READ_MAX_CHUNKS})' in instruction["content"]
    assert "đừng nhờ dán" in instruction["content"]
    assert ("unread_paste", UNREAD_PASTE_LABEL) in [(e["kind"], e.get("label")) for e in events]


def test_saying_it_read_all_after_one_read_points_at_the_first_chunk_not_returned():
    answer, steps, router, _ = run([calls({"document_id": PID, "from_chunk": 0, "n": 3}), final(READ_ALL), final(PLAIN)])

    read = returned(steps)
    assert read and len(read) < TOTAL
    first = min(set(range(TOTAL)) - read)
    assert kinds(steps) == ["tool_call", "tool_result", UNREAD_PASTE_STEP, "final"]
    assert steps[2]["arguments_shape"] == {"pattern": CLAIMS_READ_ALL, "read_chunks": len(read)}
    assert f"from_chunk={first}, n={READ_MAX_CHUNKS})" in router.prompts[2][-1]["content"]


def test_saying_it_read_all_when_every_chunk_came_back_does_not_fire():
    # One round, one call per chunk: every chunk is returned without running out of rounds.
    answer, steps, router, _ = run([calls(*({"document_id": PID, "from_chunk": i, "n": 1} for i in range(TOTAL))), final(READ_ALL)])

    assert returned(steps) == set(range(TOTAL))
    assert answer == READ_ALL and kinds(steps)[-1] == "final" and UNREAD_PASTE_STEP not in kinds(steps)
    assert len(router.prompts) == 2


def test_the_figure_check_and_this_step_each_retry_once_in_one_turn():
    # doc-47 on #3-C's slip: #2 spent its retry in round 1, and round 3 said it had read it all.
    invented = "Mức phạt là 987.654 đồng."
    answer, steps, router, _ = run([final(invented), final(ASKS), final(PLAIN)])
    assert answer == PLAIN and kinds(steps) == [ANSWER_CHECK_STEP, UNREAD_PASTE_STEP, "final"]

    answer, steps, router, _ = run([final(ASKS), final(invented), final(PLAIN)])
    assert answer == PLAIN and kinds(steps) == [UNREAD_PASTE_STEP, ANSWER_CHECK_STEP, "final"]

    answer, steps, router, _ = run([final(ASKS), final(ASKS)])
    assert answer == ASKS and kinds(steps) == [UNREAD_PASTE_STEP, "final"] and len(router.prompts) == 2, "one retry, never two"


def test_the_answer_sent_back_never_vouches_for_its_own_figures():
    # #2 has spent its retry, so the guess goes back for the paste alone; repeated after, it
    # must still count as a figure from nowhere.
    guess = "Bạn vui lòng dán lại toàn bộ văn bản; mình đoán mức phạt là 999.999 đồng."
    _, steps, _, _ = run([final("Mức phạt là 987.654 đồng."), final(guess), final("Mức phạt là 999.999 đồng.")])
    assert kinds(steps) == [ANSWER_CHECK_STEP, UNREAD_PASTE_STEP, "final"]
    assert steps[-1]["error_code"] == "UNSUPPORTED_FIGURES" and steps[-1]["arguments_shape"]["unsupported_figures"] == 1


def test_without_a_paste_the_steps_are_as_before():
    answer, steps, router, _ = run([final(ASKS)], user="Bạn đọc giúp mình biên bản họp hôm qua nhé.")
    assert answer == ASKS and kinds(steps) == ["final"] and len(router.prompts) == 1
    assert steps[0]["stop_reason"] == "final" and "error_code" not in steps[0]


def test_the_forced_answer_is_never_sent_back():
    answer, steps, router, _ = run([calls({"document_id": PID, "from_chunk": 0, "n": 1})], max_steps=1, forced=ASKS)
    assert answer == ASKS and kinds(steps) == ["tool_call", "tool_result", "final"]
    assert steps[-1]["stop_reason"] == STOP_MAX_STEPS and len(router.prompts) == 2


def test_no_retry_once_the_final_reserve_is_spent():
    # The first round ends 75 s into a 90 s turn: 15 s left, under the 20 s reserve.
    answer, steps, router, _ = run([final(ASKS)], clock=Clock([0.0, 0.0, 75.0]))
    assert answer == ASKS and kinds(steps) == ["final"] and len(router.prompts) == 1


def test_the_instruction_gives_one_call_and_no_chunk_count():
    for pattern in (ASKS_FOR_PASTE, CLAIMS_READ_ALL):
        text = read_on_instruction({"pattern": pattern, "document_id": PID, "from_chunk": 4, "read": 3}, READ_MAX_CHUNKS)
        assert text.count("read_document(") == 1
        assert f"{TOTAL} đoạn" not in text and "từ 0 đến" not in text and "còn lại" not in text
        assert re.findall(r"\d+", text.replace(PID, "")) == ["4", str(READ_MAX_CHUNKS)], "only the call's own numbers"
        assert "search_documents" not in text and "tài liệu" not in text
