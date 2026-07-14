from __future__ import annotations

from pathlib import Path


def safe_upload_suffix(filename: str) -> str:
    """Return a normalized suffix only; the original filename is never used as a storage path."""
    return Path(filename).suffix.lower()
