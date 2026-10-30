"""The API must come up under the supervisor whatever resuming does. This path is off in every other
test, so a NameError in it took the API down on 31/10 and no test saw it (ticket 40)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import model_choice
from app.services.postgres_document_service import PostgresDocumentService


@pytest.mark.parametrize("resume", [lambda self: ["run-1"], lambda self: [], lambda self: (_ for _ in ()).throw(RuntimeError("database moved"))])
def test_the_api_starts_when_resuming_finds_work_nothing_or_fails(mock_ollama, monkeypatch, resume) -> None:
    monkeypatch.setenv(model_choice.SUPERVISED_ENV, "1")
    called = []

    def spy(self):
        called.append(True)
        return resume(self)

    monkeypatch.setattr(PostgresDocumentService, "resume_interrupted", spy)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
    assert called == [True]


def test_nothing_is_resumed_outside_the_supervisor(mock_ollama, monkeypatch) -> None:
    monkeypatch.delenv(model_choice.SUPERVISED_ENV, raising=False)
    monkeypatch.setattr(PostgresDocumentService, "resume_interrupted", lambda self: pytest.fail("resumed outside the supervisor"))
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
