"""One explicit PostgreSQL test-database contract, checked before any connection.

The name guard cannot prove isolation: operators must still supply a dedicated
database. It prevents the normal suite from falling back to DATABASE_URL/.env
or accepting a production name, including libpq query overrides of that name.
"""
from __future__ import annotations

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


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
