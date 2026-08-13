from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import sessionmaker

from app.postgres.discord_memory_job_repository import (
    DiscordMemoryJobRepository,
)
from app.postgres.discord_memory_repositories import DiscordMemoryRepository
from app.services.discord_memory_extractor import (
    DiscordMemoryExtractorAdapter,
    DiscordMemoryExtractorEnvelope,
    DiscordMemoryExtractorEnvelopeBuilder,
    DiscordMemoryExtractorOutputError,
    DiscordMemoryExtractorTransportError,
    ExtractorSource,
    ExtractorTarget,
)
from app.services.discord_memory_rule_filter import (
    DISCORD_MEMORY_RULE_FILTER_POLICY_VERSION,
    DiscordMemoryFilterInput,
    DiscordMemoryRuleFilter,
)


@dataclass(frozen=True, slots=True)
class DiscordMemoryWorkerOutcome:
    status: str
    job_id: str
    candidate_id: str | None = None
    reason: str | None = None
    created: bool = False


@dataclass(frozen=True, slots=True)
class _ExtractionPlan:
    candidate_id: UUID
    guild_id: str
    envelope: DiscordMemoryExtractorEnvelope
    created: bool


class _RuleFilterError(RuntimeError):
    pass


class DiscordMemoryWorkerService:
    """Filter and dry-run extractor worker; canonical memory is never applied."""

    def __init__(
        self,
        sessions: sessionmaker,
        *,
        worker_id: str,
        lease_seconds: int,
        rule_filter: DiscordMemoryRuleFilter | None = None,
        memory_policy_enabled: bool = True,
        extractor_enabled: bool = False,
        extractor_model: str = "qwen3.5:2b",
        extractor_schema_version: str = "v1",
        extractor: DiscordMemoryExtractorAdapter | None = None,
        envelope_builder: DiscordMemoryExtractorEnvelopeBuilder | None = None,
    ) -> None:
        self.sessions = sessions
        self.worker_id = worker_id
        self.lease_seconds = max(3, lease_seconds)
        self.rule_filter = rule_filter or DiscordMemoryRuleFilter()
        self.memory_policy_enabled = memory_policy_enabled
        self.extractor_enabled = extractor_enabled
        self.extractor_model = extractor_model
        self.extractor_schema_version = extractor_schema_version
        self.extractor = extractor
        self.envelope_builder = (
            envelope_builder or DiscordMemoryExtractorEnvelopeBuilder()
        )

    def heartbeat(self, job_id: str) -> bool:
        with self.sessions.begin() as database:
            return DiscordMemoryJobRepository(database).heartbeat(
                job_id,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
            )

    @staticmethod
    def _target_memory_types(filter_reason_code: str) -> tuple[str, ...]:
        mapping = {
            "durable_preference": ("preference",),
            "hardware_configuration": ("configuration",),
            "software_configuration": ("configuration",),
            "project_decision": ("project_decision",),
            "identity_preference": ("identity",),
            "workflow_rule": ("workflow_rule",),
            "explicit_shared_fact": ("fact",),
        }
        return mapping.get(
            filter_reason_code,
            (
                "preference",
                "configuration",
                "project_decision",
                "identity",
                "workflow_rule",
                "fact",
            ),
        )

    def _complete_without_extraction(
        self,
        *,
        jobs: DiscordMemoryJobRepository,
        job_id: str,
        candidate_id: UUID,
        created: bool,
        reason: str,
    ) -> DiscordMemoryWorkerOutcome:
        if not jobs.complete_owned(job_id, worker_id=self.worker_id):
            raise PermissionError(
                "memory worker lost job ownership before completion"
            )
        return DiscordMemoryWorkerOutcome(
            status="completed",
            job_id=job_id,
            candidate_id=str(candidate_id),
            reason=reason,
            created=created,
        )

    def _prepare(self, job_id: str) -> DiscordMemoryWorkerOutcome | _ExtractionPlan:
        with self.sessions.begin() as database:
            jobs = DiscordMemoryJobRepository(database)
            job = jobs.get_job(job_id, lock=True)
            if job is None:
                raise RuntimeError("memory job disappeared after claim")
            eligibility, schema_version = jobs.load_job_source(job)
            if (
                not eligibility.eligible
                or eligibility.source is None
                or schema_version is None
            ):
                result = jobs.fail_owned(
                    job_id,
                    worker_id=self.worker_id,
                    error_code=eligibility.reason.upper(),
                    error_message=eligibility.reason,
                    retryable=False,
                )
                return DiscordMemoryWorkerOutcome(
                    status=result,
                    job_id=job_id,
                    reason=eligibility.reason,
                )
            source = eligibility.source
            memories = DiscordMemoryRepository(database)
            candidate, created = memories.create_or_get_candidate(
                source_turn_id=source.turn_id,
                session_id=source.session_id,
                source_discord_message_id=source.source_discord_message_id,
                source_author_id=source.source_author_id,
                source_author_display_name=source.source_author_display_name,
                guild_id=source.guild_id,
                channel_id=source.channel_id,
                thread_id=source.thread_id,
                extractor_schema_version=schema_version,
                filter_decision="not_run",
                filter_reason_code="foundation_receipt_only",
            )
            filter_metadata = memories.filter_metadata(candidate)
            if not (
                filter_metadata
                and filter_metadata.get("policy_version")
                == DISCORD_MEMORY_RULE_FILTER_POLICY_VERSION
            ):
                try:
                    filter_result = self.rule_filter.evaluate(
                        DiscordMemoryFilterInput(
                            turn_id=source.turn_id,
                            source_discord_message_id=(
                                source.source_discord_message_id
                            ),
                            author_id=source.source_author_id,
                            guild_id=source.guild_id,
                            channel_id=source.channel_id,
                            thread_id=source.thread_id,
                            request_text=source.request_text,
                            turn_status=source.turn_status,
                            delivery_exists=source.delivery_exists,
                            session_state=source.session_state,
                            memory_policy_enabled=self.memory_policy_enabled,
                            thread_enabled=False,
                            source_role="user",
                        )
                    )
                except Exception as error:
                    raise _RuleFilterError(
                        "deterministic rule filter failed"
                    ) from error
                candidate, _ = memories.record_filter_result(
                    candidate.id,
                    guild_id=source.guild_id,
                    policy_version=filter_result.policy_version,
                    filter_decision=filter_result.decision,
                    filter_reason_code=filter_result.reason_code,
                    candidate_strength=filter_result.candidate_strength,
                    detected_intent=filter_result.detected_intent,
                    matched_rules=filter_result.matched_rules,
                )
                filter_metadata = memories.filter_metadata(candidate)

            if candidate.filter_decision != "candidate":
                return self._complete_without_extraction(
                    jobs=jobs,
                    job_id=job_id,
                    candidate_id=candidate.id,
                    created=created,
                    reason=f"filter_{candidate.filter_decision}",
                )

            existing_extractor = memories.extractor_state(candidate)
            if existing_extractor is not None:
                return self._complete_without_extraction(
                    jobs=jobs,
                    job_id=job_id,
                    candidate_id=candidate.id,
                    created=created,
                    reason=str(existing_extractor["stage"]),
                )

            if not self.extractor_enabled:
                memories.record_extractor_disabled(
                    candidate.id,
                    guild_id=source.guild_id,
                    extractor_model=self.extractor_model,
                    extractor_schema_version=self.extractor_schema_version,
                )
                return self._complete_without_extraction(
                    jobs=jobs,
                    job_id=job_id,
                    candidate_id=candidate.id,
                    created=created,
                    reason="extractor_disabled",
                )
            if self.extractor is None:
                raise RuntimeError(
                    "extractor is enabled but no dedicated adapter is configured"
                )
            if schema_version != self.extractor_schema_version:
                raise RuntimeError(
                    "job extractor schema does not match worker configuration"
                )
            if filter_metadata is None:
                raise RuntimeError("candidate filter metadata is unavailable")
            targets = memories.list_active_extractor_targets(
                guild_id=source.guild_id,
                subject_id=source.source_author_id,
                memory_types=self._target_memory_types(
                    str(filter_metadata["reason_code"])
                ),
            )
            envelope = self.envelope_builder.build(
                source=ExtractorSource(
                    turn_id=source.turn_id,
                    discord_message_id=source.source_discord_message_id,
                    author_id=source.source_author_id,
                    guild_id=source.guild_id,
                    channel_id=source.channel_id,
                    thread_id=source.thread_id,
                    request_text=source.request_text,
                ),
                filter_metadata=filter_metadata,
                targets=(
                    ExtractorTarget(
                        memory_id=target.memory_id,
                        fact_key=target.fact_key,
                        canonical_fact=target.canonical_fact,
                        memory_type=target.memory_type,
                        scope=target.scope,
                        version=target.version,
                    )
                    for target in targets
                ),
            )
            return _ExtractionPlan(
                candidate_id=candidate.id,
                guild_id=source.guild_id,
                envelope=envelope,
                created=created,
            )

    def _persist_valid_result(
        self,
        job_id: str,
        plan: _ExtractionPlan,
        result,
    ) -> DiscordMemoryWorkerOutcome:
        proposal = result.proposal.model_dump(mode="json")
        with self.sessions.begin() as database:
            jobs = DiscordMemoryJobRepository(database)
            job = jobs.get_job(job_id, lock=True)
            if (
                job is None
                or job.status != "running"
                or job.worker_id != self.worker_id
            ):
                raise PermissionError(
                    "memory worker lost job ownership before proposal persistence"
                )
            DiscordMemoryRepository(database).record_extractor_proposal(
                plan.candidate_id,
                guild_id=plan.guild_id,
                extractor_model=result.model,
                raw_output=result.raw_output,
                proposal=proposal,
                prompt_version=result.prompt_version,
                format_mode=result.format_mode,
                latency_ms=result.latency_ms,
                performance=result.performance,
            )
            if not jobs.complete_owned(job_id, worker_id=self.worker_id):
                raise PermissionError(
                    "memory worker lost job ownership before completion"
                )
        return DiscordMemoryWorkerOutcome(
            status="completed",
            job_id=job_id,
            candidate_id=str(plan.candidate_id),
            reason="extractor_proposal_deferred",
            created=plan.created,
        )

    def _persist_invalid_result(
        self,
        job_id: str,
        plan: _ExtractionPlan,
        error: DiscordMemoryExtractorOutputError,
    ) -> DiscordMemoryWorkerOutcome:
        with self.sessions.begin() as database:
            jobs = DiscordMemoryJobRepository(database)
            job = jobs.get_job(job_id, lock=True)
            if (
                job is None
                or job.status != "running"
                or job.worker_id != self.worker_id
            ):
                raise PermissionError(
                    "memory worker lost job ownership before rejection persistence"
                )
            DiscordMemoryRepository(database).record_extractor_rejection(
                plan.candidate_id,
                guild_id=plan.guild_id,
                extractor_model=self.extractor_model,
                extractor_schema_version=self.extractor_schema_version,
                error_code=error.error_code,
                raw_output=error.raw_output,
            )
            if not jobs.complete_owned(job_id, worker_id=self.worker_id):
                raise PermissionError(
                    "memory worker lost job ownership before completion"
                )
        return DiscordMemoryWorkerOutcome(
            status="completed",
            job_id=job_id,
            candidate_id=str(plan.candidate_id),
            reason=error.error_code,
            created=plan.created,
        )

    def _retry_failure(
        self,
        job_id: str,
        *,
        error_code: str,
        error_message: str,
    ) -> DiscordMemoryWorkerOutcome:
        with self.sessions.begin() as database:
            result = DiscordMemoryJobRepository(database).fail_owned(
                job_id,
                worker_id=self.worker_id,
                error_code=error_code,
                error_message=error_message,
                retryable=True,
            )
        if result == "ownership_lost":
            raise PermissionError("memory worker lost job ownership")
        return DiscordMemoryWorkerOutcome(
            status=result,
            job_id=job_id,
            reason=error_code.casefold(),
        )

    def process(self, job_id: str) -> DiscordMemoryWorkerOutcome:
        with self.sessions.begin() as database:
            repository = DiscordMemoryJobRepository(database)
            job = repository.claim_job(
                job_id,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
            )
            if job is None:
                existing = repository.get_job(job_id)
                return DiscordMemoryWorkerOutcome(
                    status="not_claimed",
                    job_id=job_id,
                    reason=existing.status if existing else "not_found",
                )

        try:
            prepared = self._prepare(job_id)
            if isinstance(prepared, DiscordMemoryWorkerOutcome):
                return prepared
            if self.extractor is None:
                raise RuntimeError("extractor adapter disappeared after preparation")

            # No PostgreSQL transaction is held during Ollama HTTP/model work.
            try:
                result = self.extractor.extract(prepared.envelope)
            except DiscordMemoryExtractorOutputError as error:
                return self._persist_invalid_result(job_id, prepared, error)
            return self._persist_valid_result(job_id, prepared, result)
        except DiscordMemoryExtractorTransportError as error:
            return self._retry_failure(
                job_id,
                error_code=error.error_code.upper(),
                error_message=str(error),
            )
        except _RuleFilterError as error:
            return self._retry_failure(
                job_id,
                error_code="MEMORY_RULE_FILTER_ERROR",
                error_message=str(error),
            )
        except Exception as error:
            return self._retry_failure(
                job_id,
                error_code="MEMORY_EXTRACTOR_WORKER_ERROR",
                error_message=str(error),
            )
