"""Accent-insensitive matching of Vietnamese text, shared by the core and the Discord memory guard.

Both live here because both sides use them: the Discord memory guard (P2-1b) was
first, and the core's answer self-check (`answer_grounding`, D3a) applies the same
idea to RAG answers. Keeping them in a Discord module made the core import Discord
(ticket 22); `discord_memory_guard` re-exports both names, so its importers are unchanged.
"""
from __future__ import annotations

import unicodedata

# Words too generic to prove a fact came from the message (mixed Vietnamese
# folded forms and the English the extractor writes facts in).
STOPWORDS = frozenset({
    "user", "the", "prefers", "prefer", "wants", "want", "uses", "use",
    "likes", "like", "la", "va", "cua", "cho", "toi", "minh", "hay", "rang",
    "luon", "khong", "duoc", "voi", "mot",
})


def fold(text: str) -> str:
    """Accent-insensitive casefold: 'Tiếng Việt' and 'tieng viet' compare equal."""
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.replace("đ", "d").replace("Đ", "D").casefold()
