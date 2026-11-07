"""Batched reads preserve version/run selection on a dedicated PostgreSQL test DB."""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, select
from sqlalchemy.engine import make_url

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Document, DocumentVersion, IngestionRun, ResearchAnnotation, ResearchPaper, ResearchProject
from app.postgres.repositories import PostgresDocumentRepository
from app.services.postgres_document_service import PostgresDocumentService, SourceUnavailableError
from app.services.research_service import ResearchService

URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL to an isolated database ending in _test")
NOW = datetime(2026, 11, 8, 0, 0, tzinfo=UTC)


@pytest.fixture
def database():
    assert (make_url(URL).database or "").endswith("_test")
    engine = create_postgres_engine(URL)
    sessions = create_session_factory(engine)
    prefix = "batch_" + uuid4().hex
    try:
        yield engine, sessions, prefix
    finally:
        with sessions.begin() as session:
            session.execute(delete(ResearchProject).where(ResearchProject.id.startswith(prefix)))
            session.execute(delete(Document).where(Document.id.startswith(prefix)))
        engine.dispose()


@contextmanager
def reads(engine):
    statements = []
    def before(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)
    event.listen(engine, "before_cursor_execute", before)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", before)


def seed(sessions, prefix, label, *, active=True, runs=(("first", NOW, 1),), status="indexed", offset=0):
    document_id = f"{prefix}_{label}"
    with sessions.begin() as session:
        document = Document(
            id=document_id, original_filename=label + ".pdf", stored_filename=label + ".pdf",
            status=status, source_available=True, created_at=NOW + timedelta(seconds=offset),
        )
        session.add(document)
        session.flush()
        versions = {}
        for number in {1, *(number for _, _, number in runs)}:
            version = DocumentVersion(
                id=f"{document_id}_v{number}", document_id=document_id, version_number=number,
                status="active" if active and number == 1 else "staging", chunking_config={},
            )
            session.add(version)
            versions[number] = version.id
        session.flush()
        if active:
            document.active_version_id = versions[1]
        for suffix, started_at, number in runs:
            session.add(IngestionRun(
                id=f"{document_id}_{suffix}", document_id=document_id, version_id=versions[number],
                started_at=started_at, status="completed", current_stage="completed",
                total_pages=8, total_chunks=12, embedded_chunks=12, progress_percent=100,
            ))
    return document_id


def test_latest_runs_preserves_timestamp_null_and_id_tie_ordering(database):
    engine, sessions, prefix = database
    dates = seed(sessions, prefix, "dates", runs=(("z_old", NOW, 1), ("a_new", NOW + timedelta(seconds=1), 2), ("zz_null", None, 2)))
    ties = seed(sessions, prefix, "ties", runs=(("a", NOW, 1), ("z", NOW, 2)))
    nulls = seed(sessions, prefix, "nulls", active=False, runs=(("a", None, 1), ("z", None, 2)))
    empty = seed(sessions, prefix, "empty", active=False, runs=())
    with sessions() as session:
        repo = PostgresDocumentRepository(session)
        with reads(engine) as queries:
            result = repo.latest_runs([dates, ties, nulls, empty, prefix + "_absent"])
        assert len(queries) == 1
        assert {key: row.id for key, row in result.items()} == {
            dates: dates + "_a_new", ties: ties + "_z", nulls: nulls + "_z",
        }
        assert all(result[doc_id].id == repo.latest_run(doc_id).id for doc_id in result)
        with reads(engine) as queries:
            assert repo.latest_runs([]) == {}
        assert queries == []


def test_document_listing_preserves_payload_and_uses_bounded_reads(database, tmp_path):
    engine, sessions, prefix = database
    active = seed(sessions, prefix, "active", runs=(("old", NOW, 1), ("new", NOW + timedelta(seconds=1), 2)), offset=1)
    staging = seed(sessions, prefix, "staging", active=False, runs=(("queued", None, 2),), status="uploaded", offset=2)
    empty = seed(sessions, prefix, "empty", active=False, runs=(), status="uploaded", offset=3)
    seed(sessions, prefix, "deleted", status="deleted", offset=4)
    service = PostgresDocumentService(sessions, None, None, None, None, tmp_path, 480, 80, None)
    with reads(engine) as queries:
        rows = service.list_documents()
    original_read_count = len(queries)
    rows = [row for row in rows if row["document_id"].startswith(prefix)]
    assert [row["document_id"] for row in rows] == [empty, staging, active]
    by_id = {row["document_id"]: row for row in rows}
    assert by_id[active]["active_index_version"] == 1
    assert by_id[active]["active_version_id"] == active + "_v1"
    assert by_id[active]["ingestion"]["version_id"] == active + "_v2"
    assert by_id[active]["ingestion"]["id"] == active + "_new"
    assert by_id[active]["chunks_count"] == 12 and by_id[active]["total_pages"] == 8
    assert by_id[staging]["active_index_version"] == 2 and by_id[staging]["active_version_id"] is None
    assert by_id[empty]["ingestion"] is None and by_id[empty]["active_index_version"] == 0
    assert original_read_count == 3
    for index in range(8):
        seed(sessions, prefix, f"extra{index}", offset=10 + index)
    with reads(engine) as queries:
        expanded = service.list_documents()
    assert len(queries) == original_read_count
    assert all(row in expanded for row in rows)


class NoSourceFiles:
    def source_file(self, document_id):
        raise SourceUnavailableError(document_id)


def test_paper_listing_keeps_input_order_page_counts_and_annotations(database):
    engine, sessions, prefix = database
    first = seed(sessions, prefix, "first")
    second = seed(sessions, prefix, "second", runs=(("latest", NOW, 2),))
    empty = seed(sessions, prefix, "empty", active=False, runs=(), status="uploaded")
    with sessions.begin() as session:
        project = ResearchProject(id=prefix + "_project", name="Batch listing")
        session.add(project)
        session.flush()
        paper_ids = []
        for index, doc_id in enumerate([second, empty, first]):
            paper_id = f"{prefix}_paper{index}"
            paper_ids.append(paper_id)
            session.add(ResearchPaper(id=paper_id, project_id=project.id, document_id=doc_id, short_name=str(index), title=str(index), tags=[]))
        session.flush()
        session.add(ResearchAnnotation(id=prefix + "_annotation", paper_id=paper_ids[0], page=1, color="yellow", quote="evidence", rects=[]))
    service = ResearchService(sessions, NoSourceFiles(), ollama_base_url="http://unused")
    with sessions() as session:
        papers = list(session.scalars(select(ResearchPaper).where(ResearchPaper.id.in_(paper_ids)).order_by(ResearchPaper.id)))
        with reads(engine) as queries:
            rows = service._paper_rows(session, papers)
        assert len(queries) == 3
        assert [row["document_id"] for row in rows] == [second, empty, first]
        assert [row["total_pages"] for row in rows] == [8, None, 8]
        assert [row["annotation_count"] for row in rows] == [1, 0, 0]
        assert [row["indexed"] for row in rows] == [True, False, True]
        assert [row["document_status"] for row in rows] == ["indexed", "uploaded", "indexed"]
        with reads(engine) as queries:
            assert service._paper_rows(session, []) == []
        assert queries == []
