"""Old tool results step aside when the prompt nears the window (ticket 44).

Each round of the agent loop sends the model the whole conversation again. When the prompt,
by estimate, goes past the ceiling, the OLDEST tool results are replaced by a note, one at a
time, until it fits again: plain code, no model call, no summary (harness survey, section 2:
"clearing tool results is the safest, lightest touch"). Three rules:

- Oldest first, and the newest `keep_recent` results are never cleared: the model is about to
  read them. If the prompt still does not fit after that, it is sent as it is; every result
  is already bounded by tool_result_max_chars / read_result_max_chars.
- A call always travels with its result. Nothing is removed or reordered: the assistant
  message keeps its tool_calls and every tool message stays after it, only its content is
  replaced. Ollama needs the pairing, and AgentService._run keeps message positions
  (checked_out).
- The note can be read back: it names the tool and its arguments, so the model can call it
  again. Re-reading works: what read_document may open is remembered for the turn, not by
  the result that showed it.

The result is a VIEW, built for each model call from the loop's own `working` list, which is
never written to. So the answer check (answer_figures) still counts a figure the model read
in a cleared result as seen, and the trace keeps the whole result. The price is that the
check is lenient about a figure the model could now only recall from before the note.

Off by default: with no ContextBudget, `view` returns `working` itself.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.services.pastes import CHARS_PER_TOKEN, INLINE_FIXED_TOKENS

_LOG = logging.getLogger(__name__)

KEEP_RECENT_RESULTS = 2
NOTE_ARGUMENTS_CHARS = 160
# Measured tokens may only raise the estimate, and by at most this much: Ollama's
# prompt_eval_count can leave out a cached prefix, so a low reading proves nothing.
MAX_SCALE = 2.0


@dataclass(frozen=True)
class ContextBudget:
    """`ceiling_tokens` None = the agent's own inline_max_tokens (general's window less the
    reserve for the answer, one retry and one tool round)."""

    ceiling_tokens: int | None = None
    keep_recent: int = KEEP_RECENT_RESULTS


def context_budget_from_config(section: object, general: dict[str, Any] | None = None) -> ContextBudget | None:
    """`agent.context_budget` of models.yaml -> a budget, or None (off). A section that is
    missing, not enabled, or unreadable leaves the agent exactly as it was: a typo in an
    optional setting must not take the API down at start-up, so it is logged and ignored."""
    if not isinstance(section, dict) or section.get("enabled") is not True:
        if isinstance(section, dict) and section.get("enabled") not in (None, False):
            _LOG.warning("agent.context_budget.enabled must be true or false, got %r: context budget stays off", section.get("enabled"))
        return None
    ceiling, keep = section.get("ceiling_tokens"), section.get("keep_recent", KEEP_RECENT_RESULTS)
    for value in (ceiling, keep):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
            _LOG.warning("agent.context_budget has %r where a whole number of at least 1 belongs: context budget stays off", value)
            return None
    return ContextBudget(ceiling_tokens=ceiling, keep_recent=keep)


def estimate_tokens(messages: list[dict[str, Any]]) -> float:
    """The prompt's tokens by estimate: pastes.prompt_tokens' (the fixed part measured on
    the live prompt, characters over CHARS_PER_TOKEN) plus the calls an assistant message
    carries, which prompt_tokens leaves out."""
    chars = 0
    for message in messages:
        chars += len(str(message.get("content") or ""))
        if message.get("tool_calls"):
            chars += len(json.dumps(message["tool_calls"], ensure_ascii=False, default=str))
    return INLINE_FIXED_TOKENS + chars / CHARS_PER_TOKEN


def _calls_of(message: dict[str, Any]) -> list[tuple[str, object]]:
    """The (name, arguments) of each call an assistant message makes, whichever provider wrote
    it: Ollama's {"function": {"name", "arguments"}}, or the tool_use blocks of Anthropic's
    raw_tool_calls ({"type": "tool_use", "name", "input"}), which come among thinking and text
    blocks that are not calls and wait for no result."""
    found: list[tuple[str, object]] = []
    for call in message.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        function = call.get("function")
        if isinstance(function, dict):
            found.append((str(function.get("name") or ""), function.get("arguments")))
        elif call.get("type") == "tool_use":
            found.append((str(call.get("name") or ""), call.get("input")))
    return found


def _calls_by_result(messages: list[dict[str, Any]]) -> dict[int, tuple[str, object]]:
    """Position of each tool message -> the (name, arguments) of the call it answers: the
    n-th tool message after an assistant message answers its n-th call."""
    found: dict[int, tuple[str, object]] = {}
    pending: list[tuple[str, object]] = []
    answered = 0
    for index, message in enumerate(messages):
        role = message.get("role")
        if role == "assistant":
            pending = _calls_of(message)
            answered = 0
        elif role == "tool":
            if answered < len(pending):
                found[index] = pending[answered]
            answered += 1
    return found


def cleared_note(name: str, arguments: object) -> str:
    shown = ""
    if arguments:
        text = json.dumps(arguments, ensure_ascii=False, default=str)
        shown = "(" + (text if len(text) <= NOTE_ARGUMENTS_CHARS else text[: NOTE_ARGUMENTS_CHARS - 1] + "…") + ")"
    return (
        f"[Kết quả cũ của {name}{shown} đã được bỏ để nhường chỗ trong cuộc trò chuyện. "
        "Cần xem lại thì gọi lại công cụ này với đúng tham số trên.]"
    )


def calls_have_results(messages: list[dict[str, Any]]) -> bool:
    """True when every assistant message's tool_calls is followed by exactly that many tool
    messages (what Ollama expects; the property clearing must keep)."""
    index = 0
    while index < len(messages):
        message = messages[index]
        if message.get("role") == "assistant" and _calls_of(message):
            wanted = len(_calls_of(message))
            following = 0
            while index + 1 + following < len(messages) and messages[index + 1 + following].get("role") == "tool":
                following += 1
            if following != wanted:
                return False
            index += wanted
        elif message.get("role") == "tool":
            return False
        index += 1
    return True


def clear_old_results(messages: list[dict[str, Any]], budget: ContextBudget, ceiling: int, scale: float = 1.0, protected_results: set[int] | None = None) -> tuple[list[dict[str, Any]], int]:
    """`messages` with the oldest tool results replaced by notes until the estimate (times
    `scale`) is at most `ceiling`; returns (messages, how many were replaced). Under the
    ceiling it returns `messages` itself. A result no longer than its note stays: clearing
    it would free nothing."""
    if estimate_tokens(messages) * scale <= ceiling:
        return messages, 0
    results = [index for index, message in enumerate(messages) if message.get("role") == "tool"]
    calls = _calls_by_result(messages)
    view = list(messages)
    cleared = 0
    for index in results[: max(0, len(results) - budget.keep_recent)]:
        if index in (protected_results or set()):
            continue
        name, arguments = calls.get(index, (str(view[index].get("tool_name") or "công cụ"), None))
        note = cleared_note(name, arguments)
        if len(str(view[index].get("content") or "")) <= len(note):
            continue
        view[index] = {**view[index], "content": note}
        cleared += 1
        if estimate_tokens(view) * scale <= ceiling:
            break
    return (view, cleared) if cleared else (messages, 0)


class ContextWindow:
    """One turn's use of a ContextBudget: the view to send for each model call, and the
    correction learned from the tokens the model reported for the last one."""

    def __init__(self, budget: ContextBudget | None, default_ceiling: int, *, protected_results: set[int] | None = None) -> None:
        self.budget = budget
        self.ceiling = (budget.ceiling_tokens or default_ceiling) if budget else 0
        self.cleared = 0
        self._scale = 1.0
        self._estimated: float | None = None
        self._protected_results = protected_results or set()

    def view(self, working: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.budget is None:
            return working
        sent, cleared = clear_old_results(working, self.budget, self.ceiling, self._scale, self._protected_results)
        self.cleared = max(self.cleared, cleared)
        self._estimated = estimate_tokens(sent)
        return sent

    def observe(self, tokens_in: int | None) -> None:
        """What the model said it read for the view just sent. Only a reading above the
        estimate counts (see MAX_SCALE), and the largest correction of the turn is kept: a
        low reading after a high one (a cached prefix) must not show again what was cleared."""
        if self.budget is None or not tokens_in or not self._estimated:
            return
        self._scale = min(MAX_SCALE, max(self._scale, tokens_in / self._estimated))
