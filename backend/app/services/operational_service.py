"""Small operational read-model: health and metrics never change pipeline state."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from redis import Redis
from rq import Queue, Worker
from sqlalchemy import func, select, text
from sqlalchemy.orm import sessionmaker

from app.postgres.models import Document, IngestionRun, Job, OutboxEvent
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
    ) -> None:
        self.sessions, self.redis_url, self.prefix, self.qdrant, self.ollama = sessions, redis_url, prefix, qdrant, ollama
        self.cleanup_heartbeat_path = cleanup_heartbeat_path
        self.memory_ingestion_enabled = memory_ingestion_enabled
        self.memory_queue_name = memory_queue_name

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
        required = ("postgres", "redis", "qdrant", "ollama")
        base_ok = all(components[item] == "ok" for item in required)
        memory_ok = (
            not self.memory_ingestion_enabled
            or components.get("memory_ingestion") == "ok"
        )
        return {"status": "ok" if base_ok and memory_ok else "degraded", "service": "local-ai-core", **components, "checked_at": datetime.now(UTC).isoformat()}

    def metrics(self) -> dict[str, object]:
        result: dict[str, object] = {"generated_at": datetime.now(UTC).isoformat()}
        with self.sessions() as session:
            result.update({
                "backend": "postgres",
                "documents_indexed": session.scalar(select(func.count()).select_from(Document).where(Document.status == "indexed")) or 0,
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
