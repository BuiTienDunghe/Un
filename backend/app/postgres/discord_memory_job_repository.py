from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.postgres.models import (
    DiscordConversationSession,
    DiscordSessionTurn,
    DiscordTurnDelivery,
    Job,
    OutboxEvent,
    new_id,
)
from app.services.job_errors import retry_delay
from app.services.job_routing import DISCORD_MEMORY_INGEST_JOB_TYPE


EligibilityReason = Literal[
    "eligible",
    "source_missing",
    "source_ineligible",
    "session_inactive",
    "delivery_missing",
    "author_missing",
    "thread_policy_disabled",
]


@dataclass(frozen=True, slots=True)
class DiscordMemorySourceSnapshot:
    turn_id: UUID
    session_id: UUID
    source_discord_message_id: str
    source_author_id: str
    source_author_display_name: str | None
    guild_id: str
    channel_id: str
    thread_id: str | None
    request_text: str
    turn_status: str
    delivery_exists: bool
    session_state: str


@dataclass(frozen=True, slots=True)
class DiscordMemoryEligibility:
    eligible: bool
    reason: EligibilityReason
    source: DiscordMemorySourceSnapshot | None = None


class DiscordMemoryJobConflictError(RuntimeError):
    pass


class DiscordMemoryJobRepository:
    """Memory job/outbox primitives inside caller-owned transactions."""

    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def job_idempotency_key(turn_id: UUID, schema_version: str) -> str:
        return (
            f"{DISCORD_MEMORY_INGEST_JOB_TYPE}:"
            f"{turn_id}:{schema_version}"
        )

    @classmethod
    def outbox_idempotency_key(
        cls,
        turn_id: UUID,
        schema_version: str,
    ) -> str:
        return f"job_enqueue:{cls.job_idempotency_key(turn_id, schema_version)}"

    def assess_source(self, turn_id: UUID) -> DiscordMemoryEligibility:
        turn = self.session.get(DiscordSessionTurn, turn_id)
        if turn is None:
            return DiscordMemoryEligibility(False, "source_missing")
        location = self.session.get(DiscordConversationSession, turn.session_id)
        if location is None:
            return DiscordMemoryEligibility(False, "source_missing")
        if turn.status != "completed":
            return DiscordMemoryEligibility(False, "source_ineligible")
        if location.status != "active":
            return DiscordMemoryEligibility(False, "session_inactive")
        if not (location.guild_id or "").strip() or not (
            location.channel_id or ""
        ).strip():
            return DiscordMemoryEligibility(False, "source_ineligible")
        if location.thread_id is not None:
            return DiscordMemoryEligibility(False, "thread_policy_disabled")
        if not (turn.author_id or "").strip():
            return DiscordMemoryEligibility(False, "author_missing")
        if not (turn.request_text or "").strip() or not (
            turn.response_text or ""
        ).strip():
            return DiscordMemoryEligibility(False, "source_ineligible")
        delivery_count = int(
            self.session.scalar(
                select(func.count())
                .select_from(DiscordTurnDelivery)
                .where(DiscordTurnDelivery.turn_id == turn.id)
            )
            or 0
        )
        if delivery_count == 0:
            return DiscordMemoryEligibility(False, "delivery_missing")
        return DiscordMemoryEligibility(
            True,
            "eligible",
            DiscordMemorySourceSnapshot(
                turn_id=turn.id,
                session_id=turn.session_id,
                source_discord_message_id=turn.discord_message_id,
                source_author_id=turn.author_id,
                source_author_display_name=turn.author_display_name,
                guild_id=location.guild_id,
                channel_id=location.channel_id,
                thread_id=location.thread_id,
                request_text=turn.request_text,
                turn_status=turn.status,
                delivery_exists=True,
                session_state=location.status,
            ),
        )

    @staticmethod
    def _expected_payload(
        turn_id: UUID,
        session_id: UUID,
        schema_version: str,
    ) -> dict[str, str]:
        return {
            "turn_id": str(turn_id),
            "session_id": str(session_id),
            "extractor_schema_version": schema_version,
        }

    def _new_job(
        self,
        *,
        turn_id: UUID,
        session_id: UUID,
        schema_version: str,
        max_attempts: int,
    ) -> Job:
        return Job(
            id=new_id("job"),
            job_type=DISCORD_MEMORY_INGEST_JOB_TYPE,
            status="queued",
            max_attempts=max_attempts,
            idempotency_key=self.job_idempotency_key(
                turn_id,
                schema_version,
            ),
            payload=self._expected_payload(
                turn_id,
                session_id,
                schema_version,
            ),
        )

    def _new_outbox(
        self,
        *,
        job: Job,
        turn_id: UUID,
        schema_version: str,
    ) -> OutboxEvent:
        return OutboxEvent(
            id=new_id("outbox"),
            event_type="JOB_ENQUEUE_REQUESTED",
            aggregate_type="job",
            aggregate_id=job.id,
            idempotency_key=self.outbox_idempotency_key(
                turn_id,
                schema_version,
            ),
            job_id=job.id,
            payload={
                "job_id": job.id,
                "job_type": DISCORD_MEMORY_INGEST_JOB_TYPE,
            },
            status="pending",
        )

    def create_job_and_outbox(
        self,
        *,
        turn_id: UUID,
        session_id: UUID,
        schema_version: str,
        max_attempts: int,
    ) -> tuple[Job, OutboxEvent, bool]:
        key = self.job_idempotency_key(turn_id, schema_version)
        event_key = self.outbox_idempotency_key(turn_id, schema_version)
        expected_payload = self._expected_payload(
            turn_id,
            session_id,
            schema_version,
        )
        self.session.flush()
        job = self.session.scalar(
            select(Job).where(Job.idempotency_key == key)
        )
        event = self.session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.idempotency_key == event_key
            )
        )
        if job is not None:
            if (
                job.job_type != DISCORD_MEMORY_INGEST_JOB_TYPE
                or job.payload != expected_payload
            ):
                raise DiscordMemoryJobConflictError(
                    "memory job idempotency key conflicts with persisted payload"
                )
            if event is None:
                event = self._new_outbox(
                    job=job,
                    turn_id=turn_id,
                    schema_version=schema_version,
                )
                self.session.add(event)
                self.session.flush()
            elif (
                event.job_id != job.id
                or event.payload.get("job_type")
                != DISCORD_MEMORY_INGEST_JOB_TYPE
            ):
                raise DiscordMemoryJobConflictError(
                    "memory outbox idempotency key conflicts with persisted job"
                )
            return job, event, False
        if event is not None:
            raise DiscordMemoryJobConflictError(
                "memory outbox exists without its deterministic job"
            )
        job = self._new_job(
            turn_id=turn_id,
            session_id=session_id,
            schema_version=schema_version,
            max_attempts=max_attempts,
        )
        self.session.add(job)
        event = self._new_outbox(
            job=job,
            turn_id=turn_id,
            schema_version=schema_version,
        )
        self.session.add(event)
        self.session.flush()
        return job, event, True

    def get_job(self, job_id: str, *, lock: bool = False) -> Job | None:
        statement = select(Job).where(
            Job.id == job_id,
            Job.job_type == DISCORD_MEMORY_INGEST_JOB_TYPE,
        )
        if lock:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def load_job_source(
        self,
        job: Job,
    ) -> tuple[DiscordMemoryEligibility, str | None]:
        payload = job.payload if isinstance(job.payload, dict) else {}
        try:
            turn_id = UUID(str(payload["turn_id"]))
            session_id = UUID(str(payload["session_id"]))
            schema_version = str(payload["extractor_schema_version"]).strip()
        except (KeyError, TypeError, ValueError):
            return DiscordMemoryEligibility(False, "source_ineligible"), None
        if not schema_version:
            return DiscordMemoryEligibility(False, "source_ineligible"), None
        eligibility = self.assess_source(turn_id)
        if (
            eligibility.source is not None
            and eligibility.source.session_id != session_id
        ):
            return DiscordMemoryEligibility(False, "source_ineligible"), None
        return eligibility, schema_version

    def claim_job(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> Job | None:
        now = datetime.now(UTC)
        claimed_id = self.session.scalar(
            update(Job)
            .where(
                Job.id == job_id,
                Job.job_type == DISCORD_MEMORY_INGEST_JOB_TYPE,
                Job.status.in_(("queued", "retrying")),
                (Job.available_at.is_(None)) | (Job.available_at <= now),
            )
            .values(
                status="running",
                worker_id=worker_id,
                started_at=func.coalesce(Job.started_at, now),
                heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                attempts=Job.attempts + 1,
                error_code=None,
                error_message=None,
            )
            .returning(Job.id)
        )
        return self.session.get(Job, claimed_id) if claimed_id else None

    def heartbeat(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> bool:
        now = datetime.now(UTC)
        result = self.session.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.job_type == DISCORD_MEMORY_INGEST_JOB_TYPE,
                Job.status == "running",
                Job.worker_id == worker_id,
                Job.lease_expires_at > now,
            )
            .values(
                heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
            )
        )
        return bool(result.rowcount)

    def complete_owned(self, job_id: str, *, worker_id: str) -> bool:
        now = datetime.now(UTC)
        result = self.session.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.job_type == DISCORD_MEMORY_INGEST_JOB_TYPE,
                Job.status == "running",
                Job.worker_id == worker_id,
                Job.lease_expires_at > now,
            )
            .values(
                status="completed",
                completed_at=now,
                worker_id=None,
                heartbeat_at=None,
                lease_expires_at=None,
                error_code=None,
                error_message=None,
            )
        )
        return bool(result.rowcount)

    def fail_owned(
        self,
        job_id: str,
        *,
        worker_id: str,
        error_code: str,
        error_message: str,
        retryable: bool,
    ) -> Literal["retrying", "failed", "ownership_lost"]:
        job = self.get_job(job_id, lock=True)
        now = datetime.now(UTC)
        if (
            job is None
            or job.status != "running"
            or job.worker_id != worker_id
            or job.lease_expires_at is None
            or job.lease_expires_at <= now
        ):
            return "ownership_lost"
        can_retry = retryable and job.attempts < job.max_attempts
        job.status = "retrying" if can_retry else "failed"
        job.error_code = error_code[:64]
        job.error_message = error_message[:1000]
        job.worker_id = None
        job.heartbeat_at = None
        job.lease_expires_at = None
        if can_retry:
            job.available_at = now + timedelta(
                seconds=retry_delay(job.attempts)
            )
        else:
            job.completed_at = now
        return "retrying" if can_retry else "failed"

    def stale_jobs(self, *, limit: int = 100) -> list[Job]:
        now = datetime.now(UTC)
        return list(
            self.session.scalars(
                select(Job)
                .where(
                    Job.job_type == DISCORD_MEMORY_INGEST_JOB_TYPE,
                    Job.status == "running",
                    Job.lease_expires_at < now,
                    Job.heartbeat_at < now,
                )
                .order_by(Job.updated_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )

    def requeue_stale(self, job: Job) -> Literal["retrying", "failed"]:
        now = datetime.now(UTC)
        job.worker_id = None
        job.heartbeat_at = None
        job.lease_expires_at = None
        job.redis_job_id = None
        job.error_code = "WORKER_STALE"
        job.error_message = "Memory worker lease expired"
        if job.attempts >= job.max_attempts:
            job.status = "failed"
            job.completed_at = now
            return "failed"
        job.status = "retrying"
        job.available_at = now + timedelta(seconds=retry_delay(job.attempts))
        event = self.session.scalar(
            select(OutboxEvent).where(OutboxEvent.job_id == job.id)
        )
        if event is not None:
            event.status = "retrying"
            event.available_at = job.available_at
            event.redis_job_id = None
            event.processed_at = None
            event.last_error = "Memory worker lease expired"
        return "retrying"
