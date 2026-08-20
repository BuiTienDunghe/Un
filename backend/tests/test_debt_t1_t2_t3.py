"""Regression tests for the P0.5 debt fixes T1, T2, T3 (document pipeline).

T1 — content of a deleted document can be uploaded again (partial unique).
T2 — cancelling an RQ ingestion nobody claimed finalizes instead of sticking.
T3 — replace is atomic: the new hash can never commit without its reindex run.
"""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.config.settings import get_settings
from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Document, DocumentChunk, DocumentVersion, IngestionRun, Job

URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")


@pytest.fixture
def factory():
    return create_session_factory(create_postgres_engine(str(URL)))


@pytest.fixture
def debt_cleanup(factory):
    prefix = f"debt-{uuid4().hex[:8]}"
    yield prefix
    with factory.begin() as session:
        ids = list(session.scalars(select(Document.id).where(Document.original_filename.like(f"{prefix}%"))))
        if ids:
            session.execute(delete(Job).where(Job.document_id.in_(ids)))
            session.execute(delete(DocumentChunk).where(DocumentChunk.document_id.in_(ids)))
            session.execute(delete(IngestionRun).where(IngestionRun.document_id.in_(ids)))
            for document in session.scalars(select(Document).where(Document.id.in_(ids))):
                document.active_version_id = None
            session.execute(delete(DocumentVersion).where(DocumentVersion.document_id.in_(ids)))
            session.execute(delete(Document).where(Document.id.in_(ids)))
    for folder in Path(get_settings().documents_path).glob("doc_debttest*"):
        shutil.rmtree(folder, ignore_errors=True)


def seed_document(factory, prefix: str, *, status: str, content_hash: str, run_stage: str | None = None, job_status: str | None = None):
    """One document row (plus optional mid-flight run/job) without touching
    the real ingestion pipeline."""
    doc_id = f"doc_debttest{uuid4().hex[:10]}"
    with factory.begin() as session:
        session.add(Document(
            id=doc_id,
            original_filename=f"{prefix}.txt",
            stored_filename=f"{doc_id}.txt",
            mime_type="text/plain",
            file_size=1,
            content_hash=content_hash,
            status=status,
        ))
        run_id = version_id = job_id = None
        if run_stage is not None:
            version_id, run_id = f"ver_{uuid4().hex}", f"ing_{uuid4().hex}"
            session.add(DocumentVersion(id=version_id, document_id=doc_id, version_number=1, status="staging", chunking_config={}))
            session.add(IngestionRun(id=run_id, document_id=doc_id, version_id=version_id, status="queued", current_stage=run_stage))
        if job_status is not None:
            job_id = f"job_{uuid4().hex}"
            session.add(Job(id=job_id, job_type="extract_document", document_id=doc_id, version_id=version_id, ingestion_run_id=run_id, status=job_status, max_attempts=3, idempotency_key=f"debt:{job_id}"))
    return doc_id, run_id, job_id


# ── T1 ──────────────────────────────────────────────────────────────


def test_t1_content_of_a_deleted_document_can_return(client, mock_ollama, factory, debt_cleanup):
    prefix = debt_cleanup
    content = f"tai lieu {prefix} da xoa roi upload lai".encode()
    digest = hashlib.sha256(content).hexdigest()
    seed_document(factory, prefix, status="deleted", content_hash=digest)

    upload = client.post("/documents/upload", files={"file": (f"{prefix}-again.txt", content, "text/plain")})

    # Before the partial index this was an IntegrityError surfacing as a 500.
    assert upload.status_code == 201
    body = upload.json()
    assert body["duplicate"] is False and body["content_hash"] == digest


def test_t1_live_duplicates_are_still_rejected_by_the_database(factory, debt_cleanup):
    prefix = debt_cleanup
    digest = hashlib.sha256(f"{prefix}-live".encode()).hexdigest()
    seed_document(factory, prefix, status="indexed", content_hash=digest)
    # A second LIVE row with the same hash must still violate uniqueness.
    with pytest.raises(IntegrityError):
        seed_document(factory, prefix, status="uploaded", content_hash=digest)
    # A second DELETED row with the same hash is fine — history may repeat.
    seed_document(factory, prefix, status="deleted", content_hash=digest)


# ── T2 ──────────────────────────────────────────────────────────────


