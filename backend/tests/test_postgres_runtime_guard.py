from __future__ import annotations

import builtins
import inspect

import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings, get_settings
from app.main import app
from app.services.postgres_retrieval_service import PostgresRetrievalService


def test_runtime_requires_postgres_url_and_rejects_sqlite_url():
    with pytest.raises(ValueError, match="DATABASE_URL is required"):
        Settings(database_url=None)
    with pytest.raises(ValueError, match="PostgreSQL"):
        Settings(database_url="sqlite:///forbidden.db")


def test_fastapi_runtime_does_not_import_sqlite_store(monkeypatch):
    url = __import__("os").getenv("POSTGRES_TEST_URL")
    if not url:
        pytest.skip("set POSTGRES_TEST_URL")
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name in {"sqlite3", "app.stores.sqlite_store"}:
            raise AssertionError(f"runtime attempted SQLite import: {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            assert isinstance(client.app.state.rag_service.retrieval_service, PostgresRetrievalService)
            assert client.get("/health").status_code == 200
    finally:
        get_settings.cache_clear()


def test_worker_and_dispatcher_runtime_modules_have_no_sqlite_dependency():
    from app.workers import tasks
    from scripts import cleanup_worker, outbox_dispatcher

    for module in (tasks, cleanup_worker, outbox_dispatcher):
        source = inspect.getsource(module).lower()
        assert "sqlite_store" not in source
        assert "import sqlite3" not in source
