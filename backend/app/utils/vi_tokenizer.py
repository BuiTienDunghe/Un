from __future__ import annotations

from pyvi import ViTokenizer


def tokenize_vietnamese(text: str) -> list[str]:
    """Tokenize Vietnamese while preserving multi-word terms such as ``học_sinh``."""
    tokenized = ViTokenizer.tokenize(text)
    return [token for token in tokenized.lower().split() if token]