def test_t2_cancelling_an_unclaimed_rq_job_finalizes_everything(client, mock_ollama, factory, debt_cleanup, monkeypatch):
    prefix = debt_cleanup
    doc_id, run_id, job_id = seed_document(
        factory, prefix, status="processing",
        content_hash=hashlib.sha256(f"{prefix}-t2".encode()).hexdigest(),
        run_stage="queued", job_status="queued",
    )
    monkeypatch.setattr(client.app.state.document_service, "job_queue", object())

    cancelled = client.post(f"/documents/ingestions/{run_id}/cancel", headers={})

    assert cancelled.status_code == 200
    with factory() as session:
        run = session.get(IngestionRun, run_id)
        job = session.get(Job, job_id)
        document = session.get(Document, doc_id)
        assert run.current_stage == "cancelled"
        assert job.status == "cancelled"
        assert document.status == "uploaded"  # no active version to fall back to
    # The escape hatch: a cancelled run no longer blocks a fresh reindex...
    # (create_reindex accepts terminal stages; the endpoint would 409 only on
    # a missing source file, which this synthetic document does not have.)


def test_t2_a_claimed_job_keeps_the_cooperative_cancel_flag(client, mock_ollama, factory, debt_cleanup, monkeypatch):
    prefix = debt_cleanup
    doc_id, run_id, job_id = seed_document(
        factory, prefix, status="processing",
        content_hash=hashlib.sha256(f"{prefix}-t2b".encode()).hexdigest(),
        run_stage="parsing", job_status="running",
    )
    monkeypatch.setattr(client.app.state.document_service, "job_queue", object())

    cancelled = client.post(f"/documents/ingestions/{run_id}/cancel")

    assert cancelled.status_code == 200
    with factory() as session:
        run = session.get(IngestionRun, run_id)
        job = session.get(Job, job_id)
        document = session.get(Document, doc_id)
        # The worker owns the job: only the flag is set, states are untouched.
        assert run.cancel_requested is True and run.current_stage == "parsing"
        assert job.status == "cancel_requested"
        assert document.status == "processing"


# ── T3 ──────────────────────────────────────────────────────────────


def test_t3_replace_is_refused_while_a_run_is_active_and_nothing_changes(client, mock_ollama, factory, debt_cleanup):
    prefix = debt_cleanup
    old_content = f"noi dung cu {prefix}".encode()
    old_digest = hashlib.sha256(old_content).hexdigest()
    doc_id, _, _ = seed_document(
        factory, prefix, status="processing", content_hash=old_digest, run_stage="parsing",
    )
    source_dir = Path(get_settings().documents_path) / doc_id
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / f"{doc_id}.txt").write_bytes(old_content)  # matches stored_filename suffix
    (source_dir / "original.txt").write_bytes(old_content)

    replaced = client.post(
        f"/documents/{doc_id}/replace",
        files={"file": (f"{prefix}-new.txt", f"noi dung MOI {prefix}".encode(), "text/plain")},
    )

    assert replaced.status_code == 409
    assert replaced.json()["error_code"] == "DOCUMENT_ALREADY_INDEXING"
    with factory() as session:
        document = session.get(Document, doc_id)
        # The hash never moved — before T3 it committed and then the enqueue
        # failure left database and index permanently disagreeing.
        assert document.content_hash == old_digest
        runs = list(session.scalars(select(IngestionRun).where(IngestionRun.document_id == doc_id)))
        assert len(runs) == 1  # no orphan second run either
    assert (source_dir / "original.txt").read_bytes() == old_content


def test_t3_successful_replace_commits_hash_and_run_together(client, mock_ollama, factory, debt_cleanup):
    prefix = debt_cleanup
    old_content = f"ban dau {prefix}".encode()
    doc_id, _, _ = seed_document(
        factory, prefix, status="indexed",
        content_hash=hashlib.sha256(old_content).hexdigest(),
    )
    source_dir = Path(get_settings().documents_path) / doc_id
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "original.txt").write_bytes(old_content)
    new_content = f"ban thay the {prefix}".encode()

    replaced = client.post(
        f"/documents/{doc_id}/replace",
        files={"file": (f"{prefix}-v2.txt", new_content, "text/plain")},
    )

    assert replaced.status_code == 202
    body = replaced.json()
    assert body["duplicate"] is False and body["ingestion_run_id"]
    with factory() as session:
        document = session.get(Document, doc_id)
        run = session.get(IngestionRun, str(body["ingestion_run_id"]))
        # Atomicity: the committed hash and its reindex run exist together.
        assert document.content_hash == hashlib.sha256(new_content).hexdigest()
        assert run is not None and run.document_id == doc_id
