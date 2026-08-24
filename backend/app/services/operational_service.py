"""Small operational read-model: health and metrics never change pipeline state."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from redis import Redis
from rq import Queue, Worker
from sqlalchemy import func, select, text
from sqlalchemy.orm import sessionmaker

from app.postgres.models import (
    AgentTrace,
    DiscordMemory,
    DiscordMemoryCandidate,
    Document,
    DocumentChunk,
    DocumentVersion,
    IngestionRun,
    Job,
    OutboxEvent,
)
from app.services.job_routing import DISCORD_MEMORY_INGEST_JOB_TYPE


class OperationalService:
    def __init__(
        self,
        sessions: sessionmaker | None,
        redis_url: str,
        prefix: str,
        qdrant,
        ollama,
        cleanup_heartbeat_path: Path | None = None,
        *,
        memory_ingestion_enabled: bool = False,
        memory_queue_name: str = "memory_extract",
        backups_path: Path | None = None,
        backup_heartbeat_path: Path | None = None,
        backup_max_age_hours: float = 24.0,
    ) -> None:
        self.sessions, self.redis_url, self.prefix, self.qdrant, self.ollama = sessions, redis_url, prefix, qdrant, ollama
        self.cleanup_heartbeat_path = cleanup_heartbeat_path
        self.memory_ingestion_enabled = memory_ingestion_enabled
        self.memory_queue_name = memory_queue_name
        self.backups_path = backups_path
        self.backup_heartbeat_path = backup_heartbeat_path
        self.backup_max_age_hours = backup_max_age_hours

    def _backup_status(self) -> tuple[str, float | None]:
        """Report the newest recovery point, not whether a worker is running.

        A backup worker that is alive but failing every dump is not a backup,
        so freshness is judged from the dump files on disk.  The vocabulary is
        the one the other components already use: `pending` means no dump has
        been taken yet, `unavailable` means the newest one is too old to count.
        """
        if self.backups_path is None:
            return "disabled", None
        try:
            dumps = [item for item in self.backups_path.glob("local-ai-*.dump") if item.is_file()]
            if not dumps:
                return "pending", None
            age_hours = (datetime.now(UTC).timestamp() - max(item.stat().st_mtime for item in dumps)) / 3600
        except Exception:
            return "unavailable", None
        # Half an interval of slack keeps a backup that ran a little late from
        # reading as a missing recovery point.
        return ("ok" if age_hours <= self.backup_max_age_hours * 1.5 else "unavailable"), round(age_hours, 2)

    def health(self) -> dict[str, object]:
        components: dict[str, str] = {"ollama": "ok" if self.ollama.healthcheck() else "unavailable", "qdrant": "ok" if self.qdrant.healthcheck() else "unavailable"}
        if self.sessions:
            try:
                with self.sessions() as session: session.execute(text("SELECT 1"))
                components["postgres"] = "ok"
            except Exception: components["postgres"] = "unavailable"
            try:
                redis = Redis.from_url(self.redis_url); redis.ping(); components["redis"] = "ok"
                workers = Worker.all(connection=redis)
                names = {queue for worker in workers for queue in worker.queue_names()}
                components["worker_ocr"] = "ok" if f"{self.prefix}:ocr" in names else "unavailable"
                components["worker_index"] = "ok" if f"{self.prefix}:index" in names else "unavailable"
                memory_worker = (
                    "ok"
                    if f"{self.prefix}:{self.memory_queue_name}" in names
                    else "unavailable"
                )
                components["worker_memory"] = (
                    memory_worker
                    if self.memory_ingestion_enabled
                    else "disabled"
                )
            except Exception:
                components.update(
                    {
                        "redis": "unavailable",
                        "worker_ocr": "unavailable",
                        "worker_index": "unavailable",
                        "worker_memory": (
                            "unavailable"
                            if self.memory_ingestion_enabled
                            else "disabled"
                        ),
                    }
                )
            components["memory_queue"] = (
                f"{self.prefix}:{self.memory_queue_name}"
            )
            components["memory_ingestion"] = (
                "ok"
                if self.memory_ingestion_enabled
                and components.get("worker_memory") == "ok"
                else (
                    "unavailable"
                    if self.memory_ingestion_enabled
                    else "disabled"
                )
            )
            try:
                with self.sessions() as session:
                    pending = session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.status.in_(("pending", "retrying", "processing")))) or 0
                components["outbox_dispatcher"] = "ok" if pending == 0 else "pending"
            except Exception: components["outbox_dispatcher"] = "unavailable"
            try:
                if not self.cleanup_heartbeat_path or not self.cleanup_heartbeat_path.is_file():
                    components["cleanup_worker"] = "unavailable"
                else:
                    age = datetime.now(UTC).timestamp() - self.cleanup_heartbeat_path.stat().st_mtime
                    components["cleanup_worker"] = "ok" if age < 48 * 3600 else "unavailable"
            except Exception:
                components["cleanup_worker"] = "unavailable"
            backup_status, backup_age_hours = self._backup_status()
            components["backup"] = backup_status
            if backup_age_hours is not None:
                components["backup_age_hours"] = str(backup_age_hours)
            # The dumps answer "is there a recovery point"; the heartbeat answers
            # "is anything still trying" — a stopped worker is worth seeing before
            # the newest dump ages out.
            try:
                if not self.backup_heartbeat_path or not self.backup_heartbeat_path.is_file():
                    components["backup_worker"] = "unavailable"
                else:
                    heartbeat_age = datetime.now(UTC).timestamp() - self.backup_heartbeat_path.stat().st_mtime
                    components["backup_worker"] = "ok" if heartbeat_age < self.backup_max_age_hours * 3600 * 1.5 else "unavailable"
            except Exception:
                components["backup_worker"] = "unavailable"
        required = ("postgres", "redis", "qdrant", "ollama")
        base_ok = all(components[item] == "ok" for item in required)
        memory_ok = (
            not self.memory_ingestion_enabled
            or components.get("memory_ingestion") == "ok"
        )
        return {"status": "ok" if base_ok and memory_ok else "degraded", "service": "local-ai-core", **components, "checked_at": datetime.now(UTC).isoformat()}

    def agent_activity(self, limit: int = 50) -> list[dict[str, object]]:
        """Timeline of autonomous actions (P2-4), newest first, one place:
        memory decisions (with the revert handle when still undoable), agent
        tool-using answers, and background jobs."""
        bounded = max(1, min(int(limit), 200))
        entries: list[dict[str, object]] = []
        with self.sessions() as session:
            candidates = session.scalars(
                select(DiscordMemoryCandidate)
                .where(DiscordMemoryCandidate.reviewed_at.is_not(None))
                .order_by(DiscordMemoryCandidate.reviewed_at.desc())
                .limit(bounded)
            )
            for candidate in candidates:
                memory = session.scalar(
                    select(DiscordMemory).where(DiscordMemory.origin_candidate_id == candidate.id)
                )
                applied = candidate.decision == "applied"
                # A rejected candidate WITH a canonical memory row means the
                # memory existed and was taken back: that is a revert.
                kind = "memory_apply" if applied else ("memory_revert" if memory is not None else "memory_reject")
                entries.append({
                    "at": candidate.reviewed_at.isoformat(),
                    "kind": kind,
                    "actor": candidate.reviewed_by,
                    "title": candidate.canonical_fact or "(không có nội dung)",
                    "status": candidate.decision,
                    "candidate_id": str(candidate.id),
                    "revertable": bool(applied and memory is not None and memory.status == "active"),
                })
            finals = list(
                session.scalars(
                    select(AgentTrace)
                    .where(AgentTrace.kind == "final")
                    .order_by(AgentTrace.created_at.desc())
                    .limit(bounded)
                )
            )
            message_ids = [row.message_id for row in finals if row.message_id is not None]
            tool_counts: dict[int, int] = {}
            if message_ids:
                for message_id, calls in session.execute(
                    select(AgentTrace.message_id, func.count())
                    .where(AgentTrace.message_id.in_(message_ids), AgentTrace.kind == "tool_call")
                    .group_by(AgentTrace.message_id)
                ):
                    tool_counts[message_id] = int(calls)
            for row in finals:
                entries.append({
                    "at": row.created_at.isoformat(),
                    "kind": "agent_answer",
                    "actor": "agent",
                    "title": (row.content or "")[:160],
                    "status": f"{tool_counts.get(row.message_id, 0)} lượt công cụ",
                    "candidate_id": None,
                    "revertable": False,
                })
            for job in session.scalars(select(Job).order_by(Job.updated_at.desc()).limit(bounded)):
                entries.append({
                    "at": job.updated_at.isoformat(),
                    "kind": "job",
                    "actor": "worker",
                    "title": job.job_type,
                    "status": job.status,
                    "candidate_id": None,
                    "revertable": False,
                })
        entries.sort(key=lambda item: str(item["at"]), reverse=True)
        return entries[:bounded]

    def metrics(self) -> dict[str, object]:
        result: dict[str, object] = {"generated_at": datetime.now(UTC).isoformat()}
        with self.sessions() as session:
            result.update({
                "backend": "postgres",
                "documents_indexed": session.scalar(select(func.count()).select_from(Document).where(Document.status == "indexed")) or 0,
                # Size of the sparse-index corpus, with the exact predicate the
                # BM25 snapshot uses. Plan section 9.5 reopens P4-4b partly on
                # this number crossing ~5000; until it is visible somewhere,
                # that condition is "whenever somebody happens to remember".
                "active_chunks": session.scalar(
                    select(func.count())
                    .select_from(DocumentChunk)
                    .join(Document, Document.id == DocumentChunk.document_id)
                    .join(DocumentVersion, DocumentVersion.id == Document.active_version_id)
                    .where(DocumentChunk.version_id == DocumentVersion.id, Document.status == "indexed", DocumentVersion.status == "active")
                ) or 0,
                "jobs_failed": session.scalar(select(func.count()).select_from(Job).where(Job.status == "failed")) or 0,
                "jobs_retrying": session.scalar(select(func.count()).select_from(Job).where(Job.status == "retrying")) or 0,
                "jobs_stale": session.scalar(select(func.count()).select_from(Job).where(Job.status == "running", Job.lease_expires_at < datetime.now(UTC))) or 0,
                "memory_jobs_pending": session.scalar(select(func.count()).select_from(Job).where(Job.job_type == DISCORD_MEMORY_INGEST_JOB_TYPE, Job.status == "queued")) or 0,
                "memory_jobs_retrying": session.scalar(select(func.count()).select_from(Job).where(Job.job_type == DISCORD_MEMORY_INGEST_JOB_TYPE, Job.status == "retrying")) or 0,
                "memory_jobs_failed": session.scalar(select(func.count()).select_from(Job).where(Job.job_type == DISCORD_MEMORY_INGEST_JOB_TYPE, Job.status == "failed")) or 0,
                "memory_outbox_pending": session.scalar(
                    select(func.count())
                    .select_from(OutboxEvent)
                    .join(Job, Job.id == OutboxEvent.job_id)
                    .where(
                        Job.job_type == DISCORD_MEMORY_INGEST_JOB_TYPE,
                        OutboxEvent.status == "pending",
                    )
                ) or 0,
                "memory_outbox_retrying": session.scalar(
                    select(func.count())
                    .select_from(OutboxEvent)
                    .join(Job, Job.id == OutboxEvent.job_id)
                    .where(
                        Job.job_type == DISCORD_MEMORY_INGEST_JOB_TYPE,
                        OutboxEvent.status == "retrying",
                    )
                ) or 0,
                "memory_outbox_processing": session.scalar(
                    select(func.count())
                    .select_from(OutboxEvent)
                    .join(Job, Job.id == OutboxEvent.job_id)
                    .where(
                        Job.job_type == DISCORD_MEMORY_INGEST_JOB_TYPE,
                        OutboxEvent.status == "processing",
                    )
                ) or 0,
                "ocr_pages": session.scalar(select(func.coalesce(func.sum(IngestionRun.ocr_pages), 0))) or 0,
                "runs_completed": session.scalar(select(func.count()).select_from(IngestionRun).where(IngestionRun.status == "completed")) or 0,
            })
        try:
            redis = Redis.from_url(self.redis_url)
            result["queue_length"] = {
                "ocr": Queue(f"{self.prefix}:ocr", connection=redis).count,
                "index": Queue(f"{self.prefix}:index", connection=redis).count,
                "memory": Queue(
                    f"{self.prefix}:{self.memory_queue_name}",
                    connection=redis,
                ).count,
            }
        except Exception:
            result["queue_length"] = {
                "ocr": None,
                "index": None,
                "memory": None,
            }
        # Exact per-call OCR/embedding durations are emitted as structured events
        # by workers; this endpoint intentionally avoids inventing timings from
        # incomplete stage timestamps.
        result["timing_note"] = "OCR and embedding durations are emitted in structured worker logs."
        return result
