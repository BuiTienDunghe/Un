from __future__ import annotations

import logging

from dataclasses import dataclass, replace
from uuid import UUID

from sqlalchemy.orm import sessionmaker

from app.postgres.discord_memory_job_repository import (
    DiscordMemoryJobRepository,
)
from app.postgres.discord_memory_repositories import DiscordMemoryRepository
from app.postgres.models import DiscordMemoryCandidate, DiscordSessionTurn
from app.services.discord_memory_guard import auto_apply_allowed
from app.services.discord_memory_verifier import (
    DiscordMemoryVerifierAdapter,
)
from app.services.discord_memory_review_service import (
    DiscordMemoryReviewService,
    MemoryMirrorError,
)
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

logger = logging.getLogger(__name__)


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
    """Filter and extractor worker. Canonical memory is applied only through
    the review service — by a human on the dashboard, or by the agent itself
    when the proposal's confidence clears `auto_apply_threshold` (P2-1)."""

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
        review_service: DiscordMemoryReviewService | None = None,
        auto_apply_threshold: float | None = None,
        verifier: DiscordMemoryVerifierAdapter | None = None,
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
        self.review_service = review_service
        self.auto_apply_threshold = auto_apply_threshold
        self.verifier = verifier

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
            "personal_fact": ("fact",),
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
            if schema_version != self.extractor_schema_version:
                # A vocabulary bump leaves older jobs in the queue. Their
                # version will never match, so retrying burns every attempt
                # and lands under a misleading generic code — and the old
                # check sat 90 lines lower, AFTER a candidate row had already
                # been created under the stale version (review finding 28/08).
                # Fail terminally, with a code an operator can act on.
                reason = "memory_schema_version_stale"
                result = jobs.fail_owned(
                    job_id,
                    worker_id=self.worker_id,
                    error_code="MEMORY_SCHEMA_VERSION_STALE",
                    error_message=(
                        f"job schema {schema_version} != worker "
                        f"{self.extractor_schema_version}; re-enqueue the turn "
                        "under the current version to extract it"
                    ),
                    retryable=False,
                )
                return DiscordMemoryWorkerOutcome(
                    status=result,
                    job_id=job_id,
                    reason=reason,
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
            # (The schema-version mismatch is handled terminally at the top of
            # this method, before any candidate row is written.)
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

    def verify_proposal(
        self, outcome: DiscordMemoryWorkerOutcome
    ) -> DiscordMemoryWorkerOutcome:
        """Job 4: one 1-vs-1 entailment check per fresh proposal.

        The model call runs with NO database transaction open (invariant #2);
        two short transactions bracket it — one to read the fact and its
        source, one to record the verdict. Every failure path leaves the
        candidate exactly as it was: unverified, waiting for a human.
        """
        if (
            self.verifier is None
            or outcome.candidate_id is None
            or outcome.reason != "extractor_proposal_deferred"
        ):
            return outcome
        try:
            candidate_id = UUID(outcome.candidate_id)
            with self.sessions() as database:
                candidate = database.get(DiscordMemoryCandidate, candidate_id)
                if candidate is None or not candidate.canonical_fact:
                    return outcome
                turn = database.get(DiscordSessionTurn, candidate.source_turn_id)
                fact = candidate.canonical_fact
                source_text = turn.request_text if turn is not None else ""
                guild_id = candidate.guild_id
                expected_status = candidate.validation_status
            verdict = self.verifier.verify(
                canonical_fact=fact, source_text=source_text
            )
            with self.sessions.begin() as database:
                DiscordMemoryRepository(database).update_candidate_result(
                    candidate_id,
                    guild_id=guild_id,
                    expected_validation_status=expected_status,
                    verification_method=verdict.method,
                    verification_result=verdict.result,
                )
        except Exception:
            logger.exception(
                "memory verifier step failed; candidate stays unverified"
            )
        return outcome

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

    def auto_apply(
        self, outcome: DiscordMemoryWorkerOutcome
    ) -> DiscordMemoryWorkerOutcome:
        """P2-1: apply a fresh proposal without a human when its extractor
        confidence clears the operator's threshold.

        Runs after the extraction job committed and outside any transaction.
        Every failure degrades to the P1-4 review queue — nothing is retried or
        lost, the candidate simply waits for a human. Delete-proposals never
        auto-apply: forgetting stays a human decision.

        P2-1b: the confidence threshold is only the policy switch (measured to
        be a constant 1.0 on wrong facts too); the content filter that actually
        works is the deterministic guard — evidence quoted verbatim from the
        source message and fact words present in it. Proposals failing the
        guard wait for a human instead.
        """
        try:
            if (
                self.review_service is None
                or self.auto_apply_threshold is None
                or outcome.candidate_id is None
                or outcome.reason != "extractor_proposal_deferred"
            ):
                return outcome
            candidate_id = UUID(outcome.candidate_id)
            with self.sessions() as database:
                candidate = database.get(DiscordMemoryCandidate, candidate_id)
                eligible = (
                    candidate is not None
                    and candidate.decision in ("deferred", "pending")
                    and bool(candidate.canonical_fact)
                    and bool(candidate.memory_type)
                    and candidate.operation in ("create", "update")
                    and candidate.confidence is not None
                    and float(candidate.confidence) >= self.auto_apply_threshold
                    # Job 4: with a verifier configured, autonomy additionally
                    # requires the 1-vs-1 verdict to be "entailment".
                    and (
                        self.verifier is None
                        or candidate.verification_result == "entailment"
                    )
                )
                guard_ok = False
                if eligible:
                    turn = database.get(DiscordSessionTurn, candidate.source_turn_id)
                    guard_ok = auto_apply_allowed(
                        canonical_fact=candidate.canonical_fact,
                        evidence_text=candidate.evidence_text,
                        source_text=turn.request_text if turn is not None else "",
                    )
            if not eligible:
                return outcome
            if not guard_ok:
                return replace(outcome, reason="auto_apply_guard_rejected")
            self.review_service.approve(candidate_id, reviewed_by="agent")
        except MemoryMirrorError:
            # Applied in PostgreSQL; only the web mirror failed. The dashboard
            # approve button retries just the mirror.
            return replace(outcome, reason="auto_apply_mirror_failed")
        except Exception:
            return replace(outcome, reason="auto_apply_failed")
        return replace(outcome, reason="extractor_proposal_auto_applied")

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
            return self.auto_apply(
                self.verify_proposal(self._persist_valid_result(job_id, prepared, result))
            )
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
