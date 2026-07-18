from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Document, DocumentChunk, DocumentVersion, IngestionRun, Job, OcrRun, RequestLog
from app.services.postgres_cleanup_planner import PostgresCleanupPlanner


POSTGRES_URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="set POSTGRES_TEST_URL to run PostgreSQL integration tests")


@pytest.fixture
def planner(tmp_path: Path):
    factory = create_session_factory(create_postgres_engine(str(POSTGRES_URL)))
    prefix = f"cleanup-plan-{uuid4().hex}"
    value = PostgresCleanupPlanner(factory, tmp_path / "documents", tmp_path / "ocr-runs", superseded_grace_days=7, temporary_sources_ttl_days=30, logs_ttl_days=90, ocr_runs_ttl_days=14)
    try:
        yield value, factory, prefix
    finally:
        with factory.begin() as session:
            session.execute(delete(Document).where(Document.original_filename.like(f"{prefix}%")))
            session.execute(delete(OcrRun).where(OcrRun.filename.like(f"{prefix}%")))
            session.execute(delete(RequestLog).where(RequestLog.endpoint.like(f"/{prefix}%")))


def _seed(factory, prefix: str, *, status="uploaded", version_status="staging", superseded_at=None, pinned=False, source_available=True, temporary=False, busy=False):
    doc_id, version_id, run_id = f"doc_{uuid4().hex}", f"ver_{uuid4().hex}", f"ing_{uuid4().hex}"
    now = datetime.now(UTC)
    with factory.begin() as session:
        doc = Document(id=doc_id, original_filename=f"{prefix}-{doc_id}.txt", stored_filename=f"{doc_id}.txt", mime_type="text/plain", content_hash=uuid4().hex * 2, status=status, source_available=source_available, pinned=pinned, retention_policy="temporary" if temporary else "permanent", created_at=now - timedelta(days=60), last_accessed_at=now - timedelta(days=60))
        version = DocumentVersion(id=version_id, document_id=doc_id, version_number=1, status=version_status, superseded_at=superseded_at)
        if version_status == "active": doc.active_version_id = version_id
        run = IngestionRun(id=run_id, document_id=doc_id, version_id=version_id, status="completed", current_stage="completed")
        session.add_all((doc, version, run))
        session.flush()
        session.add(DocumentChunk(id=f"chunk_{uuid4().hex}", chunk_uid=f"uid_{uuid4().hex}", document_id=doc_id, version_id=version_id, chunk_index=0, content="cleanup fixture", content_hash="a" * 64, status="active" if version_status == "active" else "staging"))
        if busy:
            session.add(Job(id=f"job_{uuid4().hex}", job_type="index_document", document_id=doc_id, version_id=version_id, ingestion_run_id=run_id, status="running", idempotency_key=f"busy:{uuid4().hex}"))
    return doc_id, version_id, run_id


def test_dry_run_planning_has_zero_side_effects(planner):
    service, factory, prefix = planner
    doc_id, version_id, _ = _seed(factory, prefix, version_status="superseded", superseded_at=datetime.now(UTC) - timedelta(days=8))
    with factory() as session:
        before = (session.get(Document, doc_id).status, session.get(DocumentVersion, version_id).status, len(list(session.scalars(select(DocumentChunk).where(DocumentChunk.version_id == version_id)))))
    plan = service.plan(domain="versions", as_of=datetime.now(UTC))
    assert any(item.version_id == version_id and not item.blocking_guards for item in plan)
    with factory() as session:
        after = (session.get(Document, doc_id).status, session.get(DocumentVersion, version_id).status, len(list(session.scalars(select(DocumentChunk).where(DocumentChunk.version_id == version_id)))))
    assert before == after


def test_active_pinned_and_busy_versions_are_excluded_by_guards(planner):
    service, factory, prefix = planner
    active_doc, active_version, _ = _seed(factory, prefix, status="indexed", version_status="active", temporary=True)
    pinned_doc, pinned_version, _ = _seed(factory, prefix, version_status="superseded", superseded_at=datetime.now(UTC) - timedelta(days=8), pinned=True)
    busy_doc, busy_version, _ = _seed(factory, prefix, version_status="superseded", superseded_at=datetime.now(UTC) - timedelta(days=8), busy=True)
    plan = service.plan(as_of=datetime.now(UTC))
    by_id = {item.entity_id: item for item in plan}
    assert "has_active_version" in by_id[active_doc].blocking_guards
    assert "pinned_document" in by_id[pinned_version].blocking_guards
    assert "has_busy_job" in by_id[busy_version].blocking_guards


def test_superseded_grace_and_source_less_guards(planner):
    service, factory, prefix = planner
    old_doc, old_version, _ = _seed(factory, prefix, version_status="superseded", superseded_at=datetime.now(UTC) - timedelta(days=8))
    young_doc, young_version, _ = _seed(factory, prefix, version_status="superseded", superseded_at=datetime.now(UTC) - timedelta(days=2))
    source_less, _, _ = _seed(factory, prefix, source_available=False, temporary=True)
    plan = service.plan(as_of=datetime.now(UTC))
    by_id = {item.entity_id: item for item in plan}
    assert by_id[old_version].blocking_guards == []
    assert "grace_period_not_elapsed" in by_id[young_version].blocking_guards
    assert source_less not in by_id


def test_postgres_log_and_ocr_retention_candidates(planner):
    service, factory, prefix = planner
    old = datetime.now(UTC) - timedelta(days=100)
    with factory.begin() as session:
        session.add(RequestLog(endpoint=f"/{prefix}/old", latency_ms=1, status="ok", created_at=old))
        session.add(OcrRun(id=f"ocr-{uuid4().hex}", filename=f"{prefix}-old.pdf", status="completed", model="test", result_json={}, created_at=old, updated_at=old))
    plan = service.plan(domain="all", as_of=datetime.now(UTC))
    assert any(item.operation_type == "delete_request_log" and not item.blocking_guards for item in plan)
    assert any(item.operation_type == "delete_ocr_run" and not item.blocking_guards for item in plan)


def test_legacy_qdrant_is_not_a_cleanup_domain(planner):
    service, _, _ = planner
    with pytest.raises(ValueError, match="unsupported cleanup domain"):
        service.plan(domain="legacy-qdrant")


def test_cleanup_dry_run_worker_has_no_sqlite_dependency():
    import scripts.cleanup_worker as worker
    assert "SQLiteStore" not in vars(worker)
