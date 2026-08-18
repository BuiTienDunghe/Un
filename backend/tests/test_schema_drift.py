"""The local half of the schema regression gate (P0-6).

CI runs `alembic check` on every commit, but a developer running the suite
locally should see the drift immediately rather than discovering it on a pull
request. A model that grows an index, changes nullability or gains a constraint
without a matching migration fails here.
"""
from __future__ import annotations

import os

import pytest
from alembic.autogenerate import produce_migrations
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app.postgres.models import Base

URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")


def test_the_models_and_the_migrated_schema_agree():
    engine = create_engine(str(URL), pool_pre_ping=True)
    with engine.connect() as connection:
        differences = produce_migrations(MigrationContext.configure(connection), Base.metadata)

    operations = differences.upgrade_ops
    assert operations is not None
    # The rendered op list is the useful failure message: it names exactly what
    # the models declare that the database does not have, or the reverse.
    assert operations.is_empty(), f"models and migrations disagree: {operations.as_diffs()}"
