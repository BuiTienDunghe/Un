from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.postgres.database import create_postgres_engine
from app.postgres.models import Base


ROOT = Path(__file__).resolve().parents[2]


def test_postgres_foundation_declares_required_tables() -> None:
    assert {
        "documents",
        "document_versions",
        "ingestion_runs",
        "document_pages",
        "document_chunks",
        "jobs",
        "outbox_events",
    }.issubset(Base.metadata.tables)


def test_postgres_engine_rejects_non_postgres_url() -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        create_postgres_engine("sqlite:///not-postgres.db")


def test_alembic_can_render_postgres_sql_without_database_url() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head", "--sql"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "CREATE TABLE documents" in result.stdout
    assert "CREATE TABLE outbox_events" in result.stdout
