"""Ticket 40: a run a restart cut off goes on by itself, keeping the pages an OCR run produced."""
from __future__ import annotations

import os
import time
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Document, DocumentPage, IngestionRun
from app.postgres.repositories import PostgresDocumentRepository
from app.services.postgres_document_service import PostgresDocumentService

URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")


def make_run(factory, mime: str = "text/markdown", method: str = "ocr") -> tuple[str, str, str]:
    document_id = f"doc_{uuid4().hex}"
    with factory.begin() as session:
        repo = PostgresDocumentRepository(session)
        _document, version, run = repo.create_upload(document_id, "a.md", f"{document_id}.md", mime, 10, uuid4().hex)
        session.flush()
        ids = (document_id, version.id, run.id)
        repo.set_stage(run.id, "parsing")
        repo.replace_pages(document_id, version.id, [(1, "trang một", method), (2, "trang hai", method)])
        repo.set_stage(run.id, "chunking")
        repo.set_stage(run.id, "embedding")
    return ids


def service(factory) -> tuple[PostgresDocumentService, list]:
    started: list = []
    instance = PostgresDocumentService.__new__(PostgresDocumentService)
    instance.sessions, instance.job_queue, instance.job_max_attempts = factory, None, 3
    instance._run_index = lambda *args: started.append(args)
    return instance, started


@pytest.fixture
def factory():
    return create_session_factory(create_postgres_engine(str(URL)))


def test_a_cut_run_from_ocr_resumes_on_its_stored_pages(factory) -> None:
    document_id, version_id, run_id = make_run(factory)
    instance, started = service(factory)
    try:
        assert instance.indexing_in_progress() is True
        assert run_id in instance.resume_interrupted()
        time.sleep(0.2)
        # The database is shared with the suite: other tests may have left runs of their own.
        assert [item for item in started if item[0] == run_id] == [(run_id, document_id, version_id, [(1, "trang một", "ocr"), (2, "trang hai", "ocr")])]
        with factory() as session:
            run = session.get(IngestionRun, run_id)
            assert run.status == "queued" and run.attempt == 2 and run.error_code is None
            assert session.get(Document, document_id).status == "processing"
    finally:
        with factory.begin() as session:
            session.execute(delete(DocumentPage).where(DocumentPage.document_id == document_id))
            session.execute(delete(Document).where(Document.id == document_id))


def test_an_ordinary_upload_is_parsed_again_from_its_source(factory) -> None:
    document_id, version_id, run_id = make_run(factory, "application/pdf", "native")
    instance, started = service(factory)
    try:
        instance.resume_interrupted()
        time.sleep(0.2)
        assert [item for item in started if item[0] == run_id] == [(run_id, document_id, version_id, None)]
    finally:
        with factory.begin() as session:
            session.execute(delete(Document).where(Document.id == document_id))


def test_rq_mode_has_workers_of_its_own_and_touches_nothing(factory) -> None:
    instance, started = service(factory)
    instance.job_queue = object()
    assert instance.resume_interrupted() == [] and started == []
