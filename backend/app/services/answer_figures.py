"""An agent answer's figures must come from what the model saw that turn (ticket 20 #2).

The check costs no model call. Every figure in the answer — a run of at least two digits
once thousand separators are dropped ("100.000" = "100000") — must appear in a text the
model was given this turn: the system and user messages, the conversation history, every
tool result. A figure found nowhere is unsupported, and AgentService asks the model once
to look it up, say it was not found, or show its arithmetic (option T1).

A number before a scale word (SCALES) also stands for its full value (ticket 28 #3): "54
triệu" is 54000000 and "1,5 tỷ" 1500000000, a run of them multiplying ("3 trăm nghìn" =
300000). So "54 triệu" in the answer is found by a source's "54.000.000", and the other way
round. The digits as written still count as well ("54"), so whatever was found before is
found now — "54 triệu" by a table's "54" under "Đơn vị: triệu đồng" — and the check flags
no figure it did not flag before.

Measured on the kept Agent Eval v0.3 runs (baseline, #1, #1-B; 144 answers): it flags 3,
all of them failing answers — doc-10's invented allowance among them — and no passing one.
answer_grounding's word-overlap verdict flags 7 of the 28 passing answers that looked
something up, so it is only recorded (grounding_summary), never acted on.

Blind spots, by construction:
- a figure the model computed (a sum, a converted unit) is in no source and is flagged;
  the retry asks it to show the arithmetic. A one-digit result ("2 giờ") is never checked;
- a figure written in words ("hai trăm nghìn") is not a digit run and is not seen at all;
- a short decimal ("3,5 triệu", "1.5 giờ", "10,5%") splits into one-digit pieces, since a
  separator only joins groups of three digits, and is never checked (fable, 28/10). A
  decimal is read only before a scale word: a source's "3,5 triệu" now vouches for
  3.500.000, but in the answer it is still not checked, as its digits are single;
- a scale word is read after any number: "năm 2025 tỷ lệ…" also stands for 2025 tỷ,
  which costs nothing while the digits as written count too;
- an invented claim that carries no figure is not caught.
Single digits are skipped: in an answer they number a list more often than they claim.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from decimal import Decimal

from app.services.answer_grounding import grade_answer

MIN_DIGITS = 2
SHOWN_IN_RETRY = 5
# A Vietnamese scale word and its power of ten.
SCALES = {"trăm": 2, "nghìn": 3, "ngàn": 3, "triệu": 6, "tỷ": 9, "tỉ": 9}
_DIGITS = re.compile(r"\d+(?:[.,]\d{3})+|\d+")
_SCALE = "|".join(SCALES)
# A run of digits, or one followed by scale words, with a decimal part before them only
# ("1,5 tỷ"), so "10,5%" still splits as it always has.
_NUMBER = re.compile(rf"(\d+(?:[.,]\d{{3}})*)(?:[.,](\d+))?\s*((?:{_SCALE})(?:\s+(?:{_SCALE}))*)\b|{_DIGITS.pattern}", re.IGNORECASE)


def _digits(written: str) -> str:
    return re.sub(r"[.,]", "", written).lstrip("0") or "0"


def _figures(text: str) -> list[tuple[set[str], set[str], str]]:
    """(digits, numbers, as written) for each figure, in order of first appearance: `digits`
    are its runs of at least MIN_DIGITS digits, normalised; `numbers` are those and, for a
    scaled figure, its full value. A figure written twice ("54 triệu", "54.000.000") is one."""
    found: dict[str, tuple[set[str], set[str], str]] = {}
    for match in _NUMBER.finditer(text or ""):
        written, whole, fraction, words = match.group(0), *match.groups()
        digits = {number for piece in _DIGITS.findall(written) if len(number := _digits(piece)) >= MIN_DIGITS}
        numbers = set(digits)
        key = next(iter(digits), "")
        if words:
            value = Decimal(f"{_digits(whole)}.{fraction or 0}").scaleb(sum(SCALES[word.lower()] for word in words.split()))
            key = str(int(value)) if value == value.to_integral_value() else format(value.normalize(), "f")
            if len(key) >= MIN_DIGITS:
                numbers.add(key)
        if numbers:
            seen_digits, seen_numbers, _ = found.setdefault(key, (set(), set(), written))
            seen_digits.update(digits)
            seen_numbers.update(numbers)
    return list(found.values())


def turn_texts(messages: list[dict], skip: set[int]) -> tuple[list[str], list[str]]:
    """(everything the model was shown, this turn's tool results) from the loop's messages.
    `skip` holds the positions the check itself added — a rejected answer and the retry
    instruction that quotes its figures — so they can never vouch for those figures."""
    shown = [str(message.get("content") or "") for index, message in enumerate(messages) if index not in skip]
    tools = [str(message.get("content") or "") for message in messages if message.get("role") == "tool"]
    return shown, tools


def unsupported_figures(answer: str, seen_texts: Iterable[str]) -> list[str]:
    """The answer's figures, as written, that appear in none of `seen_texts`: any number a
    figure stands for will do. A figure without digits to check ("1,5 tỷ") only vouches."""
    available = {number for text in seen_texts for _, numbers, _ in _figures(text) for number in numbers}
    return [written for digits, numbers, written in _figures(answer) if digits and not numbers & available]


def retry_instruction(unsupported: list[str]) -> str:
    """The system message for the one retry: which figures, and the three ways out.

    The user never saw the rejected answer, yet a retried answer opened with "Xin lỗi, tôi
    đã nhầm lẫn…" (doc-22 in v0.3, doc-47 in v0.8-n1-gate) and the user read that. So the
    answer is to be written as a first one: no apology, no word of the check (ticket 28 #2).
    """
    shown = ", ".join(unsupported[:SHOWN_IN_RETRY]) + (" …" if len(unsupported) > SHOWN_IN_RETRY else "")
    return (
        f"Kiểm tra câu trả lời vừa viết: các con số {shown} không có trong câu hỏi, cuộc trò chuyện "
        "hay kết quả công cụ của lượt này. Nếu câu hỏi cần dữ liệu nội bộ (tài liệu, tin nhắn, trạng "
        "thái hệ thống) thì gọi công cụ để tra; không tìm thấy thì nói rõ là không tìm thấy, đừng đưa "
        "con số. Nếu đó là số bạn tự tính từ dữ liệu đã có thì ghi rõ phép tính. Rồi viết lại câu trả "
        "lời như khi trả lời lần đầu: không xin lỗi, không nhắc tới việc kiểm tra này."
    )


def _text_values(content: str) -> str:
    """The words of a tool result, not its JSON keys: the string values inside the
    injection-defense wrapper (recognised by its <<<…>>> lines), or the text as it is."""
    lines = (content or "").split("\n")
    body = "\n".join(lines[1:-1]) if len(lines) >= 3 and lines[0].startswith("<<<") and lines[-1].startswith("<<<") else content
    try:
        payload = json.loads(body)
    except ValueError:
        return body or ""
    values: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif value is not None:
            values.append(str(value))

    walk(payload)
    return " ".join(values)


def grounding_summary(answer: str, tool_results: list[str]) -> dict[str, object] | None:
    """answer_grounding's verdict on the turn's tool results, as labels and counts only
    (it goes to the content-free trace). None when the turn looked nothing up."""
    if not tool_results:
        return None
    report = grade_answer(answer, [_text_values(text) for text in tool_results])
    return {
        "grounding": report.label,
        "judged": report.judged,
        "grounded": report.grounded,
        "weak": report.weak,
        "ungrounded": report.ungrounded,
    }
