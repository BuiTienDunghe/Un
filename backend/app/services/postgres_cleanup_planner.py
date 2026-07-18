"""Read-only PostgreSQL cleanup planning for the Phase 7B safety gate.

This module deliberately has no delete, update, Redis, filesystem, or Qdrant
mutation call.  Phase 7C may consume its candidates only after revalidating
every guard immediately before an external side effect.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.postgres.models import Document, DocumentChunk, DocumentPage, DocumentVersion, IngestionRun, Job, OcrRun, OutboxEvent, RequestLog


BUSY_JOB_STATUSES = ("queued", "running", "retrying", "cancel_requested")
BUSY_RUN_STATUSES = ("queued", "processing", "partial")


@dataclass(frozen=True)
class CleanupCandidate:
    operation_type: str
    entity_type: str
    entity_id: str
    reason: str
    retention_cutoff: str | None
    document_id: str | None = None
    version_id: str | None = None
    run_id: str | None = None
    job_id: str | None = None
    expected_postgres_rows: dict[str, int] = field(default_factory=dict)
    expected_qdrant_points: int | None = None
    expected_filesystem_paths: list[str] = field(default_factory=list)
    blocking_guards: list[str] = field(default_factory=list)
    idempotency_key: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class PostgresCleanupPlanner:
    """Builds a deterministic, read-only cleanup plan from PostgreSQL state."""

    def __init__(self, sessions: sessionmaker, documents_path: Path, ocr_runs_path: Path, *, superseded_grace_days: int, temporary_sources_ttl_days: int, logs_ttl_days: int, ocr_runs_ttl_days: int) -> None:
        self.sessions = sessions
        self.documents_path = documents_path
        self.ocr_runs_path = ocr_runs_path
        self.superseded_grace_days = superseded_grace_days
        self.temporary_sources_ttl_days = temporary_sources_ttl_days
        self.logs_ttl_days = logs_ttl_days
        self.ocr_runs_ttl_days = ocr_runs_ttl_days

    @staticmethod
    def _as_of(value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(UTC)
        return value if value.tzinfo else value.replace(tzinfo=UTC)

    @staticmethod
    def _cutoff(as_of: datetime, days: int) -> datetime:
        return as_of - timedelta(days=max(0, days))

    def plan(self, *, domain: str = "all", limit: int = 100, as_of: datetime | None = None, document_id: str | None = None) -> list[CleanupCandidate]:
        if domain not in {"all", "documents", "versions", "sources", "logs", "ocr-runs", "caches"}:
            raise ValueError(f"unsupported cleanup domain: {domain}")
        if limit < 1:
            raise ValueError("limit must be positive")
        now = self._as_of(as_of)
        result: list[CleanupCandidate] = []
        if domain in {"all", "documents", "sources"}:
            result.extend(self._plan_sources(now, document_id))
            result.extend(self._plan_deleting_documents(now, document_id))
        if domain in {"all", "versions"}:
            result.extend(self._plan_superseded_versions(now, document_id))
        if domain in {"all", "logs"}:
            result.extend(self._plan_logs(now))
        if domain in {"all", "ocr-runs"}:
            result.extend(self._plan_ocr_runs(now))
        # Cache expiry has no configured policy or schema timestamp suitable
        # for safe deletion.  It intentionally yields no candidate in 7B.
        return result[:limit]

    def _document_guards(self, session, document: Document) -> list[str]:
        guards: list[str] = []
        if document.status in {"indexed", "processing", "deleting", "deleted"}:
            guards.append(f"document_status={document.status}")
        if document.active_version_id:
            guards.append("has_active_version")
        if document.pinned:
            guards.append("pinned")
        if not document.source_available:
            guards.append("source_unavailable_metadata")
        busy = session.scalar(select(Job.id).where(Job.document_id == document.id, Job.status.in_(BUSY_JOB_STATUSES)).limit(1))
        if busy:
            guards.append("has_busy_job")
        pending_outbox = session.scalar(
            select(OutboxEvent.id).join(Job, OutboxEvent.job_id == Job.id).where(Job.document_id == document.id, OutboxEvent.status == "pending").limit(1)
        )
        if pending_outbox:
            guards.append("has_pending_outbox")
        return guards

    def _plan_sources(self, now: datetime, document_id: str | None) -> list[CleanupCandidate]:
        # Phase 7B only considers explicitly temporary, unpinned source
        # artifacts. Active/indexed documents are guarded out regardless of age.
        with self.sessions() as session:
            statement = select(Document).where(Document.retention_policy == "temporary", Document.pinned.is_(False), Document.source_available.is_(True))
            if document_id:
                statement = statement.where(Document.id == document_id)
            docs = list(session.scalars(statement))
            result = []
            for doc in docs:
                reference = doc.last_accessed_at or doc.created_at
                if reference is None:
                    continue
                cutoff = self._cutoff(now, self.temporary_sources_ttl_days)
                guards = self._document_guards(session, doc)
                if self.temporary_sources_ttl_days <= 0:
                    guards.append("temporary_source_ttl_disabled")
                elif reference >= cutoff:
                    guards.append("temporary_source_not_expired")
                result.append(CleanupCandidate(
                    operation_type="remove_source_artifact", entity_type="document", entity_id=doc.id,
                    document_id=doc.id, reason="temporary_unpinned_source", retention_cutoff=cutoff.isoformat(),
                    expected_postgres_rows={"documents": 1}, expected_filesystem_paths=[str(self.documents_path / doc.id)],
                    blocking_guards=guards, idempotency_key=f"cleanup:source:{doc.id}",
                ))
            return result

    def _plan_deleting_documents(self, now: datetime, document_id: str | None) -> list[CleanupCandidate]:
        with self.sessions() as session:
            statement = select(Document).where(Document.status == "deleting")
            if document_id:
                statement = statement.where(Document.id == document_id)
            result = []
            for doc in session.scalars(statement):
                jobs = list(session.scalars(select(Job).where(Job.document_id == doc.id)))
                delete_job = next((job for job in jobs if job.job_type == "delete_document"), None)
                guards = []
                if doc.active_version_id:
                    guards.append("active_version_must_be_cleared_by_executor")
                if any(job.status in BUSY_JOB_STATUSES and job.job_type != "delete_document" for job in jobs):
                    guards.append("has_non_delete_busy_job")
                if delete_job is None:
                    guards.append("missing_durable_delete_job")
                if delete_job and delete_job.status not in {"queued", "retrying", "running"}:
                    guards.append(f"delete_job_status={delete_job.status}")
                result.append(CleanupCandidate(
                    operation_type="delete_document_lifecycle", entity_type="document", entity_id=doc.id,
                    document_id=doc.id, job_id=delete_job.id if delete_job else None,
                    reason="document_status_deleting", retention_cutoff=None,
                    expected_postgres_rows={"documents": 1, "versions": session.scalar(select(func.count()).select_from(DocumentVersion).where(DocumentVersion.document_id == doc.id)) or 0, "pages": session.scalar(select(func.count()).select_from(DocumentPage).where(DocumentPage.document_id == doc.id)) or 0, "chunks": session.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.document_id == doc.id)) or 0},
                    expected_qdrant_points=None, expected_filesystem_paths=[str(self.documents_path / doc.id)],
                    blocking_guards=guards, idempotency_key=f"cleanup:delete-document:{doc.id}",
                ))
            return result

    def _plan_superseded_versions(self, now: datetime, document_id: str | None) -> list[CleanupCandidate]:
        cutoff = self._cutoff(now, self.superseded_grace_days)
        with self.sessions() as session:
            statement = select(DocumentVersion, Document).join(Document, Document.id == DocumentVersion.document_id).where(DocumentVersion.status == "superseded")
            if document_id:
                statement = statement.where(Document.id == document_id)
            result = []
            for version, document in session.execute(statement).tuples():
                guards: list[str] = []
                if document.active_version_id == version.id:
                    guards.append("active_version")
                if document.pinned:
                    guards.append("pinned_document")
                if version.superseded_at is None or version.superseded_at >= cutoff:
                    guards.append("grace_period_not_elapsed")
                busy_job = session.scalar(select(Job.id).where(Job.version_id == version.id, Job.status.in_(BUSY_JOB_STATUSES)).limit(1))
                if busy_job:
                    guards.append("has_busy_job")
                busy_run = session.scalar(select(IngestionRun.id).where(IngestionRun.version_id == version.id, IngestionRun.status.in_(BUSY_RUN_STATUSES)).limit(1))
                if busy_run:
                    guards.append("has_busy_run")
                pending_outbox = session.scalar(select(OutboxEvent.id).join(Job, OutboxEvent.job_id == Job.id).where(Job.version_id == version.id, OutboxEvent.status == "pending").limit(1))
                if pending_outbox:
                    guards.append("has_pending_outbox")
                result.append(CleanupCandidate(
                    operation_type="delete_superseded_version", entity_type="document_version", entity_id=version.id,
                    document_id=document.id, version_id=version.id, reason="superseded_version_grace_elapsed",
                    retention_cutoff=cutoff.isoformat(), expected_postgres_rows={"versions": 1, "pages": session.scalar(select(func.count()).select_from(DocumentPage).where(DocumentPage.version_id == version.id)) or 0, "chunks": session.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.version_id == version.id)) or 0},
                    expected_qdrant_points=None, blocking_guards=guards,
                    idempotency_key=f"cleanup:version:{version.id}",
                ))
            return result

    def _plan_logs(self, now: datetime) -> list[CleanupCandidate]:
        cutoff = self._cutoff(now, self.logs_ttl_days)
        with self.sessions() as session:
            rows = list(session.scalars(select(RequestLog).where(RequestLog.created_at < cutoff).order_by(RequestLog.created_at)))
        return [CleanupCandidate("delete_request_log", "request_log", str(row.id), "postgres_request_log_retention", cutoff.isoformat(), expected_postgres_rows={"request_logs": 1}, idempotency_key=f"cleanup:request-log:{row.id}") for row in rows]

    def _plan_ocr_runs(self, now: datetime) -> list[CleanupCandidate]:
        cutoff = self._cutoff(now, self.ocr_runs_ttl_days)
        with self.sessions() as session:
            rows = list(session.scalars(select(OcrRun).where(OcrRun.updated_at < cutoff).order_by(OcrRun.updated_at)))
        return [CleanupCandidate("delete_ocr_run", "ocr_run", row.id, "postgres_ocr_run_retention", cutoff.isoformat(), expected_postgres_rows={"ocr_runs": 1}, expected_filesystem_paths=[str(self.ocr_runs_path / row.id)], idempotency_key=f"cleanup:ocr-run:{row.id}") for row in rows]
