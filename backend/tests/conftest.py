import os
from pathlib import Path
from uuid import uuid4

os.environ["LOG_DIR"] = str(Path(__file__).parent / "test_logs")
# Settings reads the project .env, so an operator who configures a real API key
# would otherwise make every write-endpoint test 401 on their machine but not in
# CI. The auth tests set the key explicitly on app.state instead.
os.environ["LOCAL_AI_API_KEY"] = ""
os.environ["LOCAL_AI_PROTECT_READS"] = "false"
if os.getenv("POSTGRES_TEST_URL"):
    # Normal API tests use the isolated PostgreSQL database, never a local
    # SQLite file or the runtime PostgreSQL database.
    os.environ["DATABASE_URL"] = os.environ["POSTGRES_TEST_URL"]

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from rq import Queue
from sqlalchemy import delete
from sqlalchemy.engine import make_url

from app.main import app
from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Document


def _integration_database_url() -> str:
    """Return an explicitly isolated PostgreSQL database for worker tests."""
    url = os.getenv("POSTGRES_TEST_URL")
    if not url:
        pytest.skip("set POSTGRES_TEST_URL to run worker integration tests")
    database = make_url(url).database or ""
    if not database.endswith("_test"):
        pytest.skip("POSTGRES_TEST_URL must target a database ending in _test")
    return url


@pytest.fixture
def worker_integration_resources():
    """Isolated real PostgreSQL/Redis/RQ resources for one worker test.

    Redis database 15 is reserved for tests and every test receives its own
    queue namespace.  PostgreSQL records are removed by their unique filename
    prefix, so the development database is never touched.
    """
    database_url = _integration_database_url()
    redis_url = os.getenv("REDIS_TEST_URL", "redis://127.0.0.1:6379/15")
    prefix = f"local-ai:test:{uuid4().hex}"
    factory = create_session_factory(create_postgres_engine(database_url))
    redis = Redis.from_url(redis_url)
    try:
        redis.ping()
    except Exception as error:
        pytest.skip(f"Redis test instance is unavailable: {error}")

    try:
        yield {
            "database_url": database_url,
            "factory": factory,
            "redis": redis,
            "redis_url": redis_url,
            "prefix": prefix,
            "ocr_queue": Queue(f"{prefix}:ocr", connection=redis),
            "index_queue": Queue(f"{prefix}:index", connection=redis),
            "filename_prefix": f"worker-integration-{uuid4().hex}",
        }
    finally:
        # Queue.empty also clears queued IDs; deleting the namespace keys clears
        # RQ registries and result metadata created by the worker.
        for key in redis.scan_iter(match=f"rq:*{prefix}*"):
            redis.delete(key)
        with factory.begin() as session:
            session.execute(delete(Document).where(Document.original_filename.like("worker-integration-%")))


@pytest.fixture
def client():
    database_url = _integration_database_url()
    factory = create_session_factory(create_postgres_engine(database_url))
    with factory.begin() as session:
        session.execute(delete(Document))
    with TestClient(app) as test_client:
        yield test_client
    with factory.begin() as session:
        session.execute(delete(Document))


@pytest.fixture
def mock_ollama(monkeypatch):
    def fake_chat(self, model, messages, options, keep_alive, think=None):
        return f"Mock response from {model}"

    monkeypatch.setattr("app.llm_clients.ollama_client.OllamaClient.chat", fake_chat)
    monkeypatch.setattr("app.llm_clients.ollama_client.OllamaClient.embed", lambda self, model, text: [0.1, 0.2, 0.3])
    monkeypatch.setattr("app.llm_clients.ollama_client.OllamaClient.healthcheck", lambda self: True)
