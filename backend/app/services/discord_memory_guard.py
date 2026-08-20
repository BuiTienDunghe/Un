"""Deterministic auto-apply guard for extractor proposals (P2-1b).

The 19/08 benchmark (docs/p2_progress.md) proved extractor confidence is a
constant 1.0 on right and wrong proposals alike, so the threshold alone cannot
filter content. This guard is the signal that measurably works: the proposal's
evidence must be a verbatim quote of the source message, and the fact's content
words must actually appear in that message. With qwen3.5:9b the measured
policy keeps 96.7% of clean proposals and cuts poisoned applies from 36.2% to
21.6% — `test_memory_auto_apply.py` re-derives those numbers from the stored
benchmark results with THESE functions, so the implementation and the
measurement cannot drift apart silently.

Only the agent's autonomous path runs the guard. A human approving on the
dashboard IS the guard, and stays free to apply anything.
"""
from __future__ import annotations

import re
import unicodedata

# Words too generic to prove a fact came from the message (mixed Vietnamese
# folded forms and the English the extractor writes facts in).
STOPWORDS = frozenset({
    "user", "the", "prefers", "prefer", "wants", "want", "uses", "use",
    "likes", "like", "la", "va", "cua", "cho", "toi", "minh", "hay", "rang",
    "luon", "khong", "duoc", "voi", "mot",
})

OVERLAP_MINIMUM = 0.34


def fold(text: str) -> str:
    """Accent-insensitive casefold: 'Tiếng Việt' and 'tieng viet' compare equal."""
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.replace("đ", "d").replace("Đ", "D").casefold()


def content_words(text: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9]+", fold(text))
        if len(word) > 2 and word not in STOPWORDS
    }


def fact_overlap(fact: str, source: str, minimum: float = OVERLAP_MINIMUM) -> bool:
    """Enough of the fact's content words must appear in the source message.

    This is the check that stops the observed live failure: a hallucinated
    "prefers Vietnamese" fact shares zero content words with a message about
    wanting illustrated examples.
    """
    words = content_words(fact)
    if not words:
        return False
    folded_source = fold(source)
    hits = sum(1 for word in words if word in folded_source)
    return hits / len(words) >= minimum


def evidence_grounded(evidence: str, source: str) -> bool:
    """The quoted evidence must exist verbatim in the source message."""
    return bool(evidence) and evidence in (source or "")


def auto_apply_allowed(*, canonical_fact: str | None, evidence_text: str | None, source_text: str | None) -> bool:
    source = source_text or ""
    return evidence_grounded(evidence_text or "", source) and fact_overlap(canonical_fact or "", source)
