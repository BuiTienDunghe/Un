from __future__ import annotations

import re


def chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Split on paragraph/sentence boundaries, retaining a small word overlap."""
    if not text:
        return []
    units = [unit.strip() for unit in re.split(r"\n\s*\n|(?<=[.!?])\s+", text) if unit.strip()]
    chunks: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current}\n\n{unit}".strip() if current else unit
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        if current:
            chunks.append(current)
        overlap = current[-chunk_overlap:].split(" ", 1)[-1] if current and chunk_overlap else ""
        current = f"{overlap} {unit}".strip()
        while len(current) > chunk_size:
            split_at = current.rfind(" ", 0, chunk_size)
            split_at = split_at if split_at > 0 else chunk_size
            chunks.append(current[:split_at].strip())
            current = current[max(0, split_at - chunk_overlap):].strip()
    if current:
        chunks.append(current)
    return chunks
