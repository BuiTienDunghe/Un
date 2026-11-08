"""Database safety is independent of local service availability."""
from __future__ import annotations

import pytest

from tests.database_support import validate_postgres_test_url


@pytest.mark.parametrize("url", [
    "postgresql+psycopg://test:password@localhost/local_ai_core_test",
    "postgresql+psycopg://test:password@127.0.0.1:65432/backend_audit_test",
    "postgresql+psycopg2://test:password@localhost/branch_123_test?connect_timeout=2",
])
def test_explicit_test_database_urls_are_preserved(url):
    assert validate_postgres_test_url(url) == url


@pytest.mark.parametrize("url", [
    None,
    "",
    "not a database URL",
    "sqlite:///local_ai_core_test",
    "mysql+pymysql://test:password@localhost/local_ai_core_test",
    "postgresql://test:password@localhost/local_ai_core_test",
    "postgresql+psycopg://test:password@localhost/local_ai_core",
    "postgresql+psycopg://test:password@localhost/",
    "postgresql+psycopg://test:password@localhost/_test",
    "postgresql+psycopg://test:password@localhost/local_ai_core_test_backup",
    "postgresql+psycopg://test:password@localhost:not-a-port/local_ai_core_test",
    "postgresql+psycopg://test:password@localhost/local_ai_core_test?dbname=local_ai_core",
    "postgresql+psycopg://test:password@localhost/local_ai_core_test?database=local_ai_core",
    "postgresql+psycopg://test:password@localhost/local_ai_core_test?service=production",
    "postgresql+psycopg://test:password@localhost/local_ai_core_test?servicefile=production.conf",
])
def test_unsafe_or_missing_test_database_urls_are_rejected_without_credentials(url):
    with pytest.raises(ValueError) as error:
        validate_postgres_test_url(url)
    assert "password" not in str(error.value)


def test_validation_never_falls_back_to_the_runtime_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test:password@localhost/local_ai_core_test")
    with pytest.raises(ValueError, match="explicitly set"):
        validate_postgres_test_url(None)
