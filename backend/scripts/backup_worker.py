"""Periodic PostgreSQL backup worker.

Mirrors `scripts.cleanup_worker`: the same --once/--loop shape, the same
heartbeat-file convention, and the same "interval comes from the storage
section of models.yaml" rule, so operating one worker teaches you the other.

It runs on the host rather than in a container on purpose: the dump is taken
by the PostgreSQL container's own pg_dump (`--docker-service`), which always
matches the server version, and no application image needs a database client.
"""
from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime
from pathlib import Path

from app.config.settings import get_settings
from scripts.backup_postgres import create_backup, list_backups, rotate_backups

HEARTBEAT_NAME = "backup-worker.heartbeat"


def run_once(settings, docker_service: str | None, force: bool = False) -> dict[str, object]:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required")
    config = settings.load_storage_config()
    output_dir = settings.postgres_backups_path
    interval_hours = int(config.get("backup_interval_hours", 24))
    existing = list_backups(output_dir)
    if not force and existing:
        age_hours = (datetime.now(UTC).timestamp() - existing[0].stat().st_mtime) / 3600
        if age_hours < interval_hours:
            # The worker restarts every time the launcher runs. Without this the
            # system would collect a dump per restart instead of per interval.
            return {"skipped": "recent backup exists", "newest": str(existing[0]), "age_hours": round(age_hours, 2)}
    created = create_backup(str(settings.database_url), output_dir, docker_service)
    removed = rotate_backups(
        output_dir,
        int(config.get("backups_ttl_days", 14)),
        int(config.get("backups_keep_minimum", 3)),
    )
    return {
        "created": str(created),
        "size_bytes": created.stat().st_size,
        "rotated": [str(item) for item in removed],
        "total_backups": len(list_backups(output_dir)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="PostgreSQL backup worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument(
        "--docker-service",
        default="postgres",
        help="Compose service whose pg_dump takes the dump; pass an empty value to use host pg_dump",
    )
    parser.add_argument("--force", action="store_true", help="Back up even when the newest dump is still inside the interval")
    args = parser.parse_args()
    settings = get_settings()
    heartbeat = settings.documents_path.parent / HEARTBEAT_NAME
    heartbeat.parent.mkdir(parents=True, exist_ok=True)
    while True:
        # The heartbeat is written before the dump so a worker stuck on a slow
        # dump still reads as alive; backup freshness is judged from the dump
        # files themselves, not from this file.
        heartbeat.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")
        try:
            print(run_once(settings, args.docker_service or None, args.force), flush=True)
        except Exception as error:
            # A failed backup must not kill the worker: the next interval is a
            # free retry, and /health already reports the stale backup age.
            print({"error": str(error)}, flush=True)
            if args.once:
                return 1
        if args.once:
            return 0
        interval_hours = int(settings.load_storage_config().get("backup_interval_hours", 24))
        time.sleep(max(300, interval_hours * 3600))


if __name__ == "__main__":
    raise SystemExit(main())
