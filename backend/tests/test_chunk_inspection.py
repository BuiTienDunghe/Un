"""P4-5: the chunk screen shows exactly what the retriever indexes, and marks survive reindexing."""
from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import ChunkFeedback, Document, DocumentVersion
from app.postgres.repositories import PostgresDocumentRepository
from app.services.chunk_inspection_service import (
    ChunkInspectionService,
    DocumentNotFoundForInspection,
    DocumentNotIndexedError,
)
from app.utils.chunking import chunk_pages

URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")

TEXT = (
    "# Guide\n\n## Setup\n\n"
    "Install the tool before anything else and read every warning the installer prints on the way through.\n\n"
    "The second paragraph explains configuration in much more detail than anyone reasonably wants to read.\n\n"
    "A third paragraph exists purely so the twenty-token budget must split this document into several chunks."
)


@pytest.fixture
def factory():
    return create_session_factory(create_postgres_engine(str(URL)))


def _seed_document(factory, *, indexed: bool = True, text: str = TEXT) -> tuple[str, str]:
    suffix = uuid4().hex
    doc_id, version_id = f"doc_p45_{suffix}", f"ver_p45_{suffix}"
    with factory.begin() as session:
        document = Document(id=doc_id, original_filename=f"p45-{suffix}.md", stored_filename=f"{doc_id}.md", mime_type="text/markdown", content_hash=uuid4().hex * 2, status="indexed" if indexed else "uploaded", source_available=True)
        version = DocumentVersion(id=version_id, document_id=doc_id, version_number=1, status="active" if indexed else "staging", activated_at=datetime.now(UTC) if indexed else None, chunking_config={})
        if indexed:
            document.active_version_id = version_id
        session.add_all((document, version))
        session.flush()
        if indexed:
            PostgresDocumentRepository(session).replace_chunks(doc_id, version_id, chunk_pages([(1, text, "native")], 20, 0))
    return doc_id, version_id


def _cleanup(factory):
    with factory.begin() as session:
        from sqlalchemy import delete
        session.execute(delete(ChunkFeedback))
        session.execute(delete(Document).where(Document.original_filename.like("p45-%")))


def test_list_chunks_serves_the_active_version_with_full_metadata(factory):
    _cleanup(factory)
    doc_id, version_id = _seed_document(factory)
    service = ChunkInspectionService(factory)

    result = service.list_chunks(doc_id)

    assert result["version_id"] == version_id and result["total_chunks"] == len(result["chunks"]) > 1
    assert result["total_tokens"] > 0
    first = result["chunks"][0]
    # The nine columns the design promises, in the JSONB list form for headings.
    for key in ("chunk_id", "chunk_index", "content", "token_count", "heading_path", "block_type", "locations", "content_hash", "page_start"):
        assert key in first
    assert any(chunk["heading_path"] == ["Guide", "Setup"] for chunk in result["chunks"])
    assert all(chunk["feedback"] is None for chunk in result["chunks"])
    _cleanup(factory)


def test_list_chunks_paginates_in_index_order(factory):
    _cleanup(factory)
    doc_id, _ = _seed_document(factory)
    service = ChunkInspectionService(factory)

    total = service.list_chunks(doc_id)["total_chunks"]
    first = service.list_chunks(doc_id, limit=1, offset=0)
    second = service.list_chunks(doc_id, limit=1, offset=1)

    assert first["chunks"][0]["chunk_index"] == 0 and second["chunks"][0]["chunk_index"] == 1
    assert first["total_chunks"] == second["total_chunks"] == total
    _cleanup(factory)


def test_missing_and_unindexed_documents_raise_their_own_errors(factory):
    _cleanup(factory)
    unindexed, _ = _seed_document(factory, indexed=False)
    service = ChunkInspectionService(factory)

    with pytest.raises(DocumentNotFoundForInspection):
        service.list_chunks("doc_p45_khong_ton_tai")
    with pytest.raises(DocumentNotIndexedError):
        service.list_chunks(unindexed)
    _cleanup(factory)


