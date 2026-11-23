"""The search excerpt that shows the part of a chunk the query is about (agent.focused_excerpts).

search_documents shows SEARCH_EXCERPT_CHARS of each chunk. The first characters are the right ones only
when the answer sits there: on Agent Eval v0 the required answer lay past character 400 of every chunk
the replayed search returned on 5 of 20 document tasks with must_mention patterns (doc-33..37, positions
528-1061, counted 23/11/2026). qwen3.5:2b spent a read_document round on 4 of them and still failed one.
A search engine shows the words around the match instead (keyword in context); grep-style tools in
coding harnesses show the matching line with a few lines around it. This does the same, in code, with no
model call: it scores every window of the excerpt's size by the query's words it holds, and moves away
from the head only when some window holds strictly more.

Words are compared syllable by syllable, case and Unicode form aside, since Vietnamese writes one
syllable per space; a pair of query syllables found side by side counts extra, so "phụ cấp" beats a
window with "phụ" in one place and "cấp" in another. Function words are not counted.
"""
from __future__ import annotations

import re
import unicodedata

WORD = re.compile(r"\w+", re.UNICODE)
ELLIPSIS = "…"
# Syllables too common to say where a chunk is about the question: grammar words and question words.
# Kept short on purpose: a content syllable wrongly listed here only costs focus, never correctness.
STOP_SYLLABLES = frozenset(
    {
        "và", "là", "của", "các", "có", "cho", "trong", "được", "những", "một", "với", "này", "đó", "khi", "thì",
        "ở", "theo", "về", "từ", "đến", "cũng", "như", "bao", "nhiêu", "gì", "nào", "ai", "sao", "thế", "bị",
        "đã", "sẽ", "đang", "hay", "hoặc", "nếu", "mà", "vào", "ra", "tôi", "bạn", "mình", "em", "anh", "chị",
        "không", "chưa", "hãy", "cần", "muốn", "biết", "xin", "ạ", "nhé", "vậy", "lại", "rồi",
    }
)
PAIR_WEIGHT = 2


def _norm(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def _query_terms(query: str) -> list[str]:
    return [word for word in WORD.findall(_norm(query)) if len(word) > 1 and word not in STOP_SYLLABLES]


def focused_excerpt(content: str, query: str, size: int) -> tuple[str, int]:
    """(excerpt, where it starts in `content`). The chunk's first `size` characters, cut as before, when
    the chunk fits, when the query has no word to look for, or when no window holds more of the query
    than the head does; otherwise the best window, widened evenly around its matches and marked with an
    ellipsis on each side that was cut. The excerpt is never longer than `size`."""
    if len(content) <= size:
        return content, 0
    head = content[: size - 1] + ELLIPSIS
    terms = _query_terms(query)
    if not terms or size < 8:
        return head, 0
    wanted = set(terms)
    pairs = set(zip(terms, terms[1:]))
    text = unicodedata.normalize("NFC", content)
    if len(text) != len(content):
        # A decomposed chunk would shift offsets; showing its head is the safe answer.
        return head, 0
    words = [(match.start(), match.end(), match.group(0).casefold()) for match in WORD.finditer(text)]
    if not words:
        return head, 0
    # Room for an ellipsis on both sides: a window of `span` characters always fits.
    span = size - 2

    def evaluate(first: int, last: int) -> tuple[int, int, int, int]:
        """For words[first..last]: (score, spread, lo, hi). Score: distinct query words plus PAIR_WEIGHT
        per distinct adjacent query pair. lo..hi: from the first to the last word that brought a query
        word in for the first time, and spread its width in characters, so of two windows that hold the
        same words the one holding them closer together wins and is centred on them."""
        found: dict[str, int] = {}
        for index in range(first, last + 1):
            word = words[index][2]
            if word in wanted and word not in found:
                found[word] = index
        adjacent = {(words[index][2], words[index + 1][2]) for index in range(first, last)} & pairs
        if not found:
            return 0, 0, first, first
        lo, hi = min(found.values()), max(found.values())
        return len(found) + PAIR_WEIGHT * len(adjacent), words[hi][1] - words[lo][0], lo, hi

    def last_word(first: int) -> int:
        """The last word that still ends inside a window starting at words[first]."""
        limit = words[first][0] + span
        last = first
        while last + 1 < len(words) and words[last + 1][1] <= limit:
            last += 1
        return last

    # The head as it is shown today: words that end inside its first size - 1 characters.
    head_last = 0
    while head_last + 1 < len(words) and words[head_last + 1][1] <= size - 1:
        head_last += 1
    head_score = evaluate(0, head_last)[0] if words[0][1] <= size - 1 else 0
    best: tuple[int, int, int, int] | None = None
    for first in range(1, len(words)):
        if words[first][2] not in wanted:
            # A best window can always start on a query word: moving its start up to the first match
            # loses nothing it counts.
            continue
        value, spread, lo, hi = evaluate(first, last_word(first))
        if best is None or value > best[0] or (value == best[0] and spread < best[1]):
            best = (value, spread, lo, hi)
    if best is None or best[0] <= head_score:
        return head, 0
    _, used, lo, hi = best
    # Centre the window on the matches, inside the chunk, starting and ending on a word.
    start = max(0, words[lo][0] - (span - used) // 2)
    end = min(len(text), start + span)
    start = max(0, end - span)
    while start > 0 and start < len(text) and text[start - 1].isalnum() and text[start].isalnum():
        start += 1
    while end < len(text) and end > words[hi][1] and text[end - 1].isalnum() and text[end].isalnum():
        end -= 1
    piece = content[start:end]
    shown = piece.strip()
    start += len(piece) - len(piece.lstrip())
    prefix = ELLIPSIS if start > 0 else ""
    suffix = ELLIPSIS if end < len(text) else ""
    return prefix + shown + suffix, start
