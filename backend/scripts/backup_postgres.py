"""Create a portable PostgreSQL backup using host or Compose-container pg_dump.

The dump/rotate helpers are importable so the periodic backup worker
(`scripts.backup_worker`) runs exactly the same code path as a manual run.
"""
from __future__ import annotations
import argparse
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from app.config.settings import get_settings

BACKUP_SUFFIX = ".dump"
BACKUP_PREFIX = "local-ai-"


def create_backup(url: str, output_dir: Path, docker_service: str | None = None) -> Path:
    """Write one validated custom-format dump into `output_dir` and return it.

    The dump is written to a `.part` file and only renamed once it is known to
    be complete.  Both the health check and the restore drill pick "the newest
    local-ai-*.dump", so a dump still being written must never carry that name:
    it would read as a recovery point that cannot actually restore.
    """
    parsed = urlparse(url.replace("postgresql+psycopg://", "postgresql://", 1))
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{BACKUP_PREFIX}{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}{BACKUP_SUFFIX}"
    staged = output.with_name(f"{output.name}.{os.getpid()}.part")
    env = os.environ.copy()
    if parsed.password:
        env["PGPASSWORD"] = parsed.password
    try:
        # An explicit --docker-service wins over whatever pg_dump happens to be
        # on PATH: the container's pg_dump always matches the server, while a
        # stray host copy may be older and refuse to dump a newer server.
        if docker_service:
            # Stream a custom-format dump from the configured PostgreSQL container;
            # the database password is never put in the command or output.
            command = ["docker", "compose", "exec", "-T", docker_service, "pg_dump", "--format=custom", "--username", parsed.username or "postgres", parsed.path.lstrip("/")]
            with staged.open("wb") as handle:
                subprocess.run(command, stdout=handle, check=True)
        elif shutil.which("pg_dump"):
            command = ["pg_dump", "--format=custom", "--file", str(staged), "--host", parsed.hostname or "localhost", "--port", str(parsed.port or 5432), "--username", parsed.username or "postgres", parsed.path.lstrip("/")]
            subprocess.run(command, env=env, check=True)
        else:
            raise RuntimeError("pg_dump is unavailable on PATH; rerun with --docker-service <postgres-service>")
        if not staged.is_file() or staged.stat().st_size == 0:
            raise RuntimeError("pg_dump did not produce a non-empty backup")
        # Custom-format dumps begin with the PGDMP magic. Anything else means
        # pg_dump wrote a diagnostic into the stream instead of a backup.
        with staged.open("rb") as handle:
            if handle.read(5) != b"PGDMP":
                raise RuntimeError("pg_dump output is not a custom-format backup")
        staged.replace(output)
    finally:
        staged.unlink(missing_ok=True)
    return output


def list_backups(output_dir: Path) -> list[Path]:
    """Existing dumps, newest first."""
    if not output_dir.is_dir():
        return []
    dumps = [item for item in output_dir.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}") if item.is_file()]
    return sorted(dumps, key=lambda item: item.stat().st_mtime, reverse=True)


def _files_newest_first(output_dir: Path, pattern: str) -> list[Path]:
    if not output_dir.is_dir():
        return []
    return sorted((item for item in output_dir.glob(pattern) if item.is_file()), key=lambda item: item.stat().st_mtime, reverse=True)


def rotate_files(output_dir: Path, pattern: str, retention_days: int, keep_minimum: int = 3) -> list[Path]:
    """Delete files matching `pattern` older than `retention_days`, never below `keep_minimum`.

    Retention is a storage policy, not a reason to end up with zero recovery
    points: an installation left idle past the window keeps its newest files.
    The pattern parameter exists because the same policy now covers dumps,
    source archives and their mirror copies.
    """
    if retention_days <= 0:
        return []
    files = _files_newest_first(output_dir, pattern)
    cutoff = datetime.now(UTC).timestamp() - retention_days * 86400
    removed: list[Path] = []
    for item in files[max(keep_minimum, 0):]:
        if item.stat().st_mtime < cutoff:
            item.unlink(missing_ok=True)
            removed.append(item)
    return removed


def rotate_backups(output_dir: Path, retention_days: int, keep_minimum: int = 3) -> list[Path]:
    return rotate_files(output_dir, f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}", retention_days, keep_minimum)


def mirror_files(source_dir: Path, mirror_dir: Path, pattern: str) -> list[Path]:
    """Copy files matching `pattern` that the mirror does not hold yet, by name.

    The same .part-then-rename discipline as create_backup: a copy interrupted
    halfway must never sit in the mirror under a name that reads as a recovery
    point. Files are matched by name only — dumps and archives are timestamped
    and never rewritten, so a name either exists on both sides or is missing.
    """
    mirror_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for item in _files_newest_first(source_dir, pattern):
        target = mirror_dir / item.name
        if target.exists():
            continue
        partial = mirror_dir / f"{item.name}.{os.getpid()}.part"
        try:
            shutil.copyfile(item, partial)
            partial.replace(target)
            copied.append(target)
        finally:
            partial.unlink(missing_ok=True)
    return copied


def newest_file_age_hours(output_dir: Path, pattern: str = f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}") -> float | None:
    """Age of the newest matching file in hours; None when there is none.

    The freshness question the alert script asks: judged from the files on
    disk, exactly like the /health backup component — a worker that is alive
    but failing every dump is not a backup.
    """
    files = _files_newest_first(output_dir, pattern)
    if not files:
        return None
    return (datetime.now(UTC).timestamp() - files[0].stat().st_mtime) / 3600


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="data/backups/postgres")
    parser.add_argument("--docker-service", help="Compose service containing pg_dump when host pg_dump is unavailable")
    parser.add_argument("--retention-days", type=int, default=0, help="Delete dumps older than this after a successful backup; 0 disables rotation")
    parser.add_argument("--keep-minimum", type=int, default=3, help="Never rotate below this many dumps")
    args = parser.parse_args()
    url = get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL is required")
    output = create_backup(url, Path(args.output_dir), args.docker_service)
    for removed in rotate_backups(Path(args.output_dir), args.retention_days, args.keep_minimum):
        print(f"rotated {removed}")
    print(output)


if __name__ == "__main__":
    main()
