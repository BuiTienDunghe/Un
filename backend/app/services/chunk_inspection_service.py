"""P4-5: read a document's active chunks the way the index sees them, and mark bad ones.

Read-only over the exact corpus retrieval serves (the BM25 snapshot predicate:
document indexed, version active and selected), so what the screen shows is
what the retriever ranks — not a staging version, not a superseded one.

Marks live in chunk_feedback, never on document_chunks: replace_chunks deletes
and recreates chunk rows on every reindex, so a column there would silently
lose every mark (the T15 class of bug). A mark is matched back to a re-indexed
chunk through content_hash — identical content means the same chunk in a new
coat, changed content is genuinely a different chunk and old marks stop
applying.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.postgres.models import ChunkFeedback, Document, DocumentChunk, DocumentVersion, new_id


class ChunkInspectionError(Exception):
    pass


class DocumentNotFoundForInspection(ChunkInspectionError):
    pass


class DocumentNotIndexedError(ChunkInspectionError):
    pass


class ChunkNotFoundError(ChunkInspectionError):
    pass


class ChunkInspectionService:
    def __init__(self, session_factory: sessionmaker) -> None:
        self.sessions = session_factory

    def _active_version(self, session, document_id: str) -> tuple[Document, DocumentVersion]:
        document = session.get(Document, document_id)
        if document is None or document.status == "deleted":
            raise DocumentNotFoundForInspection(document_id)
        if document.status != "indexed" or not document.active_version_id:
            raise DocumentNotIndexedError(document_id)
        version = session.get(DocumentVersion, document.active_version_id)
        if version is None or version.status != "active":
            raise DocumentNotIndexedError(document_id)
        return document, version

    def list_chunks(self, document_id: str, limit: int = 50, offset: int = 0) -> dict[str, object]:
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        with self.sessions() as session:
            document, version = self._active_version(session, document_id)
            rows = list(session.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.version_id == version.id)
                .order_by(DocumentChunk.chunk_index)
                .limit(limit).offset(offset)
            ))
            totals = session.execute(
                select(DocumentChunk.id, DocumentChunk.token_count)
                .where(DocumentChunk.version_id == version.id)
            ).all()
            feedback_rows = list(session.scalars(
                select(ChunkFeedback).where(ChunkFeedback.document_id == document_id)
            ))
            # Current-version marks match by uid; marks made on an older version
            # follow the content: same hash = same chunk in a new coat.
            by_uid = {item.chunk_uid: item for item in feedback_rows}
            by_hash = {item.content_hash: item for item in feedback_rows}

            def feedback_for(chunk: DocumentChunk) -> dict[str, object] | None:
                found = by_uid.get(chunk.chunk_uid) or by_hash.get(chunk.content_hash)
                if found is None:
                    return None
                return {"label": found.label, "note": found.note, "created_at": found.created_at.isoformat() if found.created_at else None}

            return {
                "document_id": document.id,
                "version_id": version.id,
                "version_number": version.version_number,
                "filename": document.original_filename,
                "total_chunks": len(totals),
                "total_tokens": sum(count for _, count in totals if count is not None),
                "limit": limit,
                "offset": offset,
                "chunks": [
                    {
                        "chunk_id": chunk.id,
                        "chunk_index": chunk.chunk_index,
                        "content": chunk.content,
                        "retrieval_context": chunk.retrieval_context,
                        "token_count": chunk.token_count,
                        "page_start": chunk.page_start,
                        "page_end": chunk.page_end,
                        "heading_path": list(chunk.heading_path or []),
                        "section_title": chunk.section_title,
                        "block_type": chunk.block_type,
                        "locations": list(chunk.locations or []),
                        "content_hash": chunk.content_hash,
                        "feedback": feedback_for(chunk),
                    }
                    for chunk in rows
                ],
            }

    def add_feedback(self, document_id: str, chunk_id: str, label: str = "bad", note: str | None = None) -> dict[str, object]:
        with self.sessions.begin() as session:
            self._active_version(session, document_id)
            chunk = session.get(DocumentChunk, chunk_id)
            if chunk is None or chunk.document_id != document_id:
                raise ChunkNotFoundError(chunk_id)
            existing = session.scalar(
                select(ChunkFeedback).where(ChunkFeedback.chunk_uid == chunk.chunk_uid, ChunkFeedback.label == label)
            )
            if existing is not None:
                # Idempotent by design (uq_chunk_feedback_uid_label): marking
                # twice updates the note instead of erroring or piling up.
                existing.note = note
                row = existing
            else:
                row = ChunkFeedback(id=new_id("cfb"), chunk_uid=chunk.chunk_uid, document_id=document_id, content_hash=chunk.content_hash, label=label, note=note)
                session.add(row)
            session.flush()
            return {"chunk_id": chunk_id, "chunk_uid": row.chunk_uid, "label": row.label, "note": row.note}

    def remove_feedback(self, document_id: str, chunk_id: str, label: str = "bad") -> bool:
        with self.sessions.begin() as session:
            chunk = session.get(DocumentChunk, chunk_id)
            if chunk is None or chunk.document_id != document_id:
                raise ChunkNotFoundError(chunk_id)
            existing = session.scalar(
                select(ChunkFeedback).where(ChunkFeedback.chunk_uid == chunk.chunk_uid, ChunkFeedback.label == label)
            )
            if existing is None:
                return False
            session.delete(existing)
            return True
