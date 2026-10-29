"""An agent answer's figures must come from what the model saw that turn (ticket 20 #2).

The check costs no model call. Every figure in the answer — a run of at least two digits
once thousand separators are dropped ("100.000" = "100000") — must appear in a text the
model was given this turn: the system and user messages, the conversation history, every
tool result. A figure found nowhere is unsupported, and AgentService asks the model once
to look it up, say it was not found, or show its arithmetic (option T1).

Measured on the kept Agent Eval v0.3 runs (baseline, #1, #1-B; 144 answers): it flags 3,
all of them failing answers — doc-10's invented allowance among them — and no passing one.
answer_grounding's word-overlap verdict flags 7 of the 28 passing answers that looked
something up, so it is only recorded (grounding_summary), never acted on.

Blind spots, by construction:
- a figure the model computed (a sum, a converted unit) is in no source and is flagged;
  the retry asks it to show the arithmetic. A one-digit result ("2 giờ") is never checked;
- a figure written in words ("hai trăm nghìn") is not a digit run and is not seen at all;
- a short decimal ("3,5 triệu", "1.5 giờ", "10,5%") splits into one-digit pieces, since a
  separator only joins groups of three digits, and is never checked (fable, 28/10);
- an invented claim that carries no figure is not caught.
Single digits are skipped: in an answer they number a list more often than they claim.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable

from app.services.answer_grounding import grade_answer

MIN_DIGITS = 2
SHOWN_IN_RETRY = 5
_NUMBER = re.compile(r"\d+(?:[.,]\d{3})+|\d+")


def _figures(text: str) -> list[tuple[str, str]]:
    """(normalised, as written) for each figure, in order of first appearance."""
    found: dict[str, str] = {}
    for written in _NUMBER.findall(text or ""):
        number = re.sub(r"[.,]", "", written).lstrip("0") or "0"
        if len(number) >= MIN_DIGITS and number not in found:
            found[number] = written
    return list(found.items())


def turn_texts(messages: list[dict], skip: set[int]) -> tuple[list[str], list[str]]:
    """(everything the model was shown, this turn's tool results) from the loop's messages.
    `skip` holds the positions the check itself added — a rejected answer and the retry
    instruction that quotes its figures — so they can never vouch for those figures."""
    shown = [str(message.get("content") or "") for index, message in enumerate(messages) if index not in skip]
    tools = [str(message.get("content") or "") for message in messages if message.get("role") == "tool"]
    return shown, tools


def unsupported_figures(answer: str, seen_texts: Iterable[str]) -> list[str]:
    """The answer's figures, as written, that appear in none of `seen_texts`."""
    available = {number for text in seen_texts for number, _ in _figures(text)}
    return [written for number, written in _figures(answer) if number not in available]


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
