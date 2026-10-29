"""Erase one Discord member's words from the places the bot copied them to (ticket 17).

forget_member deletes what is filed under a member's id: channel messages, turns,
memories. The bot also COPIES their words to places filed under nobody — the backend
conversation's history (`messages`) and the agent's traces, where a search_history
result quotes them verbatim, by author. These helpers rewrite such a copy in place
(the owner's option C, 27/10):

  - a search_history result loses the member's items, which become PLACEHOLDER, and
    keeps everyone else's — including another member quoting them, as forget_member
    already leaves that member's own messages alone;
  - text the bot wrote (an answer, a tool argument) loses every verbatim run of at
    least MIN_QUOTE_CHARS characters taken from the member's own messages;
  - a result that cannot be parsed but still carries the member's trace is replaced
    whole.

What this cannot do: find a PARAPHRASE. Only verbatim copies are detectable, so a bot
answer that retold the member's words in its own is left as it is.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

PLACEHOLDER = "[đã xoá theo yêu cầu]"
# Shorter runs match too much that nobody owns ("cảm ơn mọi người"); 20 characters is
# about four Vietnamese words.
MIN_QUOTE_CHARS = 20
LIMITS_NOTE = (
    f"Chỉ xoá được bản chép NGUYÊN VĂN (từ {MIN_QUOTE_CHARS} ký tự) lời của thành viên; "
    "lời diễn giải lại thì không phát hiện được."
)


class QuoteIndex:
    """Every MIN_QUOTE_CHARS-long window of the member's own texts."""

    def __init__(self, texts: Iterable[str | None]) -> None:
        self.windows: set[str] = set()
        for text in texts:
            text = text or ""
            for start in range(len(text) - MIN_QUOTE_CHARS + 1):
                self.windows.add(text[start:start + MIN_QUOTE_CHARS])

    def __bool__(self) -> bool:
        return bool(self.windows)


def redact_quotes(text: str | None, index: QuoteIndex) -> tuple[str | None, bool]:
    """Replace every maximal run built of the member's verbatim windows with PLACEHOLDER."""
    if not text or not index:
        return text, False
    covered_until = -1
    spans: list[list[int]] = []
    for start in range(len(text) - MIN_QUOTE_CHARS + 1):
        if text[start:start + MIN_QUOTE_CHARS] in index.windows:
            end = start + MIN_QUOTE_CHARS
            if spans and start <= covered_until:
                spans[-1][1] = end
            else:
                spans.append([start, end])
            covered_until = end
    if not spans:
        return text, False
    pieces, cursor = [], 0
    for start, end in spans:
        pieces.append(text[cursor:start])
        pieces.append(PLACEHOLDER)
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces), True


def _unwrap(content: str) -> tuple[str, str, str]:
    """(open marker line, body, close marker line) of an injection-defense wrapped
    result — recognised by shape (<<<...>>> lines), so this layer imports no service."""
    lines = content.split("\n")
    if len(lines) >= 3 and lines[0].startswith("<<<") and lines[-1].startswith("<<<"):
        return lines[0] + "\n", "\n".join(lines[1:-1]), "\n" + lines[-1]
    return "", content, ""


def _carries(body: str, author_id: str) -> bool:
    return re.search(r'"author_id"\s*:\s*"' + re.escape(author_id) + '"', body) is not None


def _drop_member_items(payload: Any, author_id: str) -> tuple[Any, bool]:
    """A history result is a list of items, or {"omitted", "note", "items"} when it overflowed."""
    if isinstance(payload, list):
        changed = False
        kept: list[Any] = []
        for item in payload:
            if isinstance(item, dict) and str(item.get("author_id")) == author_id:
                kept.append(PLACEHOLDER)
                changed = True
            else:
                kept.append(item)
        return kept, changed
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        items, changed = _drop_member_items(payload["items"], author_id)
        return ({**payload, "items": items} if changed else payload), changed
    return payload, False


def redact_history_result(content: str | None, author_id: str, index: QuoteIndex) -> tuple[str | None, bool]:
    """One search_history tool result with the member's items replaced."""
    if not content:
        return content, False
    opening, body, closing = _unwrap(content)
    try:
        payload = json.loads(body)
    except ValueError:
        # Cut by characters (the _dump fallback): no items to drop one by one, so a
        # result that still shows the member's id or words goes whole.
        if _carries(body, author_id) or redact_quotes(body, index)[1]:
            return opening + PLACEHOLDER + closing, True
        return content, False
    payload, changed = _drop_member_items(payload, author_id)
    if not changed:
        return content, False
    return opening + json.dumps(payload, ensure_ascii=False) + closing, True


def redact_arguments(arguments: Any, author_id: str, index: QuoteIndex) -> tuple[Any, bool]:
    """A tool call's arguments with the member's id and verbatim words replaced; also an
    answer_check step's, whose value is a list of the figures it flagged (ticket 28 #1)."""
    if not isinstance(arguments, dict):
        return arguments, False
    redacted: dict[str, Any] = {}
    changed = False
    for key, value in arguments.items():
        if isinstance(value, str) and key == "author_id" and value.strip() == author_id:
            redacted[key], changed = PLACEHOLDER, True
        elif isinstance(value, str):
            redacted[key], quoted = redact_quotes(value, index)
            changed = changed or quoted
        elif isinstance(value, list):
            items = [redact_quotes(item, index) if isinstance(item, str) else (item, False) for item in value]
            redacted[key] = [item for item, _ in items]
            changed = changed or any(quoted for _, quoted in items)
        else:
            redacted[key] = value
    return redacted, changed
