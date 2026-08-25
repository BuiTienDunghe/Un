"""Vietnamese word segmentation — the input to every sparse (BM25) lexeme.

T16: the tokenizer is a *versioned dependency of derived data*, not a pure
function. pyvi 0.1.1 segments "học sinh" into the single lexeme "học_sinh";
another release may segment it differently, and every BM25 term in the corpus
changes with it. Today that is a runtime-only drift, because the sparse index
is rebuilt from PostgreSQL at startup — the worst case is a retrieval ranking
that quietly moved between two installs, with the eval baseline still claiming
the old numbers. The moment a lexeme is *persisted* (P4-4b, plan §9) the same
drift becomes permanently dirty data that nothing signals.

Hence three rules, in the only order that makes them true:
  1. requirements.txt pins the version EXACTLY, not as a range.
  2. This constant is read back from the installed package, never hard-coded —
     a version constant that can disagree with reality is worse than none.
  3. Anything derived from it records it: the BM25 rebuild log, /models, and
     the eval baseline (which refuses to gate across a tokenizer change, the
     same way it already refuses across an embedding-model change).
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_version

from pyvi import ViTokenizer


def _tokenizer_version() -> str:
    try:
        return f"pyvi-{installed_version('pyvi')}"
    except PackageNotFoundError:  # pragma: no cover - only if pyvi is vendored, not installed
        return "pyvi-unknown"


#: Identity of the segmentation contract, e.g. "pyvi-0.1.1". Resolved once at
#: import: the installed distribution cannot change under a running process.
TOKENIZER_VERSION = _tokenizer_version()


def tokenize_vietnamese(text: str) -> list[str]:
    """Tokenize Vietnamese while preserving multi-word terms such as ``học_sinh``."""
    tokenized = ViTokenizer.tokenize(text)
    return [token for token in tokenized.lower().split() if token]
