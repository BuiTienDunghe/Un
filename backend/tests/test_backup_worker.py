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


# ── 24/08: the second net gets a second location, and a bell ──────────────────

from scripts.backup_postgres import mirror_files, newest_file_age_hours, rotate_files
from scripts.backup_sources import SOURCES_PATTERN, archive_sources


def test_mirror_copies_only_missing_files_and_never_leaves_a_part(tmp_path: Path):
    source, mirror = tmp_path / "src", tmp_path / "mir"
    _dump(source, "local-ai-20260101-000000.dump")
    _dump(source, "local-ai-20260102-000000.dump")
    _dump(mirror, "local-ai-20260101-000000.dump")  # already mirrored

    copied = mirror_files(source, mirror, "local-ai-*.dump")

    assert [item.name for item in copied] == ["local-ai-20260102-000000.dump"]
    assert len(list(mirror.glob("*.dump"))) == 2
    assert list(mirror.glob("*.part")) == []
    # Idempotent: a second pass copies nothing.
    assert mirror_files(source, mirror, "local-ai-*.dump") == []


def test_rotate_files_applies_the_same_policy_to_source_archives(tmp_path: Path):
    for day in range(5):
        path = tmp_path / f"sources-2026010{day}-000000.zip"
        path.write_bytes(b"PK fake")
        stamp = time.time() - (90 + day) * 86400
        os.utime(path, (stamp, stamp))

    removed = rotate_files(tmp_path, "sources-*.zip", retention_days=14, keep_minimum=3)

    assert len(removed) == 2 and len(list(tmp_path.glob("sources-*.zip"))) == 3


def test_newest_file_age_hours_is_the_alert_scripts_question(tmp_path: Path):
    assert newest_file_age_hours(tmp_path) is None  # no dump at all = alert
    _dump(tmp_path, "local-ai-20260101-000000.dump", age_days=3)
    age = newest_file_age_hours(tmp_path)
    assert age is not None and 71 < age < 73


def test_archive_sources_zips_originals_with_manifest_and_no_part(tmp_path: Path):
    documents = tmp_path / "documents"
    (documents / "doc_a").mkdir(parents=True)
    (documents / "doc_a" / "original.md").write_text("alpha body", encoding="utf-8")
    (documents / "doc_b").mkdir()
    (documents / "doc_b" / "original.pdf").write_bytes(b"%PDF fake")
    (documents / "doc_b" / "derived.txt").write_text("not archived", encoding="utf-8")

    archive, count = archive_sources(documents, tmp_path / "out")

    assert count == 2 and archive.exists() and list((tmp_path / "out").glob("*.part")) == []
    from zipfile import ZipFile
    with ZipFile(archive) as zip_file:
        names = set(zip_file.namelist())
        assert names == {"doc_a/original.md", "doc_b/original.pdf", "manifest.json"}
        import json as json_module
        manifest = json_module.loads(zip_file.read("manifest.json"))
        assert {entry["path"] for entry in manifest} == {"doc_a\original.md", "doc_b\original.pdf"} or {entry["path"] for entry in manifest} == {"doc_a/original.md", "doc_b/original.pdf"}


def test_run_once_archives_sources_and_mirrors_both(tmp_path: Path, monkeypatch):
    """The nightly cycle: dump -> rotate -> sources -> mirror, one call."""
    from types import SimpleNamespace
    import scripts.backup_worker as worker

    documents = tmp_path / "data" / "documents"
    (documents / "doc_a").mkdir(parents=True)
    (documents / "doc_a" / "original.md").write_text("alpha", encoding="utf-8")
    backups = tmp_path / "data" / "backups"
    mirror = tmp_path / "mirror"

    def fake_create_backup(url, output_dir, docker_service):
        return _dump(Path(output_dir), "local-ai-20260110-000000.dump")

    monkeypatch.setattr(worker, "create_backup", fake_create_backup)
    settings = SimpleNamespace(
        database_url="postgresql+psycopg://u:p@127.0.0.1:5432/db",
        load_storage_config=lambda: {"backup_interval_hours": 24, "backups_ttl_days": 14, "backups_keep_minimum": 3},
        postgres_backups_path=backups / "postgres",
        sources_backups_path=backups / "sources",
        env_backups_path=backups / "env",
        env_file_path=tmp_path / ".env",
        backup_mirror_path=mirror,
        documents_path=documents,
    )

    result = worker.run_once(settings, docker_service=None, force=True)

    assert result["sources_count"] == 1
    assert (mirror / "postgres" / "local-ai-20260110-000000.dump").exists()
    assert list((mirror / "sources").glob("sources-*.zip"))
    assert "warnings" not in result


def test_run_once_backup_survives_a_dead_mirror(tmp_path: Path, monkeypatch):
    """A failed second copy must never undo a successful first one."""
    from types import SimpleNamespace
    import scripts.backup_worker as worker

    documents = tmp_path / "data" / "documents"
    documents.mkdir(parents=True)
    backups = tmp_path / "data" / "backups"

    monkeypatch.setattr(worker, "create_backup", lambda url, output_dir, docker_service: _dump(Path(output_dir), "local-ai-20260110-000000.dump"))
    monkeypatch.setattr(worker, "mirror_files", lambda *args: (_ for _ in ()).throw(OSError("mirror drive is gone")))
    settings = SimpleNamespace(
        database_url="postgresql+psycopg://u:p@127.0.0.1:5432/db",
        load_storage_config=lambda: {"backup_interval_hours": 24, "backups_ttl_days": 14, "backups_keep_minimum": 3},
        postgres_backups_path=backups / "postgres",
        sources_backups_path=backups / "sources",
        env_backups_path=backups / "env",
        env_file_path=tmp_path / ".env",
        backup_mirror_path=tmp_path / "mirror",
        documents_path=documents,
    )

    result = worker.run_once(settings, docker_service=None, force=True)

    assert "created" in result  # the dump itself succeeded
    assert any("mirror failed" in warning for warning in result.get("warnings", []))


def test_env_is_copied_plainly_and_only_when_it_changed(tmp_path: Path):
    """.env travels in the backup as plain text, on purpose.

    It already sits in plain text at the project root, so a copy under the
    gitignored backup folder adds no exposure — while a passphrase would add a
    way to lose the backup for good. Encryption is for copies leaving the
    machine (backup-env-once.bat), not for this one.
    """
    from scripts.backup_postgres import ENV_PATTERN, archive_env

    env_file, out = tmp_path / ".env", tmp_path / "envbak"
    env_file.write_text("TOKEN=first\n", encoding="utf-8")

    first, changed = archive_env(env_file, out)
    assert changed and first is not None and first.read_text(encoding="utf-8") == "TOKEN=first\n"

    # Unchanged .env must not pile up one identical copy per night.
    same, changed_again = archive_env(env_file, out)
    assert not changed_again and same == first
    assert len(list(out.glob(ENV_PATTERN))) == 1

    env_file.write_text("TOKEN=second\n", encoding="utf-8")
    second, changed_third = archive_env(env_file, out)
    assert changed_third and second != first
    # The old copy stays: the folder is a history of edits, not a single mirror.
    assert len(list(out.glob(ENV_PATTERN))) == 2


def test_a_missing_env_is_not_an_error(tmp_path: Path):
    from scripts.backup_postgres import archive_env

    assert archive_env(tmp_path / "nope.env", tmp_path / "out") == (None, False)
