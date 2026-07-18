"""Exit non-zero when durable jobs are stale; suited to Task Scheduler/cron."""
from __future__ import annotations
import argparse, json
from datetime import UTC, datetime
from sqlalchemy import select
from app.config.settings import get_settings
from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Job

def main() -> None:
 parser=argparse.ArgumentParser(); parser.add_argument("--fail-on-alert",action="store_true"); args=parser.parse_args(); settings=get_settings()
 if not settings.database_url: raise RuntimeError("DATABASE_URL is required")
 sessions=create_session_factory(create_postgres_engine(settings.database_url))
 with sessions() as session: jobs=list(session.scalars(select(Job).where(Job.status=="running",Job.lease_expires_at < datetime.now(UTC))))
 payload={"stale_jobs":len(jobs),"jobs":[{"id":j.id,"type":j.job_type,"worker_id":j.worker_id,"lease_expires_at":j.lease_expires_at.isoformat() if j.lease_expires_at else None} for j in jobs]}; print(json.dumps(payload))
 if args.fail_on_alert and jobs: raise SystemExit(2)
if __name__=="__main__": main()
