"""Database safety is independent of local service availability."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.database_support import DISABLED_TEST_DATABASE_URL, configure_test_database, validate_postgres_test_url


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


@pytest.mark.parametrize("explicit", [None, ""])
def test_missing_integration_url_pins_a_dead_database_instead_of_runtime_configuration(explicit):
    environment = {"DATABASE_URL": "postgresql+psycopg://operator:private@localhost/production"}
    if explicit is not None:
        environment["POSTGRES_TEST_URL"] = explicit
    assert configure_test_database(environment) == DISABLED_TEST_DATABASE_URL
    assert environment["DATABASE_URL"] == DISABLED_TEST_DATABASE_URL
    assert environment.get("POSTGRES_TEST_URL") == explicit


def test_explicit_integration_url_wins_over_runtime_configuration():
    explicit = "postgresql+psycopg://test:test@127.0.0.1:1/isolated_test"
    environment = {"POSTGRES_TEST_URL": explicit, "DATABASE_URL": "postgresql+psycopg://operator:private@localhost/production"}
    assert configure_test_database(environment) == explicit
    assert environment["DATABASE_URL"] == explicit


@pytest.mark.parametrize("explicit", [None, "postgresql+psycopg://test:test@127.0.0.1:1/isolated_test"])
def test_conftest_pins_the_database_before_application_import_without_loading_settings(explicit):
    backend = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(backend)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["DATABASE_URL"] = "postgresql+psycopg://operator:private@localhost/production"
    if explicit is None:
        environment.pop("POSTGRES_TEST_URL", None)
    else:
        environment["POSTGRES_TEST_URL"] = explicit
    # Intercept before any application or Settings module can load. This tests
    # conftest ordering itself without reading .env or connecting to a service.
    probe = '''
import builtins, json, os, runpy
class ApplicationImportReached(Exception):
    pass
original = builtins.__import__
def intercept(name, *args, **kwargs):
    if name == "app.main":
        print(json.dumps({"database_url": os.environ["DATABASE_URL"]}))
        raise ApplicationImportReached
    return original(name, *args, **kwargs)
builtins.__import__ = intercept
try:
    runpy.run_path("tests/conftest.py")
except ApplicationImportReached:
    pass
else:
    raise AssertionError("application import was not reached")
'''
    completed = subprocess.run([sys.executable, "-B", "-c", probe], cwd=backend, env=environment,
                               check=True, capture_output=True, text=True)
    assert json.loads(completed.stdout)["database_url"] == (explicit or DISABLED_TEST_DATABASE_URL)
