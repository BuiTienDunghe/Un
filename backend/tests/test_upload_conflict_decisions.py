from __future__ import annotations

import asyncio
import io
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import UploadFile
from sqlalchemy import delete

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Document
from app.services.postgres_document_service import PostgresDocumentService


POSTGRES_URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="set POSTGRES_TEST_URL to run PostgreSQL integration tests")


class _Log:
    def log_request(self, *args: object, **kwargs: object) -> None: pass


class _Ocr:
    # SmartParser reads the OCR slot from the router while it is constructed.
    # This test only uploads .txt files, so an empty model map is the honest
    # stub: no OCR slot is configured and no OCR path can be taken.
    router = SimpleNamespace(models={})


def _file(name: str, content: bytes) -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(content), headers={"content-type": "text/plain"})


@pytest.fixture
def service(tmp_path: Path):
    factory = create_session_factory(create_postgres_engine(str(POSTGRES_URL)))
    value = PostgresDocumentService(factory, object(), object(), object(), _Log(), tmp_path / "documents", 64, 8, _Ocr(), job_queue=object())
    yield value, factory
    with factory.begin() as session:
        session.execute(delete(Document).where(Document.original_filename.like("upload-decision-%")))


def test_upload_conflict_decisions(service):
    value, factory = service
    first = asyncio.run(value.upload(_file("upload-decision-original.txt", b"one"), 1024))
    assert first["duplicate"] is False

    same = asyncio.run(value.upload(_file("upload-decision-original.txt", b"one"), 1024))
    assert same["action_required"] is True
    assert same["conflict"] == "same_name_same_hash"
    assert asyncio.run(value.upload(_file("upload-decision-original.txt", b"one"), 1024, decision="use_existing"))["document_id"] == first["document_id"]

    renamed = asyncio.run(value.upload(_file("upload-decision-renamed.txt", b"one"), 1024))
    assert renamed["conflict"] == "new_name_existing_hash"
    accepted = asyncio.run(value.upload(_file("upload-decision-renamed.txt", b"one"), 1024, decision="rename"))
    assert accepted["renamed"] is True

    keep_both = asyncio.run(value.upload(_file("upload-decision-renamed.txt", b"two"), 1024))
    assert keep_both["conflict"] == "same_name_different_hash"
    assert keep_both["suggested_filename"] == "upload-decision-renamed (2).txt"
    kept = asyncio.run(value.upload(_file("upload-decision-renamed.txt", b"two"), 1024, decision="keep_both"))
    assert kept["filename"] == "upload-decision-renamed (2).txt"

    replacement = asyncio.run(value.upload(_file("upload-decision-renamed.txt", b"three"), 1024))
    assert replacement["conflict"] == "same_name_different_hash"
    replaced = asyncio.run(value.upload(_file("upload-decision-renamed.txt", b"three"), 1024, decision="replace"))
    assert replaced["run_id"] and replaced["version_id"]
    with factory() as session:
        document = session.get(Document, first["document_id"])
        assert document and document.original_filename == "upload-decision-renamed.txt"
        assert document.content_hash == replaced["content_hash"]
        assert session.get(Document, kept["document_id"]).original_filename == "upload-decision-renamed (2).txt"
