from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.postgres.discord_memory_job_repository import (
    DiscordMemoryEligibility,
    DiscordMemoryJobRepository,
)


@dataclass(frozen=True, slots=True)
class DiscordMemoryCompletionOutcome:
    created: bool
    eligibility: DiscordMemoryEligibility
    job_id: str | None = None
    outbox_event_id: str | None = None


class DiscordMemoryCompletionTransportError(RuntimeError):
    """Durable Job/Outbox creation failed; the whole completion must retry."""


class DiscordMemoryCompletionService:
    """Adds only durable transport records to the Discord completion commit."""

    def __init__(
        self,
        *,
        enabled: bool,
        extractor_schema_version: str,
        max_attempts: int,
    ) -> None:
        self.enabled = enabled
        self.extractor_schema_version = extractor_schema_version.strip()
        self.max_attempts = max(1, max_attempts)
        if not self.extractor_schema_version:
            raise ValueError("extractor_schema_version must not be empty")

    def on_first_completion(
        self,
        database: Session,
        turn_id: UUID,
    ) -> DiscordMemoryCompletionOutcome | None:
        if not self.enabled:
            return None
        # The session factory disables autoflush. Eligibility must observe the
        # delivery rows and completed state written earlier in this transaction.
        database.flush()
        repository = DiscordMemoryJobRepository(database)
        eligibility = repository.assess_source(turn_id)
        if not eligibility.eligible or eligibility.source is None:
            return DiscordMemoryCompletionOutcome(False, eligibility)
        try:
            job, event, created = repository.create_job_and_outbox(
                turn_id=turn_id,
                session_id=eligibility.source.session_id,
                schema_version=self.extractor_schema_version,
                max_attempts=self.max_attempts,
            )
        except Exception as error:
            # Do not let DiscordTurnService's delivery-constraint handler
            # misclassify a Job/Outbox persistence error as a delivery-ID
            # conflict. This exception leaves the caller transaction uncommitted.
            raise DiscordMemoryCompletionTransportError(
                "Discord memory Job/Outbox persistence failed"
            ) from error
        return DiscordMemoryCompletionOutcome(
            created=created,
            eligibility=eligibility,
            job_id=job.id,
            outbox_event_id=event.id,
        )
