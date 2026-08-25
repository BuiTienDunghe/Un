from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from time import monotonic

from loguru import logger
from rank_bm25 import BM25Okapi
from sqlalchemy.orm import sessionmaker

from app.postgres.repositories import PostgresDocumentRepository
from app.utils.chunking import combined_retrieval_text
from app.utils.vi_tokenizer import TOKENIZER_VERSION, tokenize_vietnamese


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
    # P4-2: indexed in front of content; never returned as citation text.
    retrieval_context: str | None
    page_start: int | None
    page_end: int | None
    locations: list[dict[str, object]]
    heading_path: list[str]
    section_title: str | None
    block_type: str
    extraction_method: str
    content_hash: str


class PostgresBm25Service:
    """Process-local sparse index rebuilt from PostgreSQL active chunks only.

    Change detection is two-layered (P4-4a, 25/08). Writes in THIS process
    (thread-path activation, delete, source removal) call invalidate() and are
    visible on the very next search — the interactive upload-then-ask flow
    stays immediate. Writes from OTHER processes (RQ index worker, the cleanup
    container) are caught by the fingerprint query, which no longer runs on
    every search but at most once per `fingerprint_ttl_seconds`. That amortizes
    the per-question DB round-trip (measured 5.7 ms) without the failure mode
    an invalidate-only design would have: under any multi-process setup it
    would simply never see external writes, silently and permanently.
    """

    def __init__(self, session_factory: sessionmaker, fingerprint_ttl_seconds: float = 5.0) -> None:
        self.sessions = session_factory
        self.fingerprint_ttl_seconds = fingerprint_ttl_seconds
        self._lock = RLock()
        self._fingerprint: tuple[tuple[object, ...], ...] | None = None
        self._checked_at: float | None = None
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
                    retrieval_context=chunk.retrieval_context,
                    page_start=chunk.page_start, page_end=chunk.page_end,
                    locations=list(chunk.locations or []), heading_path=list(chunk.heading_path or []),
                    section_title=chunk.section_title, block_type=chunk.block_type,
                    extraction_method=chunk.extraction_method, content_hash=chunk.content_hash,
                )
                for document, version, chunk in rows
            ]

    def _current_fingerprint(self) -> tuple[tuple[object, ...], ...]:
        # A single aggregate query: the previous per-chunk scan made every
        # /rag/chat pay O(corpus) just to detect "nothing changed".
        with self.sessions() as session:
            return tuple(
                (doc_id, version_id, filename, source_available, self._stamp(activated_at), int(chunk_count), self._stamp(newest_chunk))
                for doc_id, version_id, filename, source_available, activated_at, chunk_count, newest_chunk in PostgresDocumentRepository(session).active_chunk_fingerprint()
            )

    def invalidate(self) -> None:
        with self._lock:
            self._fingerprint, self._checked_at, self._index, self._chunks = None, None, None, []

    def _ensure_index(self) -> None:
        with self._lock:
            # Inside the TTL window an existing index is served as-is; a
            # same-process write has reset _checked_at via invalidate(), so
            # this shortcut never hides our own writes.
            if self._index is not None and self._checked_at is not None and monotonic() - self._checked_at < self.fingerprint_ttl_seconds:
                return
        fingerprint = self._current_fingerprint()
        with self._lock:
            self._checked_at = monotonic()
            if fingerprint == self._fingerprint:
                return
            chunks = self._snapshot()
            self._chunks = chunks
            self._index = BM25Okapi([tokenize_vietnamese(combined_retrieval_text(chunk.retrieval_context, chunk.content)) for chunk in chunks]) if chunks else None
            self._fingerprint = fingerprint
            self.rebuild_count += 1
        # T16: every lexeme in the index just built came out of this tokenizer.
        # The index is ephemeral, so the version is not stored beside it — it is
        # logged beside it, which is the same guarantee for data that dies with
        # the process: a ranking that moved after a reinstall is explainable.
        logger.bind(
            event="bm25_rebuilt", chunks=len(chunks), tokenizer_version=TOKENIZER_VERSION,
            rebuild_count=self.rebuild_count,
        ).info("BM25 rebuilt over {} chunks ({})", len(chunks), TOKENIZER_VERSION)

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
                for position, chunk in enumerate(self._chunks):
                    if requested is not None and chunk.document_id not in requested:
                        continue
                    # Reuse the per-chunk token counts BM25Okapi built from the
                    # exact same tokenize_vietnamese output at index time.
                    # Re-tokenizing the corpus here made every zero-score query
                    # (typically an out-of-corpus question) cost a full rebuild
                    # — ~98% of which is pyvi — scaling with corpus size.
                    overlap = sum(count for token, count in self._index.doc_freqs[position].items() if token in wanted)
                    if overlap:
                        fallback.append((chunk, float(overlap)))
                fallback.sort(key=lambda item: (-item[1], item[0].document_id, item[0].chunk_index))
                return [self._result(chunk, score) for chunk, score in fallback[:top_k]]
            return result
