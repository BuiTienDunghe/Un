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


def _checks(engine) -> dict[str, str]:
    return {
        item["name"]: item["sqltext"]
        for item in inspect(engine).get_check_constraints(
            "discord_memory_candidates"
        )
    }


def test_revision_18_upgrade_downgrade_reupgrade_isolated_database():
    assert URL is not None
    database = make_url(URL).database
    assert database == "local_ai_core_test"
    assert database != "local_ai_core"
    engine = create_engine(URL, pool_pre_ping=True)
    try:
        _alembic("downgrade", "20260728_17")
        checks = _checks(engine)
        assert "rejected_policy" not in checks[
            "ck_discord_memory_candidates_filter_decision"
        ]
        assert "not_required" not in checks[
            "ck_discord_memory_candidates_validation_status"
        ]
        assert "ck_discord_memory_candidates_filter_reason_code" not in checks

        _alembic("upgrade", "20260728_18")
        checks = _checks(engine)
        assert "rejected_policy" in checks[
            "ck_discord_memory_candidates_filter_decision"
        ]
        assert "not_required" in checks[
            "ck_discord_memory_candidates_validation_status"
        ]
        assert "explicit_remember" in checks[
            "ck_discord_memory_candidates_filter_reason_code"
        ]

        _alembic("downgrade", "20260728_17")
        checks = _checks(engine)
        assert "rejected_policy" not in checks[
            "ck_discord_memory_candidates_filter_decision"
        ]
        assert "ck_discord_memory_candidates_filter_reason_code" not in checks
    finally:
        # Restore the head of the day, not the head this test was written
        # against, so a new revision does not strand the test database.
        _alembic("upgrade", "head")
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT version_num FROM alembic_version")
        ) == head_revision()
