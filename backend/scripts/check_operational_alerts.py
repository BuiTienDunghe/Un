"""Exit non-zero when jobs are stale, the corpus crossed its warning size, or the newest dump is too old; suited to Task Scheduler/cron."""
from __future__ import annotations
import argparse, json
from datetime import UTC, datetime
from sqlalchemy import func, select
from app.config.settings import get_settings
from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Document, DocumentChunk, DocumentVersion, Job
from scripts.backup_postgres import newest_file_age_hours

def main() -> None:
 parser=argparse.ArgumentParser(); parser.add_argument("--fail-on-alert",action="store_true")
 # Plan section 9.5 reopens P4-4b at ~5000 active chunks; warning at half gives
 # the decision time to happen before the threshold, instead of being noticed
 # after. 0 disables the check.
 parser.add_argument("--chunk-warn",type=int,default=2500,help="alert when active chunks reach this (0 = off)")
 # Two nights of missed dumps went unnoticed on 23-24/08 (Docker Desktop was
 # off, the 02:00 task failed silently, and /health only lives while the
 # launcher runs). 48h = two intervals: one late dump is not an incident.
 parser.add_argument("--dump-max-age-hours",type=float,default=48.0,help="alert when the newest dump is older (0 = off)")
 args=parser.parse_args(); settings=get_settings()
 if not settings.database_url: raise RuntimeError("DATABASE_URL is required")
 # The DB half must not take the filesystem half down with it. The incident
 # this script exists for (23-24/08) was "Docker Desktop was off, so no dumps
 # were taken" -- and with Docker off, the original code crashed on connect
 # BEFORE evaluating dump age, i.e. it went blind in exactly the situation it
 # was built to catch. A DB error is reported (exit 3, not the alert exit 2,
 # so a morning Docker-not-yet-started race is loggable without a false
 # popup), and the dump-age check still runs.
 jobs=[]; active_chunks=None; db_error=None
 try:
  sessions=create_session_factory(create_postgres_engine(settings.database_url))
  with sessions() as session:
   jobs=list(session.scalars(select(Job).where(Job.status=="running",Job.lease_expires_at < datetime.now(UTC))))
   # Same predicate as the BM25 snapshot: only the authoritative active corpus.
   active_chunks=session.scalar(select(func.count()).select_from(DocumentChunk).join(Document,Document.id==DocumentChunk.document_id).join(DocumentVersion,DocumentVersion.id==Document.active_version_id).where(DocumentChunk.version_id==DocumentVersion.id,Document.status=="indexed",DocumentVersion.status=="active")) or 0
 except Exception as error:
  db_error=f"{type(error).__name__}: {error}"
 chunk_alert=bool(args.chunk_warn) and active_chunks is not None and active_chunks>=args.chunk_warn
 dump_age=newest_file_age_hours(settings.postgres_backups_path)
 dump_alert=bool(args.dump_max_age_hours) and (dump_age is None or dump_age>args.dump_max_age_hours)
 # A failed nightly eval leaves this marker (scripts/nightly_eval.py); folding
 # it in here means ONE morning popup covers the whole night shift.
 eval_attention=(settings.logs_path/"ATTENTION_nightly_eval.txt")
 eval_alert=eval_attention.exists()
 payload={"stale_jobs":len(jobs),"jobs":[{"id":j.id,"type":j.job_type,"worker_id":j.worker_id,"lease_expires_at":j.lease_expires_at.isoformat() if j.lease_expires_at else None} for j in jobs],"active_chunks":active_chunks,"chunk_warn_threshold":args.chunk_warn,"chunk_alert":chunk_alert,"newest_dump_age_hours":round(dump_age,2) if dump_age is not None else None,"dump_max_age_hours":args.dump_max_age_hours,"dump_alert":dump_alert,"nightly_eval_alert":eval_alert,"db_error":db_error}; print(json.dumps(payload))
 if args.fail_on_alert and (jobs or chunk_alert or dump_alert or eval_alert): raise SystemExit(2)
 if db_error: raise SystemExit(3)
if __name__=="__main__": main()
