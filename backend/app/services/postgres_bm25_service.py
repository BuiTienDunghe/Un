from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock

from rank_bm25 import BM25Okapi
from sqlalchemy.orm import sessionmaker

from app.postgres.repositories import PostgresDocumentRepository
from app.utils.vi_tokenizer import tokenize_vietnamese


@dataclass(frozen=True)
class _IndexedChunk:
    document_id: str
    version_id: str
    version_number: int
    chunk_id: str
    chunk_index: int
    filename: str
    source_available: bool
    content: str
    page_start: int | None
    page_end: int | None
    locations: list[dict[str, object]]
    heading_path: list[str]
    section_title: str | None
    block_type: str
    extraction_method: str
    content_hash: str


class PostgresBm25Service:
    """Process-local sparse index rebuilt from PostgreSQL active chunks only."""

    def __init__(self, session_factory: sessionmaker) -> None:
        self.sessions = session_factory
        self._lock = RLock()
        self._fingerprint: tuple[tuple[object, ...], ...] | None = None
        self._index: BM25Okapi | None = None
        self._chunks: list[_IndexedChunk] = []
        self.rebuild_count = 0

    @staticmethod
    def _stamp(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    def _snapshot(self, document_id: str | list[str] | None = None) -> list[_IndexedChunk]:
        requested = [document_id] if isinstance(document_id, str) else document_id
        with self.sessions() as session:
            rows = PostgresDocumentRepository(session).active_chunk_snapshot(requested)
            return [
                _IndexedChunk(
                    document_id=document.id, version_id=version.id, version_number=version.version_number,
                    chunk_id=chunk.id, chunk_index=chunk.chunk_index, filename=document.original_filename,
                    source_available=document.source_available, content=chunk.content,
                    page_start=chunk.page_start, page_end=chunk.page_end,
                    locations=list(chunk.locations or []), heading_path=list(chunk.heading_path or []),
                    section_title=chunk.section_title, block_type=chunk.block_type,
                    extraction_method=chunk.extraction_method, content_hash=chunk.content_hash,
                )
                for document, version, chunk in rows
            ]

    def _current_fingerprint(self) -> tuple[tuple[object, ...], ...]:
        with self.sessions() as session:
            rows = PostgresDocumentRepository(session).active_chunk_snapshot()
            grouped: dict[tuple[str, str], list[object]] = {}
            for document, version, chunk in rows:
                key = (document.id, version.id)
                state = grouped.setdefault(key, [document.updated_at, version.activated_at, 0, None])
                state[2] = int(state[2]) + 1
                stamps = [item for item in (state[3], chunk.created_at) if item is not None]
                state[3] = max(stamps) if stamps else None
            return tuple(sorted((doc_id, version_id, self._stamp(values[0]), self._stamp(values[1]), values[2], self._stamp(values[3])) for (doc_id, version_id), values in grouped.items()))

    def invalidate(self) -> None:
        with self._lock:
            self._fingerprint, self._index, self._chunks = None, None, []

    def _ensure_index(self) -> None:
        fingerprint = self._current_fingerprint()
        with self._lock:
            if fingerprint == self._fingerprint:
                return
            chunks = self._snapshot()
            self._chunks = chunks
            self._index = BM25Okapi([tokenize_vietnamese(chunk.content) for chunk in chunks]) if chunks else None
            self._fingerprint = fingerprint
            self.rebuild_count += 1

    @staticmethod
    def _result(chunk: _IndexedChunk, score: float) -> dict[str, object]:
        return {
            "document_id": chunk.document_id, "version_id": chunk.version_id,
            "index_version": chunk.version_number, "chunk_id": chunk.chunk_id,
            "chunk_index": chunk.chunk_index, "filename": chunk.filename,
            "source_available": chunk.source_available, "content": chunk.content,
            "content_hash": chunk.content_hash, "page": chunk.page_start,
            "page_start": chunk.page_start, "page_end": chunk.page_end,
            "locations": chunk.locations, "heading_path": " > ".join(chunk.heading_path) or None,
            "section_title": chunk.section_title, "block_type": chunk.block_type,
            "extraction_method": chunk.extraction_method, "score": score,
        }

    def search(self, question: str, top_k: int, document_id: str | list[str] | None = None) -> list[dict[str, object]]:
        self._ensure_index()
        with self._lock:
            if not self._index:
                return []
            requested = {document_id} if isinstance(document_id, str) else (set(document_id) if document_id is not None else None)
            query_tokens = tokenize_vietnamese(question)
            scores = self._index.get_scores(query_tokens)
            ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)
            result: list[dict[str, object]] = []
            for index, score in ranked:
                chunk = self._chunks[index]
                if score <= 0 or (requested is not None and chunk.document_id not in requested):
                    continue
                result.append(self._result(chunk, float(score)))
                if len(result) >= top_k:
                    break
            # rank_bm25 assigns zero IDF to a token present in every currently
            # indexed chunk (notably a one-document corpus).  Returning no
            # exact lexical match is worse than the legacy behavior users
            # expect, so only in this all-zero case use deterministic token
            # overlap as a sparse fallback; it never mixes with a positive
            # BM25 ranking.
            if not result and query_tokens:
                wanted = set(query_tokens)
                fallback = []
                for chunk in self._chunks:
                    if requested is not None and chunk.document_id not in requested:
                        continue
                    overlap = sum(1 for token in tokenize_vietnamese(chunk.content) if token in wanted)
                    if overlap:
                        fallback.append((chunk, float(overlap)))
                fallback.sort(key=lambda item: (-item[1], item[0].document_id, item[0].chunk_index))
                return [self._result(chunk, score) for chunk, score in fallback[:top_k]]
            return result
