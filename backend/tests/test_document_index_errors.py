"""Index HTTP errors on a bare app: no database, worker, model, or lifespan."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.exc import OperationalError

from app.main import http_error_handler
from app.routers import documents
from app.services.postgres_document_service import DocumentAlreadyIndexingError, DocumentNotFoundError, SourceUnavailableError
from app.stores.qdrant_store import QdrantDimensionMismatchError


class IndexService:
    def __init__(self):
        self.calls = []
        self.error = None
        self.result = {
            "id": "run_1", "index_version": 2, "version_id": "version_2",
            "job_id": "job_1", "status": "queued", "stage": "queued",
        }

    def enqueue_index(self, document_id):
        self.calls.append(document_id)
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def index_client():
    app = FastAPI()
    app.state.settings = SimpleNamespace(local_ai_api_key="index-test-key", local_ai_auth_enabled=False)
    service = IndexService()
    app.state.document_service = service
    app.add_exception_handler(HTTPException, http_error_handler)
    app.include_router(documents.router)
    with TestClient(app) as client:
        yield client, service


@pytest.fixture
def error_records():
    records = []
    sink = documents.logger.add(
        lambda message: records.append(message.record), level="ERROR",
        filter=lambda record: record["extra"].get("event") == "document_index_request_failed",
    )
    try:
        yield records
    finally:
        documents.logger.remove(sink)


def post_index(client, **overrides):
    return client.post("/documents/index", json={"document_id": "doc_1", **overrides}, headers={"X-API-Key": "index-test-key"})


def test_index_success_keeps_accepted_payload(index_client):
    client, service = index_client
    response = post_index(client)
    assert response.status_code == 202
    assert response.json() == {
        "document_id": "doc_1", "ingestion_run_id": "run_1", "index_version": 2,
        "version_id": "version_2", "job_id": "job_1", "status": "queued", "stage": "queued",
    }
    assert service.calls == ["doc_1"]


@pytest.mark.parametrize("error,status,code", [
    (DocumentNotFoundError("doc_1"), 404, "DOCUMENT_NOT_FOUND"),
    (DocumentAlreadyIndexingError("doc_1"), 409, "DOCUMENT_ALREADY_INDEXING"),
    (SourceUnavailableError("doc_1"), 409, "SOURCE_UNAVAILABLE"),
    (QdrantDimensionMismatchError("expected dimensions differ"), 422, "VECTOR_DIMENSION_MISMATCH"),
])
def test_expected_index_errors_keep_existing_contract(index_client, error_records, error, status, code):
    client, service = index_client
    service.error = error
    response = post_index(client)
    assert response.status_code == status
    assert response.json()["error_code"] == code
    assert error_records == []


@pytest.mark.parametrize("error", [
    RuntimeError("private internal state"),
    ValueError("private invalid server configuration"),
    OperationalError("SELECT private_data", {}, RuntimeError("private database connection details")),
])
def test_unexpected_index_errors_are_server_errors_with_a_logged_receipt(index_client, error_records, error):
    client, service = index_client
    service.error = error
    response = post_index(client)
    assert response.status_code == 500
    body = response.json()
    assert body["error_code"] == "DOCUMENT_INDEX_REQUEST_FAILED"
    assert "private" not in response.text
    error_id = body["detail"]["error_id"]
    assert UUID(hex=error_id).hex == error_id
    assert len(error_records) == 1
    record = error_records[0]
    assert record["extra"]["error_id"] == error_id
    assert record["extra"]["document_id"] == "doc_1"
    assert record["exception"].value is error
    assert service.calls == ["doc_1"]


@pytest.mark.parametrize("result", [
    {"id": "run_already_queued"},
    {"id": "run_already_queued", "index_version": "private bad version", "status": "queued", "stage": "queued"},
])
def test_bad_service_response_is_not_reported_as_bad_document(index_client, error_records, result):
    client, service = index_client
    service.result = result
    response = post_index(client)
    assert response.status_code == 500
    assert response.json()["error_code"] == "DOCUMENT_INDEX_REQUEST_FAILED"
    assert "Kiểm tra trạng thái" in response.json()["message"]
    assert "private" not in response.text
    assert len(error_records) == 1
    assert service.calls == ["doc_1"]


def test_index_auth_still_blocks_before_service_is_called(index_client):
    client, service = index_client
    response = client.post("/documents/index", json={"document_id": "doc_1"})
    assert response.status_code == 401
    assert response.json()["error_code"] == "API_KEY_REQUIRED"
    assert service.calls == []


def test_invalid_document_id_is_still_a_client_validation_error(index_client, error_records):
    client, service = index_client
    response = post_index(client, document_id="")
    assert response.status_code == 422
    assert service.calls == []
    assert error_records == []
