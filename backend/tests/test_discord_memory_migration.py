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
NEW_TABLES = {
    "discord_memory_candidates",
    "discord_memories",
    "discord_memory_sources",
}


def _run_alembic(*arguments: str) -> subprocess.CompletedProcess[str]:
    assert URL is not None
    environment = os.environ.copy()
    environment["DATABASE_URL"] = URL
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def test_revision_16_upgrade_downgrade_reupgrade_isolated_database():
    assert URL is not None
    parsed = make_url(URL)
    assert parsed.database == "local_ai_core_test"
    assert parsed.database != "local_ai_core"
    engine = create_engine(URL, pool_pre_ping=True)
    legacy_columns_before = {
        column["name"] for column in inspect(engine).get_columns("memories")
    }
    try:
        _run_alembic("downgrade", "20260728_15")
        inspector = inspect(engine)
        assert NEW_TABLES.isdisjoint(inspector.get_table_names())
        assert {
            column["name"] for column in inspector.get_columns("memories")
        } == legacy_columns_before

        _run_alembic("upgrade", "20260728_16")
        inspector = inspect(engine)
        assert NEW_TABLES <= set(inspector.get_table_names())
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260728_16"
            )

        candidate_fks = {
            fk["name"] for fk in inspector.get_foreign_keys(
                "discord_memory_candidates"
            )
        }
        assert candidate_fks == {
            "fk_discord_memory_candidates_session",
            "fk_discord_memory_candidates_source_turn",
            "fk_discord_memory_candidates_target_memory",
        }
        memory_indexes = {
            index["name"]: index
            for index in inspector.get_indexes("discord_memories")
        }
        for name in (
            "uq_discord_memory_active_member",
            "uq_discord_memory_active_guild",
            "uq_discord_memory_active_channel",
            "uq_discord_memory_active_thread",
            "uq_discord_memory_member_version",
            "uq_discord_memory_guild_version",
            "uq_discord_memory_channel_version",
            "uq_discord_memory_thread_version",
        ):
            assert memory_indexes[name]["unique"] is True
            assert memory_indexes[name]["dialect_options"]["postgresql_where"]

        _run_alembic("downgrade", "20260728_15")
        inspector = inspect(engine)
        assert NEW_TABLES.isdisjoint(inspector.get_table_names())
        assert {
            column["name"] for column in inspector.get_columns("memories")
        } == legacy_columns_before
    finally:
        # Restore the head of the day, not the head this test was written
        # against, so a new revision does not strand the test database.
        _run_alembic("upgrade", "head")
    head = head_revision()
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == head
        )
    heads = _run_alembic("heads").stdout
    assert heads.count("(head)") == 1
    assert f"{head} (head)" in heads
