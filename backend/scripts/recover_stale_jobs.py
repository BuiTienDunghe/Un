import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.config.settings import get_settings
from app.postgres.database import create_postgres_engine, create_session_factory
from app.services.job_queue_service import JobQueueService
from app.services.job_recovery_service import JobRecoveryService

settings = get_settings()
if not settings.database_url:
    raise SystemExit("DATABASE_URL is required")
parser = argparse.ArgumentParser(); mode = parser.add_mutually_exclusive_group(required=True); mode.add_argument("--dry-run", action="store_true"); mode.add_argument("--execute", action="store_true"); args = parser.parse_args()
service = JobRecoveryService(create_session_factory(create_postgres_engine(settings.database_url)), JobQueueService(settings.redis_url, settings.rq_queue_prefix))
print({"mode": "dry-run" if args.dry_run else "execute", "stale": service.recover_stale(args.dry_run), "requeued": service.reconcile_queued(args.dry_run)})
