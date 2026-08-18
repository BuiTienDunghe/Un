from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from tests.migration_support import head_revision


ROOT = Path(__file__).resolve().parents[2]
URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")


def _alembic(*args: str) -> None:
    assert URL is not None
    environment = os.environ.copy()
    environment["DATABASE_URL"] = URL
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def _filter_check(engine) -> str:
    checks = {
        item["name"]: item["sqltext"]
        for item in inspect(engine).get_check_constraints(
            "discord_memory_candidates"
        )
    }
    return checks["ck_discord_memory_candidates_filter_decision"]


def test_revision_17_adds_and_reverses_not_run_vocabulary():
    assert URL is not None
    assert make_url(URL).database == "local_ai_core_test"
    engine = create_engine(URL, pool_pre_ping=True)
    try:
        _alembic("downgrade", "20260728_16")
        assert "not_run" not in _filter_check(engine)
        _alembic("upgrade", "20260728_17")
        assert "not_run" in _filter_check(engine)
        _alembic("downgrade", "20260728_16")
        assert "not_run" not in _filter_check(engine)
    finally:
        # Restore the head of the day, not the head this test was written
        # against, so a new revision does not strand the test database.
        _alembic("upgrade", "head")
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == head_revision()
        )
