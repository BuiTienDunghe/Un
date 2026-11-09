"""One explicit PostgreSQL test-database contract, checked before any connection.

The name guard cannot prove isolation: operators must still supply a dedicated
database. The validator refuses unsafe explicit URLs; configure_test_database()
also pins DATABASE_URL to a dead endpoint when no integration URL is supplied.
"""
from __future__ import annotations

from collections.abc import MutableMapping

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

DISABLED_TEST_DATABASE_URL = "postgresql+psycopg://test:test@127.0.0.1:1/unconfigured_test"


def configure_test_database(environment: MutableMapping[str, str]) -> str:
    """Isolate app imports from the operator's DATABASE_URL and project .env."""
    explicit = environment.get("POSTGRES_TEST_URL")
    selected = validate_postgres_test_url(explicit) if explicit else DISABLED_TEST_DATABASE_URL
    environment["DATABASE_URL"] = selected
    return selected


def validate_postgres_test_url(value: str | None) -> str:
    """Return the unchanged explicit URL or refuse it without exposing credentials."""
    if not value:
        raise ValueError("POSTGRES_TEST_URL must be explicitly set for database tests")
    try:
        parsed = make_url(value)
    except (ArgumentError, TypeError, ValueError):
        raise ValueError("POSTGRES_TEST_URL must be a valid PostgreSQL SQLAlchemy URL") from None
    if not parsed.drivername.startswith("postgresql+"):
        raise ValueError("POSTGRES_TEST_URL must use an explicit postgresql+ driver")
    database = parsed.database or ""
    if database == "_test" or not database.endswith("_test"):
        raise ValueError("POSTGRES_TEST_URL must name a dedicated database ending in _test")
    if {key.lower() for key in parsed.query} & {"dbname", "database", "service", "servicefile"}:
        raise ValueError("POSTGRES_TEST_URL must not override its database through query parameters")
    return value