def test_feedback_is_idempotent_and_removable(factory):
    _cleanup(factory)
    doc_id, _ = _seed_document(factory)
    service = ChunkInspectionService(factory)
    chunk_id = service.list_chunks(doc_id)["chunks"][0]["chunk_id"]

    service.add_feedback(doc_id, chunk_id, note="cắt ngang câu")
    # Marking twice updates the note instead of erroring (uq uid+label).
    saved = service.add_feedback(doc_id, chunk_id, note="cắt ngang câu, bản 2")
    assert saved["note"] == "cắt ngang câu, bản 2"

    listed = service.list_chunks(doc_id)["chunks"][0]
    assert listed["feedback"] == {"label": "bad", "note": "cắt ngang câu, bản 2", "created_at": listed["feedback"]["created_at"]}

    assert service.remove_feedback(doc_id, chunk_id) is True
    assert service.remove_feedback(doc_id, chunk_id) is False
    assert service.list_chunks(doc_id)["chunks"][0]["feedback"] is None
    _cleanup(factory)


def test_feedback_survives_reindex_with_same_content_but_not_changed_content(factory):
    """The design's core storage decision, proven through the real write path.

    replace_chunks deletes and recreates chunk rows; a new version gives every
    chunk a new uid. A mark must follow identical CONTENT into the new version
    (content_hash bridge) and must stop applying when the content changed.
    """
    _cleanup(factory)
    doc_id, version_id = _seed_document(factory)
    service = ChunkInspectionService(factory)
    marked = service.list_chunks(doc_id)["chunks"][0]
    service.add_feedback(doc_id, marked["chunk_id"], note="đánh trước re-index")

    # "Re-index": a NEW active version, same text -> same chunk contents.
    with factory.begin() as session:
        old = session.get(DocumentVersion, version_id)
        old.status, old.superseded_at = "superseded", datetime.now(UTC)
        new_version = DocumentVersion(id=f"ver_p45_{uuid4().hex}", document_id=doc_id, version_number=2, status="active", activated_at=datetime.now(UTC), chunking_config={})
        session.add(new_version)
        session.flush()
        session.get(Document, doc_id).active_version_id = new_version.id
        PostgresDocumentRepository(session).replace_chunks(doc_id, new_version.id, chunk_pages([(1, TEXT, "native")], 20, 0))

    relisted = service.list_chunks(doc_id)
    assert relisted["version_number"] == 2
    survived = relisted["chunks"][0]
    assert survived["chunk_id"] != marked["chunk_id"]          # new row entirely
    assert survived["content_hash"] == marked["content_hash"]  # same content
    assert survived["feedback"] is not None and survived["feedback"]["note"] == "đánh trước re-index"

    # Version 3 with different text: the old mark must NOT stick to new content.
    with factory.begin() as session:
        current = session.get(Document, doc_id)
        session.get(DocumentVersion, current.active_version_id).status = "superseded"
        third = DocumentVersion(id=f"ver_p45_{uuid4().hex}", document_id=doc_id, version_number=3, status="active", activated_at=datetime.now(UTC), chunking_config={})
        session.add(third)
        session.flush()
        current.active_version_id = third.id
        PostgresDocumentRepository(session).replace_chunks(doc_id, third.id, chunk_pages([(1, "# Guide\n\nEntirely rewritten body text.", "native")], 20, 0))

    rewritten = service.list_chunks(doc_id)
    assert all(chunk["feedback"] is None for chunk in rewritten["chunks"])
    _cleanup(factory)


def test_endpoints_return_200_404_409_and_write_feedback(client):
    factory = create_session_factory(create_postgres_engine(str(URL)))
    _cleanup(factory)
    doc_id, _ = _seed_document(factory)
    unindexed, _ = _seed_document(factory, indexed=False)

    listing = client.get(f"/documents/{doc_id}/chunks")
    assert listing.status_code == 200
    body = listing.json()
    assert body["total_chunks"] > 1 and body["chunks"][0]["chunk_index"] == 0

    assert client.get("/documents/doc_khong_co/chunks").status_code == 404
    assert client.get(f"/documents/{unindexed}/chunks").status_code == 409

    chunk_id = body["chunks"][0]["chunk_id"]
    saved = client.post(f"/documents/{doc_id}/chunks/{chunk_id}/feedback", json={"note": "kém"})
    assert saved.status_code == 200 and saved.json()["label"] == "bad"
    assert client.get(f"/documents/{doc_id}/chunks").json()["chunks"][0]["feedback"]["note"] == "kém"
    assert client.delete(f"/documents/{doc_id}/chunks/{chunk_id}/feedback").status_code == 204
    assert client.delete(f"/documents/{doc_id}/chunks/{chunk_id}/feedback").status_code == 404
    _cleanup(factory)
