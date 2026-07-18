from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import time
from datetime import datetime

from app.config.settings import get_settings
from app.postgres.database import create_postgres_engine, create_session_factory
from app.services.postgres_cleanup_planner import CleanupCandidate, PostgresCleanupPlanner
from app.services.postgres_cleanup_service import PostgresCleanupService
from app.stores.qdrant_store import QdrantStore


def _parse_as_of(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed


def _dry_run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for PostgreSQL cleanup planning")
    sessions = create_session_factory(create_postgres_engine(settings.database_url))
    config = settings.load_storage_config()
    planner = PostgresCleanupPlanner(
        sessions, settings.documents_path, settings.ocr_runs_path,
        superseded_grace_days=settings.superseded_version_grace_days,
        temporary_sources_ttl_days=int(config.get("temporary_sources_ttl_days", 0)),
        logs_ttl_days=int(config.get("logs_ttl_days", 7)),
        ocr_runs_ttl_days=int(config.get("ocr_runs_ttl_days", 14)),
    )
    candidates = planner.plan(domain=args.domain, limit=args.limit, as_of=_parse_as_of(args.as_of), document_id=args.document_id)
    candidates = candidates[:args.limit]
    payload = {
        "mode": "dry-run",
        "side_effects": False,
        "domain": args.domain,
        "candidate_count": len(candidates),
        "eligible_count": sum(not item.blocking_guards for item in candidates),
        "blocked_count": sum(bool(item.blocking_guards) for item in candidates),
        "candidates": [item.as_dict() for item in candidates],
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="PostgreSQL cleanup worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--domain", default="all", choices=("all", "documents", "versions", "sources", "logs", "ocr-runs", "caches"))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--as-of")
    parser.add_argument("--document-id")
    args = parser.parse_args()
    if args.dry_run:
        return _dry_run(args)
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required")
    sessions = create_session_factory(create_postgres_engine(settings.database_url))
    qdrant = QdrantStore(settings.qdrant_url, settings.qdrant_timeout_seconds)
    from sqlalchemy import text
    with sessions() as session:
        session.execute(text("SELECT 1"))
    if not qdrant.healthcheck():
        raise RuntimeError("Qdrant is unavailable")
    settings.documents_path.mkdir(parents=True, exist_ok=True)
    config = settings.load_storage_config()
    service = PostgresCleanupService(
        sessions, qdrant, settings.documents_path, settings.superseded_version_grace_days,
        ocr_runs_path=settings.ocr_runs_path,
        request_log_retention_days=settings.request_log_retention_days,
        ocr_runs_ttl_days=int(config.get("ocr_runs_ttl_days", 14)),
        temporary_sources_ttl_days=int(config.get("temporary_sources_ttl_days", 0)),
    )
    while True:
        (settings.documents_path.parent / "cleanup-worker.heartbeat").write_text(datetime.now(UTC).isoformat(), encoding="utf-8")
        print(service.run_once())
        if args.once:
            return 0
        time.sleep(max(60, int(settings.load_storage_config().get("cleanup_interval_hours", 24)) * 3600))


if __name__ == "__main__":
    raise SystemExit(main())
