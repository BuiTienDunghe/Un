"""Answer self-check without a model (D3a): is each sentence backed by a cited source?

Inference-budget invariant (plan §1): this costs zero model calls. It is the
memory guard's idea (``discord_memory_guard``) applied to RAG answers — accent
folding, content-word overlap and verbatim evidence — extended from "one fact
vs one message" to "every sentence of an answer vs the bare text of the chunks
that were actually cited".

What it is and is not:
- It measures *lexical support*: did the words and phrases of a sentence come
  from the sources? That catches the failure that matters most in a
  citation-grounded product — fluent text that the sources never said.
- It does NOT judge truth or reasoning. A paraphrase that uses different words
  than the source scores lower than it deserves (known blind spot, same as the
  cross-language case noted in T12): the design choice is to under-report
  grounding rather than to certify invented text, so ``weak`` is the safe side.
- Sources are scored on their bare ``content`` — never on generated
  ``retrieval_context`` (P4-2), which is index-only text the user cannot see.

Only reporting happens here. Blocking or rewriting an answer is a product
decision that needs the heavy-machine measurement first (docs/d3a_answer_grounding.md).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from app.services.discord_memory_guard import STOPWORDS as GUARD_STOPWORDS
from app.services.discord_memory_guard import fold

# Thresholds — all ratios of a sentence's content words found in the sources.
# 0.34 is the memory guard's measured floor (P2-1b benchmark): below it a
# "fact" shares too little with its source to have come from it. 0.6 marks a
# sentence that is mostly the source's own vocabulary; between the two the
# sentence is plausible but partially unsupported (or paraphrased).
GROUNDED_MINIMUM = 0.60
WEAK_MINIMUM = 0.34
# A run of this many consecutive answer words found verbatim in a source is
# strong evidence on its own (the memory guard's "evidence verbatim" idea) and
# promotes a sentence straight to grounded, whatever its overlap ratio.
VERBATIM_RUN = 4
# Sentences with fewer content words than this are not claims worth judging
# ("Chắc chắn rồi.", "Tóm lại:", headings) and would only add noise either way.
MIN_CONTENT_WORDS = 4
# An answer is grounded as a whole when at least this share of its judged
# sentences are grounded AND nothing is ungrounded; any ungrounded sentence
# makes the whole answer ungrounded — one invented claim is one too many.
ANSWER_GROUNDED_SHARE = 0.80

# Generic Vietnamese/English answer vocabulary that proves nothing about
# provenance; extends the memory guard's list with words RAG answers lean on.
STOPWORDS = GUARD_STOPWORDS | frozenset({
    "theo", "trong", "nay", "nhu", "den", "tu", "cac", "nhung", "khi", "thi",
    "neu", "nen", "se", "da", "dang", "con", "hon", "rat", "cung", "ve", "tai",
    "bang", "sau", "truoc", "tren", "duoi", "tai", "lieu", "doan", "trich",
    "cau", "hoi", "tra", "loi", "nguon", "thong", "tin", "viec", "dieu", "nay",
    "nhu", "vay", "co", "the", "phai", "can", "lam", "dung", "ban", "chung",
    "and", "for", "with", "that", "this", "from", "are", "was", "not", "you",
    "can", "will", "has", "have", "been", "into", "its", "also", "which",
    "context", "document", "documents", "source", "sources", "according",
})

# Courtesy / scaffolding sentences are not claims; they are skipped before
# judging rather than counted as ungrounded.
_PLEASANTRY = re.compile(
    r"^(xin chao|chao ban|cam on|rat vui|hy vong|neu ban can|ban co the hoi|tom lai|ket luan|"
    r"noi tom lai|nhu vay|hello|hi|thanks|thank you|in summary|to summarize|sure|of course)\b"
)

# Letters that only Vietnamese uses (checked BEFORE folding). A lexical check
# cannot see across languages — an English answer over Vietnamese sources
# shares almost no tokens however faithful it is (the T12 blind spot). Such
# sentences are capped at "weak" and flagged, never called ungrounded: the
# honest statement is "cannot judge", not "invented".
_VIETNAMESE_LETTERS = re.compile("[ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ]")

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+")
_LEADING_MARKUP = re.compile(r"^\s*(?:[-*•]+|\d+[.)]|#+)\s*")


@dataclass
class SentenceGrounding:
    text: str
    label: str  # grounded | weak | ungrounded
    overlap: float
    verbatim: bool


@dataclass
class GroundingReport:
    label: str  # grounded | weak | ungrounded | unjudged
    grounded_ratio: float
    judged: int
    grounded: int
    weak: int
    ungrounded: int
    # True when at least one sentence was capped at "weak" because it is not
    # in the sources' language — the verdict is "unjudgeable", not "invented".
    language_mismatch: bool = False
    sentences: list[SentenceGrounding] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        # Only unsupported sentences travel to the API: the grounded ones are
        # the answer itself, and the client shows the gaps, not the whole text.
        data["sentences"] = [asdict(item) for item in self.sentences if item.label != "grounded"]
        return data


def content_words(text: str) -> list[str]:
    """Ordered content words (folded, stopwords removed); order matters for runs."""
    return [word for word in re.findall(r"[a-z0-9]+", fold(text)) if len(word) > 2 and word not in STOPWORDS]


def split_sentences(answer: str) -> list[str]:
    sentences: list[str] = []
    for raw in _SENTENCE_SPLIT.split(answer or ""):
        cleaned = _LEADING_MARKUP.sub("", raw or "").strip()
        if cleaned:
            sentences.append(cleaned)
    return sentences


def is_pleasantry(sentence: str) -> bool:
    return bool(_PLEASANTRY.match(fold(sentence).strip()))


def looks_vietnamese(text: str, minimum: int = 1) -> bool:
    return len(_VIETNAMESE_LETTERS.findall((text or "").lower())) >= minimum


def _verbatim_run(words: list[str], source_words: set[tuple[str, ...]]) -> bool:
    if len(words) < VERBATIM_RUN:
        return False
    return any(tuple(words[i : i + VERBATIM_RUN]) in source_words for i in range(len(words) - VERBATIM_RUN + 1))


def _source_index(sources: list[str]) -> tuple[set[str], set[tuple[str, ...]]]:
    """Vocabulary and VERBATIM_RUN-grams of all sources, built once per answer."""
    vocabulary: set[str] = set()
    runs: set[tuple[str, ...]] = set()
    for source in sources:
        # Same normalisation as the answer side (content_words), so a run of
        # answer words can only match a run of source words token for token.
        content = content_words(source)
        vocabulary.update(content)
        runs.update(tuple(content[i : i + VERBATIM_RUN]) for i in range(max(0, len(content) - VERBATIM_RUN + 1)))
    return vocabulary, runs


def judge_sentence(sentence: str, vocabulary: set[str], runs: set[tuple[str, ...]], sources_vietnamese: bool | None = None) -> tuple[SentenceGrounding, bool] | None:
    """(verdict, language_mismatch) for one sentence, or None when not a claim."""
    words = content_words(sentence)
    if len(words) < MIN_CONTENT_WORDS or is_pleasantry(sentence):
        return None
    overlap = sum(1 for word in words if word in vocabulary) / len(words)
    verbatim = _verbatim_run(words, runs)
    if verbatim or overlap >= GROUNDED_MINIMUM:
        label = "grounded"
    elif overlap >= WEAK_MINIMUM:
        label = "weak"
    else:
        label = "ungrounded"
    mismatch = sources_vietnamese is not None and looks_vietnamese(sentence) != sources_vietnamese
    if mismatch and label == "ungrounded":
        label = "weak"  # cannot judge across languages; cap on the safe side
    return SentenceGrounding(text=sentence, label=label, overlap=round(overlap, 3), verbatim=verbatim), (mismatch and label != "grounded")


def grade_answer(answer: str, sources: list[str]) -> GroundingReport:
    """Score an answer against the bare text of the chunks it was generated from.

    ``sources`` are chunk ``content`` strings (what the model saw and what the
    user can open) — callers must not pass ``retrieval_context``.
    """
    texts = [source for source in sources if source]
    vocabulary, runs = _source_index(texts)
    # Language of the sources as a whole (a few letters, not one stray accent);
    # None when there are no sources, which disables the cap — an answer with
    # no sources is unsupported in any language.
    sources_vietnamese = looks_vietnamese(" ".join(texts), minimum=3) if texts else None
    judged: list[SentenceGrounding] = []
    mismatch = False
    for sentence in split_sentences(answer):
        result = judge_sentence(sentence, vocabulary, runs, sources_vietnamese)
        if result is not None:
            verdict, sentence_mismatch = result
            judged.append(verdict)
            mismatch = mismatch or sentence_mismatch
    counts = {label: sum(1 for item in judged if item.label == label) for label in ("grounded", "weak", "ungrounded")}
    if not judged:
        # Nothing judgeable (empty answer, only pleasantries): "unjudged" keeps
        # this apart from a real verdict either way.
        return GroundingReport(label="unjudged", grounded_ratio=0.0, judged=0, grounded=0, weak=0, ungrounded=0, sentences=judged)
    ratio = counts["grounded"] / len(judged)
    if counts["ungrounded"]:
        label = "ungrounded"
    elif ratio >= ANSWER_GROUNDED_SHARE:
        label = "grounded"
    else:
        label = "weak"
    return GroundingReport(label=label, grounded_ratio=round(ratio, 3), judged=len(judged), language_mismatch=mismatch, sentences=judged, **counts)


def grade_rag_answer(answer: str, sources: list[dict[str, object]]) -> dict[str, object]:
    """Adapter for the RAG service: takes the retrieval ``sources`` dicts."""
    return grade_answer(answer, [str(source.get("content") or "") for source in sources]).to_dict()
