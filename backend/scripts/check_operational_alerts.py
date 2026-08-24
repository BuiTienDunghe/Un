"""Exit non-zero when durable jobs are stale or the corpus crossed its warning size; suited to Task Scheduler/cron."""
from __future__ import annotations
import argparse, json
from datetime import UTC, datetime
from sqlalchemy import func, select
from app.config.settings import get_settings
from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import Document, DocumentChunk, DocumentVersion, Job

def main() -> None:
 parser=argparse.ArgumentParser(); parser.add_argument("--fail-on-alert",action="store_true")
 # Plan section 9.5 reopens P4-4b at ~5000 active chunks; warning at half gives
 # the decision time to happen before the threshold, instead of being noticed
 # after. 0 disables the check.
 parser.add_argument("--chunk-warn",type=int,default=2500,help="alert when active chunks reach this (0 = off)")
 args=parser.parse_args(); settings=get_settings()
 if not settings.database_url: raise RuntimeError("DATABASE_URL is required")
 sessions=create_session_factory(create_postgres_engine(settings.database_url))
 with sessions() as session:
  jobs=list(session.scalars(select(Job).where(Job.status=="running",Job.lease_expires_at < datetime.now(UTC))))
  # Same predicate as the BM25 snapshot: only the authoritative active corpus.
  active_chunks=session.scalar(select(func.count()).select_from(DocumentChunk).join(Document,Document.id==DocumentChunk.document_id).join(DocumentVersion,DocumentVersion.id==Document.active_version_id).where(DocumentChunk.version_id==DocumentVersion.id,Document.status=="indexed",DocumentVersion.status=="active")) or 0
 chunk_alert=bool(args.chunk_warn) and active_chunks>=args.chunk_warn
 payload={"stale_jobs":len(jobs),"jobs":[{"id":j.id,"type":j.job_type,"worker_id":j.worker_id,"lease_expires_at":j.lease_expires_at.isoformat() if j.lease_expires_at else None} for j in jobs],"active_chunks":active_chunks,"chunk_warn_threshold":args.chunk_warn,"chunk_alert":chunk_alert}; print(json.dumps(payload))
 if args.fail_on_alert and (jobs or chunk_alert): raise SystemExit(2)
if __name__=="__main__": main()
