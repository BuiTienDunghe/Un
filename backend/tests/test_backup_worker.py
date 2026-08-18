from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.services.operational_service import OperationalService
from scripts.backup_postgres import create_backup, list_backups, rotate_backups


def _dump(directory: Path, name: str, age_days: float = 0.0) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(b"PGDMP fake")
    stamp = time.time() - age_days * 86400
    os.utime(path, (stamp, stamp))
    return path


def test_list_backups_is_newest_first_and_ignores_other_files(tmp_path: Path):
    _dump(tmp_path, "local-ai-20260101-000000.dump", age_days=9)
    newest = _dump(tmp_path, "local-ai-20260110-000000.dump", age_days=1)
    (tmp_path / "notes.txt").write_text("not a backup", encoding="utf-8")

    found = list_backups(tmp_path)

    assert [item.name for item in found][0] == newest.name
    assert len(found) == 2


def test_rotation_never_drops_below_the_minimum_even_when_everything_is_old(tmp_path: Path):
    for day in range(5):
        _dump(tmp_path, f"local-ai-2026010{day}-000000.dump", age_days=90 + day)

    removed = rotate_backups(tmp_path, retention_days=14, keep_minimum=3)

    # An installation left idle past the retention window must still own
    # recovery points; retention is a storage policy, not a delete-everything.
    assert len(removed) == 2
    assert len(list_backups(tmp_path)) == 3


def test_rotation_keeps_everything_inside_the_window(tmp_path: Path):
    _dump(tmp_path, "local-ai-20260110-000000.dump", age_days=1)
    _dump(tmp_path, "local-ai-20260109-000000.dump", age_days=2)
    _dump(tmp_path, "local-ai-20260108-000000.dump", age_days=3)
    _dump(tmp_path, "local-ai-20251201-000000.dump", age_days=60)

    removed = rotate_backups(tmp_path, retention_days=14, keep_minimum=3)

    assert [item.name for item in removed] == ["local-ai-20251201-000000.dump"]


def test_rotation_is_disabled_when_retention_is_zero(tmp_path: Path):
    _dump(tmp_path, "local-ai-20250101-000000.dump", age_days=400)

    assert rotate_backups(tmp_path, retention_days=0, keep_minimum=1) == []
    assert len(list_backups(tmp_path)) == 1


def test_an_explicit_docker_service_wins_over_host_pg_dump(tmp_path: Path, monkeypatch):
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        handle = kwargs.get("stdout")
        if handle is not None:
            handle.write(b"PGDMP fake")
        return None


    monkeypatch.setattr("scripts.backup_postgres.shutil.which", lambda name: "/usr/bin/pg_dump")
    monkeypatch.setattr("scripts.backup_postgres.subprocess.run", fake_run)

    created = create_backup("postgresql+psycopg://u:p@127.0.0.1:5432/db", tmp_path, docker_service="postgres")

    # The container's pg_dump always matches the server; a stray host copy may
    # be older and refuse the dump, so the explicit flag must take precedence.
    assert calls[0][:4] == ["docker", "compose", "exec", "-T"]
    assert created.is_file() and created.stat().st_size > 0


def test_an_empty_dump_never_becomes_a_recovery_point(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("scripts.backup_postgres.shutil.which", lambda name: None)
    monkeypatch.setattr("scripts.backup_postgres.subprocess.run", lambda command, **kwargs: None)

    with pytest.raises(RuntimeError, match="non-empty"):
        create_backup("postgresql+psycopg://u:p@127.0.0.1:5432/db", tmp_path, docker_service="postgres")

    # A truncated file is worse than no file: it would read as a recovery point.
    assert list_backups(tmp_path) == []
    assert list(tmp_path.glob("*.part")) == []


def test_output_that_is_not_a_custom_format_dump_is_rejected(tmp_path: Path, monkeypatch):
    def write_error_text(command, **kwargs):
        handle = kwargs.get("stdout")
        if handle is not None:
            handle.write(b"pg_dump: error: connection failed")

    monkeypatch.setattr("scripts.backup_postgres.shutil.which", lambda name: None)
    monkeypatch.setattr("scripts.backup_postgres.subprocess.run", write_error_text)

    # pg_dump can exit 0 having streamed a diagnostic; a non-empty file is not
    # proof of a backup, the PGDMP magic is.
    with pytest.raises(RuntimeError, match="custom-format"):
        create_backup("postgresql+psycopg://u:p@127.0.0.1:5432/db", tmp_path, docker_service="postgres")

    assert list_backups(tmp_path) == []
    assert list(tmp_path.glob("*.part")) == []


def _service(backups_path: Path | None, max_age_hours: float = 24.0) -> OperationalService:
    return OperationalService(None, "redis://127.0.0.1:6379/0", "test", None, None, backups_path=backups_path, backup_max_age_hours=max_age_hours)


def test_health_reports_backup_freshness_from_the_dumps_on_disk(tmp_path: Path):
    # `disabled` = not configured, `pending` = configured but nothing dumped yet.
    # Both are honest, and neither is the same as "the backup is too old".
    assert _service(None)._backup_status() == ("disabled", None)
    assert _service(tmp_path)._backup_status() == ("pending", None)

    _dump(tmp_path, "local-ai-20260110-000000.dump", age_days=0.25)
    status, age_hours = _service(tmp_path)._backup_status()
    assert status == "ok" and age_hours is not None and 5 < age_hours < 7

    os.utime(tmp_path / "local-ai-20260110-000000.dump", (time.time() - 5 * 86400, time.time() - 5 * 86400))
    stale_status, stale_age = _service(tmp_path)._backup_status()
    assert stale_status == "unavailable" and stale_age is not None and stale_age > 24


def test_a_dump_still_being_written_is_not_counted_as_a_recovery_point(tmp_path: Path):
    (tmp_path / "local-ai-20260110-000000.dump.1234.part").write_bytes(b"PGDMP half")

    # Only the final name counts; otherwise a dump in progress would make the
    # health endpoint claim a fresh recovery point that cannot restore.
    assert _service(tmp_path)._backup_status() == ("pending", None)
    assert list_backups(tmp_path) == []
