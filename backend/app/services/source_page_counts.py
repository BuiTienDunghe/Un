"""Bounded PDF page counts tied to a source revision, not just a document ID."""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock

from app.services import document_pages


@dataclass(frozen=True)
class SourceFingerprint:
    path: Path
    revision: str | None
    size: int
    modified_ns: int
    changed_ns: int
    device: int
    inode: int

    @classmethod
    def read(cls, path: Path, revision: str | None) -> SourceFingerprint:
        stat = path.stat()
        return cls(path, revision, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_dev, stat.st_ino)


class SourcePageCounts:
    """One current entry per document. Locks never surround PDF IO.

    Missing/unreadable files are not cached; a restored source is retried. A
    source changed during reading produces no count rather than a stale entry.
    Proven index metadata can seed a count when it postdates the source file.
    """

    def __init__(self, max_entries: int = 1024, loader: Callable[[Path], int | None] | None = None) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._max_entries = max_entries
        self._loader = loader
        self._entries: OrderedDict[str, tuple[SourceFingerprint, int]] = OrderedDict()
        self._lock = Lock()

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def discard(self, document_id: str) -> None:
        with self._lock:
            self._entries.pop(document_id, None)

    def count(self, document_id: str, path: Path, revision: str | None = None,
              *, known_pages: int | None = None, known_at: datetime | None = None) -> int | None:
        try:
            before = SourceFingerprint.read(path, revision)
        except OSError:
            self.discard(document_id)
            return None
        with self._lock:
            entry = self._entries.get(document_id)
            if entry is not None and entry[0] == before:
                self._entries.move_to_end(document_id)
                return entry[1]
        covered = (known_at is not None and known_at.utcoffset() is not None
                   and max(before.modified_ns, before.changed_ns) <= int(known_at.timestamp() * 1_000_000_000))
        pages = known_pages if known_pages and covered else (self._loader or document_pages.page_count)(path)
        try:
            after = SourceFingerprint.read(path, revision)
        except OSError:
            self.discard(document_id)
            return None
        if before != after:
            return None
        if pages is not None:
            with self._lock:
                self._entries[document_id] = (before, pages)
                self._entries.move_to_end(document_id)
                while len(self._entries) > self._max_entries:
                    self._entries.popitem(last=False)
        return pages
