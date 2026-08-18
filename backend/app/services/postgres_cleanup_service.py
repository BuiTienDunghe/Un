"""PostgreSQL cleanup executor with claim/revalidation boundaries.

The executor intentionally performs one external operation only after its
short PostgreSQL claim transaction commits.  Every finalization re-reads the
row, making retries safe after a process crash or partial external failure.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from app.postgres.models import Document, DocumentChunk, DocumentPage, DocumentVersion, Job, OcrRun, OutboxEvent, RequestLog
from app.services.postgres_cleanup_planner import BUSY_JOB_STATUSES


class PostgresCleanupService:
    def __init__(self, sessions: sessionmaker, qdrant, documents_path: Path, grace_days: int = 7, *, ocr_runs_path: Path | None = None, request_log_retention_days: int = 7, ocr_runs_ttl_days: int = 14, temporary_sources_ttl_days: int = 0, claim_lease_seconds: int = 900) -> None:
        self.sessions, self.qdrant, self.documents_path = sessions, qdrant, documents_path
        self.grace_days, self.ocr_runs_path = grace_days, ocr_runs_path or documents_path.parent / "ocr_runs"
        self.request_log_retention_days, self.ocr_runs_ttl_days = request_log_retention_days, ocr_runs_ttl_days
        self.temporary_sources_ttl_days = temporary_sources_ttl_days
        self.claim_lease_seconds = claim_lease_seconds

    def run_once(self) -> dict[str, int]:
        return {
            "logs": self.cleanup_expired_logs(),
            "ocr_runs": self.cleanup_expired_ocr_runs(),
            "sources": self.cleanup_expired_sources(),
            "superseded": self.cleanup_superseded(),
            "deleted": self.cleanup_deleting_documents(),
        }

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    def _document_dir(self, document_id: str) -> Path:
        root = self.documents_path.resolve()
        target = (root / document_id).resolve()
        if target.parent != root:
            raise ValueError("cleanup source path escapes documents root")
        return target

    def _has_busy_version_state(self, session, version_id: str) -> bool:
        return bool(session.scalar(select(Job.id).where(Job.version_id == version_id, Job.job_type != "cleanup_version", Job.status.in_(BUSY_JOB_STATUSES)).limit(1)) or session.scalar(select(OutboxEvent.id).join(Job, OutboxEvent.job_id == Job.id).where(Job.version_id == version_id, OutboxEvent.status == "pending").limit(1)))

    def _claim(self, session, *, key: str, job_type: str, document_id: str | None = None, version_id: str | None = None) -> Job | None:
        now = self._now()
        job = session.scalar(select(Job).where(Job.idempotency_key == key).with_for_update())
        if job and job.status == "completed":
            return None
        if job and job.status == "running" and job.lease_expires_at and job.lease_expires_at > now:
            return None
        if job is None:
            job = Job(id=f"job_{key}"[:128], job_type=job_type, document_id=document_id, version_id=version_id, status="running", max_attempts=3, idempotency_key=key, payload={})
            session.add(job)
        else:
            job.status = "running"
        job.started_at = job.started_at or now
        job.heartbeat_at, job.lease_expires_at = now, now + timedelta(seconds=self.claim_lease_seconds)
        return job

    def cleanup_expired_logs(self) -> int:
        cutoff = self._now() - timedelta(days=self.request_log_retention_days)
        # Logs have no external dependency.  Conditional delete is the claim
        # and finalization in one short transaction.
        with self.sessions.begin() as session:
            result = session.execute(delete(RequestLog).where(RequestLog.created_at < cutoff))
            return int(result.rowcount or 0)

    def cleanup_expired_ocr_runs(self) -> int:
        cutoff = self._now() - timedelta(days=self.ocr_runs_ttl_days)
        with self.sessions() as session:
            ids = list(session.scalars(select(OcrRun.id).where(OcrRun.updated_at < cutoff, OcrRun.status.notin_(("queued", "running", "processing"))).with_for_update(skip_locked=True)))
        completed = 0
        for run_id in ids:
            # Reclaim atomically before filesystem work.  `cleanup_pending` is
            # a durable retry state; a later run can pick it up.
            with self.sessions.begin() as session:
                row = session.get(OcrRun, run_id, with_for_update=True)
                if not row or (row.updated_at >= cutoff) or row.status in {"queued", "running", "processing"}:
                    continue
                row.status = "cleanup_pending"
            try:
                shutil.rmtree(self.ocr_runs_path / run_id, ignore_errors=False)
            except FileNotFoundError:
                pass
            except OSError:
                # Keep a durable non-active state; retry will revalidate it.
                continue
            with self.sessions.begin() as session:
                row = session.get(OcrRun, run_id, with_for_update=True)
                if row and row.status == "cleanup_pending":
                    session.delete(row); completed += 1
        return completed

    def cleanup_expired_sources(self) -> int:
        if self.temporary_sources_ttl_days <= 0:
            return 0
        cutoff = self._now() - timedelta(days=self.temporary_sources_ttl_days)
        with self.sessions() as session:
            ids = list(session.scalars(select(Document.id).where(Document.retention_policy == "temporary", Document.pinned.is_(False), Document.source_available.is_(True), Document.status.notin_(("indexed", "processing", "deleting", "deleted")), Document.created_at < cutoff)))
        completed = 0
        for doc_id in ids:
            claim_key = f"cleanup_source:{doc_id}"
            with self.sessions.begin() as session:
                doc = session.get(Document, doc_id, with_for_update=True)
                if not doc or doc.pinned or not doc.source_available or doc.status in {"indexed", "processing", "deleting", "deleted"}:
                    continue
                if session.scalar(select(Job.id).where(Job.document_id == doc_id, Job.status.in_(BUSY_JOB_STATUSES)).limit(1)):
                    continue
                claim = self._claim(session, key=claim_key, job_type="cleanup_source", document_id=doc_id)
                if claim is None:
                    continue
            try:
                shutil.rmtree(self._document_dir(doc_id), ignore_errors=False)
            except FileNotFoundError:
                pass
            except OSError:
                with self.sessions.begin() as session:
                    claim = session.scalar(select(Job).where(Job.idempotency_key == claim_key))
                    if claim and claim.status == "running": claim.status, claim.lease_expires_at = "retrying", None
                continue
            with self.sessions.begin() as session:
                doc = session.get(Document, doc_id, with_for_update=True)
                claim = session.scalar(select(Job).where(Job.idempotency_key == claim_key).with_for_update())
                if doc and claim and claim.status == "running" and not doc.pinned:
                    doc.source_available, doc.source_removed_at = False, self._now()
                    claim.status, claim.completed_at, claim.lease_expires_at = "completed", self._now(), None
                    completed += 1
        return completed

    def cleanup_superseded(self) -> int:
        cutoff = self._now() - timedelta(days=self.grace_days)
        with self.sessions() as session:
            candidates = list(session.scalars(select(DocumentVersion.id).where(DocumentVersion.status.in_(("superseded", "cleanup_pending")), DocumentVersion.superseded_at < cutoff)))
        completed = 0
        for version_id in candidates:
            with self.sessions.begin() as session:
                version = session.get(DocumentVersion, version_id, with_for_update=True)
                if not version:
                    continue
                document = session.get(Document, version.document_id, with_for_update=True)
                if not document or document.pinned or document.active_version_id == version.id or self._has_busy_version_state(session, version.id):
                    continue
                if version.status == "superseded" and (version.superseded_at is None or version.superseded_at >= cutoff):
                    continue
                if version.status not in {"superseded", "cleanup_pending"}:
                    continue
                claim = self._claim(session, key=f"cleanup_version:{version.id}", job_type="cleanup_version", document_id=document.id, version_id=version.id)
                if claim is None:
                    continue
                version.status = "cleanup_pending"
                document_id = document.id
            try:
                self.qdrant.delete_document_version(document_id, version_id)
            except Exception:
                # Leave cleanup_pending: retry is idempotent at Qdrant and
                # active retrieval excludes this version.
                with self.sessions.begin() as session:
                    claim = session.scalar(select(Job).where(Job.idempotency_key == f"cleanup_version:{version_id}").with_for_update())
                    if claim and claim.status == "running": claim.status, claim.lease_expires_at = "retrying", None
                continue
            with self.sessions.begin() as session:
                version = session.get(DocumentVersion, version_id, with_for_update=True)
                document = session.get(Document, document_id, with_for_update=True)
                if not version or not document or version.status != "cleanup_pending" or document.active_version_id == version.id or document.pinned:
                    continue
                session.execute(delete(DocumentPage).where(DocumentPage.version_id == version_id))
                session.execute(delete(DocumentChunk).where(DocumentChunk.version_id == version_id))
                version.status = "deleted"
                claim = session.scalar(select(Job).where(Job.idempotency_key == f"cleanup_version:{version_id}").with_for_update())
                if claim and claim.status == "running": claim.status, claim.completed_at, claim.lease_expires_at = "completed", self._now(), None
                completed += 1
        return completed

    def cleanup_deleting_documents(self) -> int:
        with self.sessions() as session:
            ids = list(session.scalars(select(Document.id).where(Document.status == "deleting")))
        completed = 0
        for doc_id in ids:
            with self.sessions.begin() as session:
                doc = session.get(Document, doc_id, with_for_update=True)
                delete_job = session.scalar(select(Job).where(Job.document_id == doc_id, Job.job_type == "delete_document").with_for_update())
                if not doc or doc.status != "deleting" or not delete_job or delete_job.status not in {"queued", "retrying", "running"}:
                    continue
                if session.scalar(select(OutboxEvent.id).where(OutboxEvent.job_id == delete_job.id, OutboxEvent.status == "pending").limit(1)):
                    continue
                now = self._now()
                if delete_job.status == "running" and delete_job.lease_expires_at and delete_job.lease_expires_at > now:
                    continue
                delete_job.status, delete_job.started_at = "running", delete_job.started_at or now
                delete_job.heartbeat_at, delete_job.lease_expires_at = now, now + timedelta(seconds=self.claim_lease_seconds)
            try:
                self.qdrant.delete_document(doc_id)
            except Exception as error:
                with self.sessions.begin() as session:
                    job = session.scalar(select(Job).where(Job.document_id == doc_id, Job.job_type == "delete_document").with_for_update())
                    if job and job.status == "running": job.status, job.error_message, job.lease_expires_at = "retrying", str(error)[:1000], None
                continue
            try:
                shutil.rmtree(self._document_dir(doc_id), ignore_errors=False)
            except FileNotFoundError:
                pass
            except OSError as error:
                with self.sessions.begin() as session:
                    job = session.scalar(select(Job).where(Job.document_id == doc_id, Job.job_type == "delete_document").with_for_update())
                    if job and job.status == "running": job.status, job.error_message, job.lease_expires_at = "retrying", str(error)[:1000], None
                continue
            with self.sessions.begin() as session:
                doc = session.get(Document, doc_id, with_for_update=True)
                job = session.scalar(select(Job).where(Job.document_id == doc_id, Job.job_type == "delete_document").with_for_update())
                if not doc or not job or doc.status != "deleting" or job.status != "running":
                    continue
                session.execute(delete(DocumentPage).where(DocumentPage.document_id == doc_id))
                session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc_id))
                for version in session.scalars(select(DocumentVersion).where(DocumentVersion.document_id == doc_id)):
                    version.status = "deleted"
                for item in session.scalars(select(Job).where(Job.document_id == doc_id, Job.status.in_(BUSY_JOB_STATUSES))):
                    if item.job_type != "delete_document": item.status = "cancelled"
                doc.status, doc.active_version_id, doc.source_available, doc.deleted_at = "deleted", None, False, self._now()
                job.status, job.completed_at, job.lease_expires_at = "completed", self._now(), None
                completed += 1
        return completed
