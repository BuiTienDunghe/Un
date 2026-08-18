"""Up/down/up coverage for revision 20260818_21 (P0-6).

Follows the shape of the other migration tests: the isolated test database is
walked backwards, inspected, and restored to head in `finally` — restoring to
`head`, never to a pinned revision, so a later migration cannot strand it.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

from tests.migration_support import head_revision

ROOT = Path(__file__).resolve().parents[2]
URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")

CREATED_INDEXES = {
    "document_chunks": {"ix_document_chunks_document_id"},
    "document_pages": {"ix_document_pages_document_id", "ix_document_pages_version_id"},
    "document_versions": {"ix_document_versions_document_id", "ix_document_versions_status"},
    "ingestion_runs": {"ix_ingestion_runs_document_id", "ix_ingestion_runs_status", "ix_ingestion_runs_version_id"},
    "jobs": {"ix_jobs_document_id", "ix_jobs_ingestion_run_id", "ix_jobs_job_type", "ix_jobs_version_id"},
    "outbox_events": {"ix_outbox_events_status"},
}


def _alembic(*args: str) -> None:
    assert URL is not None
    environment = os.environ.copy()
    environment["DATABASE_URL"] = URL
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def _index_names(engine, table: str) -> set[str]:
    return {item["name"] for item in inspect(engine).get_indexes(table)}


def _idempotency_key_is_nullable(engine) -> bool:
    column = next(item for item in inspect(engine).get_columns("outbox_events") if item["name"] == "idempotency_key")
    return bool(column["nullable"])


def test_revision_21_creates_indexes_and_tightens_the_outbox_key_reversibly():
    assert URL is not None
    assert make_url(URL).database == "local_ai_core_test"
    engine = create_engine(URL, pool_pre_ping=True)
    try:
        for table, names in CREATED_INDEXES.items():
            assert names <= _index_names(engine, table)
        assert not _idempotency_key_is_nullable(engine)

        _alembic("downgrade", "20260818_20")
        for table, names in CREATED_INDEXES.items():
            assert not (names & _index_names(engine, table))
        # The dedup key goes back to nullable; the backfilled values stay,
        # because a downgrade restores schema and never destroys data.
        assert _idempotency_key_is_nullable(engine)
    finally:
        _alembic("upgrade", "head")

    for table, names in CREATED_INDEXES.items():
        assert names <= _index_names(engine, table)
    assert not _idempotency_key_is_nullable(engine)
    assert head_revision() == "20260818_21"


def test_the_two_undeclared_indexes_are_kept_rather_than_dropped():
    assert URL is not None
    engine = create_engine(URL, pool_pre_ping=True)

    # Autogenerate wanted to drop both. They predate the models that forgot to
    # declare them, and dropping a live index is a production change.
    assert "ix_documents_cleanup_status" in _index_names(engine, "documents")
    assert "ix_jobs_status_available" in _index_names(engine, "jobs")
