from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.postgres.discord_memory_constants import (
    DISCORD_MEMORY_CANDIDATE_VALIDATION_STATUSES_V2,
    DISCORD_MEMORY_CANDIDATE_DECISIONS_V1,
    DISCORD_MEMORY_FILTER_DECISIONS_V3,
    DISCORD_MEMORY_FILTER_REASON_CODES_V1,
    DISCORD_MEMORY_FILTER_STRENGTHS_V1,
    DISCORD_MEMORY_OPERATIONS_V1,
    DISCORD_MEMORY_SCOPES_V1,
    DISCORD_MEMORY_SOURCE_ROLES_V1,
    DISCORD_MEMORY_VERIFICATION_RESULTS_V1,
)
from app.postgres.models import (
    DiscordConversationSession,
    DiscordMemory,
    DiscordMemoryCandidate,
    DiscordMemorySource,
    DiscordSessionTurn,
)


class DiscordMemoryConflictError(RuntimeError):
    """An idempotency key or canonical identity conflicts with stored data."""


class DiscordMemoryNotFoundError(LookupError):
    """A required Discord-memory entity does not exist in the requested guild."""


@dataclass(frozen=True, slots=True)
class DiscordMemoryExtractorTarget:
    memory_id: UUID
    fact_key: str
    canonical_fact: str
    memory_type: str
    scope: str
    version: int


@dataclass(frozen=True, slots=True)
class DiscordMemoryIdentity:
    guild_id: str
    scope: str
    subject_type: str
    subject_id: str
    fact_key: str
    channel_id: str | None = None
    thread_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("guild_id", "subject_type", "subject_id", "fact_key"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must not be empty")
        if self.scope not in DISCORD_MEMORY_SCOPES_V1:
            raise ValueError(f"unsupported Discord memory scope: {self.scope}")
        if self.scope in {"member_in_guild", "guild"}:
            valid_location = self.channel_id is None and self.thread_id is None
        elif self.scope == "channel":
            valid_location = bool(self.channel_id) and self.thread_id is None
        else:
            valid_location = bool(self.channel_id) and bool(self.thread_id)
        if not valid_location:
            raise ValueError(f"invalid location for Discord memory scope {self.scope}")

    def lock_material(self) -> str:
        return "\x1f".join(
            (
                self.guild_id,
                self.scope,
                self.channel_id or "",
                self.thread_id or "",
                self.subject_type,
                self.subject_id,
                self.fact_key,
            )
        )


class DiscordMemoryRepository:
    """Caller-transaction-owned persistence for the isolated Discord domain."""

    _CANDIDATE_RESULT_FIELDS = frozenset(
        {
            "extractor_model",
            "raw_output",
            "normalized_output",
            "operation",
            "memory_type",
            "subject_type",
            "subject_id",
            "scope",
            "fact_key",
            "canonical_fact",
            "evidence_text",
            "confidence",
            "target_memory_id",
            "validation_status",
            "decision",
            "conflict_key",
            "proposed_value_hash",
            "not_before",
            "expires_at",
            "error_code",
            "error_message",
            "reviewed_at",
            "reviewed_by",
            "verification_method",
            "verification_result",
        }
    )

    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def _candidate_identity(candidate: DiscordMemoryCandidate) -> tuple[Any, ...]:
        # Display names are snapshots, never identity.
        return (
            candidate.source_turn_id,
            candidate.session_id,
            candidate.source_discord_message_id,
            candidate.source_author_id,
            candidate.guild_id,
            candidate.channel_id,
            candidate.thread_id,
            candidate.extractor_schema_version,
        )

    @staticmethod
    def _requested_candidate_identity(
        *,
        source_turn_id: UUID,
        session_id: UUID,
        source_discord_message_id: str,
        source_author_id: str,
        guild_id: str,
        channel_id: str,
        thread_id: str | None,
        extractor_schema_version: str,
    ) -> tuple[Any, ...]:
        return (
            source_turn_id,
            session_id,
            source_discord_message_id,
            source_author_id,
            guild_id,
            channel_id,
            thread_id,
            extractor_schema_version,
        )

    def _validate_source_identity(
        self,
        *,
        source_turn_id: UUID,
        session_id: UUID,
        source_discord_message_id: str,
        source_author_id: str,
        guild_id: str,
        channel_id: str,
        thread_id: str | None,
    ) -> None:
        turn = self.session.get(DiscordSessionTurn, source_turn_id)
        location = self.session.get(DiscordConversationSession, session_id)
        if turn is None or location is None or turn.session_id != session_id:
            raise DiscordMemoryNotFoundError("source turn/session pair was not found")
        if (
            turn.discord_message_id != source_discord_message_id
            or turn.author_id != source_author_id
            or location.guild_id != guild_id
            or location.channel_id != channel_id
            or location.thread_id != thread_id
        ):
            raise DiscordMemoryConflictError(
                "candidate source identity does not match the persisted Discord turn"
            )

    def _find_candidate_by_keys(
        self,
        *,
        source_turn_id: UUID,
        source_discord_message_id: str,
        extractor_schema_version: str,
    ) -> DiscordMemoryCandidate | None:
        by_turn = self.session.scalar(
            select(DiscordMemoryCandidate).where(
                DiscordMemoryCandidate.source_turn_id == source_turn_id,
                DiscordMemoryCandidate.extractor_schema_version
                == extractor_schema_version,
            )
        )
        by_message = self.session.scalar(
            select(DiscordMemoryCandidate).where(
                DiscordMemoryCandidate.source_discord_message_id
                == source_discord_message_id,
                DiscordMemoryCandidate.extractor_schema_version
                == extractor_schema_version,
            )
        )
        if by_turn is not None and by_message is not None and by_turn.id != by_message.id:
            raise DiscordMemoryConflictError(
                "turn and Discord-message idempotency keys identify different candidates"
            )
        return by_turn or by_message

    def create_or_get_candidate(
        self,
        *,
        source_turn_id: UUID,
        session_id: UUID,
        source_discord_message_id: str,
        source_author_id: str,
        source_author_display_name: str | None,
        guild_id: str,
        channel_id: str,
        thread_id: str | None,
        extractor_schema_version: str,
        filter_decision: str,
        filter_reason_code: str,
    ) -> tuple[DiscordMemoryCandidate, bool]:
        if filter_decision not in DISCORD_MEMORY_FILTER_DECISIONS_V3:
            raise ValueError("invalid filter_decision")
        self._validate_source_identity(
            source_turn_id=source_turn_id,
            session_id=session_id,
            source_discord_message_id=source_discord_message_id,
            source_author_id=source_author_id,
            guild_id=guild_id,
            channel_id=channel_id,
            thread_id=thread_id,
        )
        requested_identity = self._requested_candidate_identity(
            source_turn_id=source_turn_id,
            session_id=session_id,
            source_discord_message_id=source_discord_message_id,
            source_author_id=source_author_id,
            guild_id=guild_id,
            channel_id=channel_id,
            thread_id=thread_id,
            extractor_schema_version=extractor_schema_version,
        )
        existing = self._find_candidate_by_keys(
            source_turn_id=source_turn_id,
            source_discord_message_id=source_discord_message_id,
            extractor_schema_version=extractor_schema_version,
        )
        if existing is not None:
            if self._candidate_identity(existing) != requested_identity:
                raise DiscordMemoryConflictError(
                    "candidate idempotency key was reused with different source identity"
                )
            return existing, False

        now = datetime.now(UTC)
        candidate = DiscordMemoryCandidate(
            id=uuid4(),
            source_turn_id=source_turn_id,
            session_id=session_id,
            source_discord_message_id=source_discord_message_id,
            source_author_id=source_author_id,
            source_author_display_name=source_author_display_name,
            guild_id=guild_id,
            channel_id=channel_id,
            thread_id=thread_id,
            extractor_schema_version=extractor_schema_version,
            filter_decision=filter_decision,
            filter_reason_code=filter_reason_code,
            validation_status="pending",
            decision={
                "candidate": "pending",
                "no_op": "no_op",
                "not_run": "deferred",
                "rejected_policy": "rejected",
            }[filter_decision],
            created_at=now,
            updated_at=now,
        )
        try:
            with self.session.begin_nested():
                self.session.add(candidate)
                self.session.flush()
        except IntegrityError:
            existing = self._find_candidate_by_keys(
                source_turn_id=source_turn_id,
                source_discord_message_id=source_discord_message_id,
                extractor_schema_version=extractor_schema_version,
            )
            if (
                existing is None
                or self._candidate_identity(existing) != requested_identity
            ):
                raise DiscordMemoryConflictError(
                    "candidate idempotency conflict"
                ) from None
            return existing, False
        return candidate, True

    def get_candidate(
        self,
        candidate_id: UUID,
        *,
        guild_id: str,
    ) -> DiscordMemoryCandidate | None:
        if not guild_id:
            raise ValueError("guild_id is required")
        return self.session.scalar(
            select(DiscordMemoryCandidate).where(
                DiscordMemoryCandidate.id == candidate_id,
                DiscordMemoryCandidate.guild_id == guild_id,
            )
        )

    def get_candidate_by_source(
        self,
        source_turn_id: UUID,
        extractor_schema_version: str,
        *,
        guild_id: str,
    ) -> DiscordMemoryCandidate | None:
        if not guild_id:
            raise ValueError("guild_id is required")
        return self.session.scalar(
            select(DiscordMemoryCandidate).where(
                DiscordMemoryCandidate.source_turn_id == source_turn_id,
                DiscordMemoryCandidate.extractor_schema_version
                == extractor_schema_version,
                DiscordMemoryCandidate.guild_id == guild_id,
            )
        )

    def update_candidate_result(
        self,
        candidate_id: UUID,
        *,
        guild_id: str,
        expected_validation_status: str,
        **changes: Any,
    ) -> tuple[DiscordMemoryCandidate, bool]:
        unknown = set(changes) - self._CANDIDATE_RESULT_FIELDS
        if unknown:
            raise ValueError(f"unsupported candidate result fields: {sorted(unknown)}")
        if "operation" in changes and changes["operation"] not in (
            None,
            *DISCORD_MEMORY_OPERATIONS_V1,
        ):
            raise ValueError("invalid operation")
        if "scope" in changes and changes["scope"] not in (
            None,
            *DISCORD_MEMORY_SCOPES_V1,
        ):
            raise ValueError("invalid scope")
        if (
            "validation_status" in changes
            and changes["validation_status"]
            not in DISCORD_MEMORY_CANDIDATE_VALIDATION_STATUSES_V2
        ):
            raise ValueError("invalid validation_status")
        if (
            "decision" in changes
            and changes["decision"] not in DISCORD_MEMORY_CANDIDATE_DECISIONS_V1
        ):
            raise ValueError("invalid decision")
        if "verification_result" in changes and changes["verification_result"] not in (
            None,
            *DISCORD_MEMORY_VERIFICATION_RESULTS_V1,
        ):
            raise ValueError("invalid verification_result")

        candidate = self.session.scalar(
            select(DiscordMemoryCandidate)
            .where(
                DiscordMemoryCandidate.id == candidate_id,
                DiscordMemoryCandidate.guild_id == guild_id,
            )
            .with_for_update()
        )
        if candidate is None:
            raise DiscordMemoryNotFoundError(str(candidate_id))
        if all(getattr(candidate, key) == value for key, value in changes.items()):
            return candidate, False
        if candidate.validation_status != expected_validation_status:
            raise DiscordMemoryConflictError(
                "candidate changed after the caller's expected state"
            )
        for key, value in changes.items():
            setattr(candidate, key, value)
        candidate.updated_at = datetime.now(UTC)
        self.session.flush()
        return candidate, True

    def record_filter_result(
        self,
        candidate_id: UUID,
        *,
        guild_id: str,
        policy_version: str,
        filter_decision: str,
        filter_reason_code: str,
        candidate_strength: str,
        detected_intent: str,
        matched_rules: tuple[str, ...],
    ) -> tuple[DiscordMemoryCandidate, bool]:
        if filter_decision not in {
            "candidate",
            "no_op",
            "rejected_policy",
        }:
            raise ValueError("invalid terminal filter_decision")
        if filter_reason_code not in DISCORD_MEMORY_FILTER_REASON_CODES_V1:
            raise ValueError("invalid filter_reason_code")
        if candidate_strength not in DISCORD_MEMORY_FILTER_STRENGTHS_V1:
            raise ValueError("invalid candidate_strength")
        if not policy_version.strip():
            raise ValueError("policy_version is required")

        metadata = {
            "stage": "rule_filter",
            "policy_version": policy_version,
            "decision": filter_decision,
            "reason_code": filter_reason_code,
            "candidate_strength": candidate_strength,
            "detected_intent": detected_intent,
            "matched_rules": list(matched_rules),
        }
        candidate = self.session.scalar(
            select(DiscordMemoryCandidate)
            .where(
                DiscordMemoryCandidate.id == candidate_id,
                DiscordMemoryCandidate.guild_id == guild_id,
            )
            .with_for_update()
        )
        if candidate is None:
            raise DiscordMemoryNotFoundError(str(candidate_id))

        stored = (
            candidate.normalized_output
            if isinstance(candidate.normalized_output, dict)
            else None
        )
        if stored is not None and stored.get("stage") == "rule_filter":
            if stored == metadata:
                return candidate, False
            raise DiscordMemoryConflictError(
                "candidate already has a different rule-filter result"
            )
        if (
            candidate.filter_decision != "not_run"
            or candidate.filter_reason_code != "foundation_receipt_only"
            or candidate.validation_status != "pending"
            or candidate.decision != "deferred"
        ):
            raise DiscordMemoryConflictError(
                "candidate is not an unfiltered foundation receipt"
            )

        candidate.filter_decision = filter_decision
        candidate.filter_reason_code = filter_reason_code
        candidate.normalized_output = metadata
        if filter_decision == "candidate":
            candidate.validation_status = "pending"
            candidate.decision = "deferred"
        elif filter_decision == "no_op":
            candidate.validation_status = "not_required"
            candidate.decision = "no_op"
        else:
            candidate.validation_status = "rejected"
            candidate.decision = "rejected"
        candidate.updated_at = datetime.now(UTC)
        self.session.flush()
        return candidate, True

    @staticmethod
    def filter_metadata(
        candidate: DiscordMemoryCandidate,
    ) -> dict[str, Any] | None:
        stored = (
            candidate.normalized_output
            if isinstance(candidate.normalized_output, dict)
            else None
        )
        if stored is None:
            return None
        if stored.get("stage") == "rule_filter":
            return stored
        nested = stored.get("rule_filter")
        return nested if isinstance(nested, dict) else None

    @staticmethod
    def extractor_state(
        candidate: DiscordMemoryCandidate,
    ) -> dict[str, Any] | None:
        stored = (
            candidate.normalized_output
            if isinstance(candidate.normalized_output, dict)
            else None
        )
        if stored is None:
            return None
        for key in ("extractor_proposal", "extractor_error", "extractor"):
            value = stored.get(key)
            if isinstance(value, dict):
                return {"stage": key, **value}
        return None

    def list_active_extractor_targets(
        self,
        *,
        guild_id: str,
        subject_id: str,
        memory_types: tuple[str, ...] | None = None,
        limit: int = 20,
    ) -> list[DiscordMemoryExtractorTarget]:
        if not guild_id or not subject_id:
            raise ValueError("guild_id and subject_id are required")
        bounded_limit = max(1, min(limit, 20))
        supported_types = (
            "preference",
            "configuration",
            "project_decision",
            "identity",
            "workflow_rule",
            "fact",
        )
        selected_types = tuple(memory_types or supported_types)
        if not selected_types or any(
            value not in supported_types for value in selected_types
        ):
            raise ValueError("extractor target memory_types are invalid")
        rows = self.session.scalars(
            select(DiscordMemory)
            .where(
                DiscordMemory.guild_id == guild_id,
                DiscordMemory.scope == "member_in_guild",
                DiscordMemory.subject_type.in_(("member", "discord_member")),
                DiscordMemory.subject_id == subject_id,
                DiscordMemory.status == "active",
                DiscordMemory.memory_type.in_(selected_types),
            )
            .order_by(DiscordMemory.updated_at.desc(), DiscordMemory.id)
            .limit(bounded_limit)
        )
        return [
            DiscordMemoryExtractorTarget(
                memory_id=memory.id,
                fact_key=memory.fact_key,
                canonical_fact=memory.canonical_fact,
                memory_type=memory.memory_type,
                scope=memory.scope,
                version=memory.version,
            )
            for memory in rows
        ]

    def list_active_context_memories(
        self,
        *,
        guild_id: str,
        subject_id: str | None,
        limit: int = 10,
    ) -> list[DiscordMemory]:
        """Active facts for the ANSWER path: this member's facts plus
        guild-wide facts, ledger-only.

        This is the read the constrained ledger was built for and never had
        (memory_design.md §3): every filter the Qdrant mirror lacks — guild,
        subject, status — is applied here in SQL. Zero model calls; the
        single-active-row indexes guarantee at most one row per fact key.
        """
        bounded_limit = max(1, min(int(limit), 20))
        if not guild_id:
            return []
        scope_clauses = [DiscordMemory.scope == "guild"]
        if subject_id:
            scope_clauses.append(
                and_(
                    DiscordMemory.scope == "member_in_guild",
                    DiscordMemory.subject_type.in_(("member", "discord_member")),
                    DiscordMemory.subject_id == subject_id,
                )
            )
        return list(
            self.session.scalars(
                select(DiscordMemory)
                .where(
                    DiscordMemory.guild_id == guild_id,
                    DiscordMemory.status == "active",
                    or_(*scope_clauses),
                )
                .order_by(DiscordMemory.updated_at.desc(), DiscordMemory.id)
                .limit(bounded_limit)
            )
        )

    def _candidate_for_extractor(
        self,
        candidate_id: UUID,
        *,
        guild_id: str,
    ) -> tuple[DiscordMemoryCandidate, dict[str, Any]]:
        candidate = self.session.scalar(
            select(DiscordMemoryCandidate)
            .where(
                DiscordMemoryCandidate.id == candidate_id,
                DiscordMemoryCandidate.guild_id == guild_id,
            )
            .with_for_update()
        )
        if candidate is None:
            raise DiscordMemoryNotFoundError(str(candidate_id))
        filter_metadata = self.filter_metadata(candidate)
        if (
            candidate.filter_decision != "candidate"
            or filter_metadata is None
            or filter_metadata.get("decision") != "candidate"
        ):
            raise DiscordMemoryConflictError(
                "extractor can only process a terminal candidate filter result"
            )
        return candidate, filter_metadata

    def record_extractor_disabled(
        self,
        candidate_id: UUID,
        *,
        guild_id: str,
        extractor_model: str,
        extractor_schema_version: str,
    ) -> tuple[DiscordMemoryCandidate, bool]:
        candidate, filter_metadata = self._candidate_for_extractor(
            candidate_id,
            guild_id=guild_id,
        )
        metadata = {
            "status": "disabled",
            "reason_code": "extractor_disabled",
            "model": extractor_model,
            "schema_version": extractor_schema_version,
        }
        expected = {
            "rule_filter": filter_metadata,
            "extractor": metadata,
        }
        if candidate.normalized_output == expected:
            return candidate, False
        if self.extractor_state(candidate) is not None:
            raise DiscordMemoryConflictError(
                "candidate already has a different extractor state"
            )
        candidate.normalized_output = expected
        candidate.extractor_model = extractor_model
        candidate.error_code = "extractor_disabled"
        candidate.error_message = None
        candidate.validation_status = "pending"
        candidate.decision = "deferred"
        candidate.updated_at = datetime.now(UTC)
        self.session.flush()
        return candidate, True

    def record_extractor_proposal(
        self,
        candidate_id: UUID,
        *,
        guild_id: str,
        extractor_model: str,
        raw_output: dict[str, Any],
        proposal: dict[str, Any],
        prompt_version: str,
        format_mode: str,
        latency_ms: int,
        performance: dict[str, int] | None = None,
    ) -> tuple[DiscordMemoryCandidate, bool]:
        candidate, filter_metadata = self._candidate_for_extractor(
            candidate_id,
            guild_id=guild_id,
        )
        expected = {
            "rule_filter": filter_metadata,
            "extractor_proposal": proposal,
            "extractor_audit": {
                "prompt_version": prompt_version,
                "format_mode": format_mode,
                "latency_ms": latency_ms,
                "performance": performance or {},
            },
        }
        existing_output = (
            candidate.normalized_output
            if isinstance(candidate.normalized_output, dict)
            else {}
        )
        if (
            existing_output.get("extractor_proposal") == proposal
            and candidate.raw_output == raw_output
        ):
            return candidate, False
        if self.extractor_state(candidate) is not None:
            raise DiscordMemoryConflictError(
                "candidate already has a different terminal extractor result"
            )

        target = proposal.get("target_memory_id")
        candidate.extractor_model = extractor_model
        candidate.raw_output = raw_output
        candidate.normalized_output = expected
        candidate.operation = proposal.get("operation")
        candidate.memory_type = proposal.get("memory_type")
        candidate.subject_type = proposal.get("subject_type")
        candidate.subject_id = proposal.get("subject_id")
        candidate.scope = proposal.get("scope")
        candidate.fact_key = proposal.get("fact_key")
        candidate.canonical_fact = proposal.get("canonical_fact")
        candidate.evidence_text = proposal.get("evidence_text")
        confidence = proposal.get("confidence")
        candidate.confidence = (
            Decimal(str(confidence)) if confidence is not None else None
        )
        candidate.target_memory_id = UUID(str(target)) if target else None
        candidate.validation_status = "pending"
        candidate.decision = "deferred"
        candidate.error_code = None
        candidate.error_message = None
        candidate.updated_at = datetime.now(UTC)
        self.session.flush()
        return candidate, True

    def record_extractor_rejection(
        self,
        candidate_id: UUID,
        *,
        guild_id: str,
        extractor_model: str,
        extractor_schema_version: str,
        error_code: str,
        raw_output: dict[str, Any] | None,
    ) -> tuple[DiscordMemoryCandidate, bool]:
        candidate, filter_metadata = self._candidate_for_extractor(
            candidate_id,
            guild_id=guild_id,
        )
        metadata = {
            "status": "rejected",
            "error_code": error_code[:120],
            "model": extractor_model,
            "schema_version": extractor_schema_version,
        }
        expected = {
            "rule_filter": filter_metadata,
            "extractor_error": metadata,
        }
        if (
            candidate.normalized_output == expected
            and candidate.raw_output == raw_output
        ):
            return candidate, False
        if self.extractor_state(candidate) is not None:
            raise DiscordMemoryConflictError(
                "candidate already has a different terminal extractor result"
            )
        candidate.extractor_model = extractor_model
        candidate.raw_output = raw_output
        candidate.normalized_output = expected
        candidate.validation_status = "rejected"
        candidate.decision = "rejected"
        candidate.error_code = error_code[:120]
        candidate.error_message = None
        candidate.updated_at = datetime.now(UTC)
        self.session.flush()
        return candidate, True

    @staticmethod
    def _identity_predicate(identity: DiscordMemoryIdentity):
        predicates = [
            DiscordMemory.guild_id == identity.guild_id,
            DiscordMemory.scope == identity.scope,
            DiscordMemory.subject_type == identity.subject_type,
            DiscordMemory.subject_id == identity.subject_id,
            DiscordMemory.fact_key == identity.fact_key,
        ]
        predicates.append(
            DiscordMemory.channel_id.is_(None)
            if identity.channel_id is None
            else DiscordMemory.channel_id == identity.channel_id
        )
        predicates.append(
            DiscordMemory.thread_id.is_(None)
            if identity.thread_id is None
            else DiscordMemory.thread_id == identity.thread_id
        )
        return and_(*predicates)

    def _lock_identity(self, identity: DiscordMemoryIdentity) -> None:
        # The hash is only a transaction-local advisory-lock key. Canonical
        # identity remains the full trusted field tuple in PostgreSQL.
        lock_key = int.from_bytes(
            sha256(identity.lock_material().encode("utf-8")).digest()[:8],
            "big",
            signed=True,
        )
        self.session.execute(select(func.pg_advisory_xact_lock(lock_key)))

    def get_active_memory(
        self,
        identity: DiscordMemoryIdentity,
        *,
        lock: bool = False,
    ) -> DiscordMemory | None:
        statement = select(DiscordMemory).where(
            self._identity_predicate(identity),
            DiscordMemory.status == "active",
        )
        if lock:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def version_history(
        self,
        identity: DiscordMemoryIdentity,
    ) -> list[DiscordMemory]:
        return list(
            self.session.scalars(
                select(DiscordMemory)
                .where(self._identity_predicate(identity))
                .order_by(DiscordMemory.version)
            )
        )

    def _candidate_for_memory(
        self,
        candidate_id: UUID,
        identity: DiscordMemoryIdentity,
    ) -> DiscordMemoryCandidate:
        candidate = self.get_candidate(candidate_id, guild_id=identity.guild_id)
        if candidate is None:
            raise DiscordMemoryNotFoundError(str(candidate_id))
        return candidate

    def _memory_from_origin(
        self,
        candidate_id: UUID,
    ) -> DiscordMemory | None:
        return self.session.scalar(
            select(DiscordMemory).where(
                DiscordMemory.origin_candidate_id == candidate_id
            )
        )

    def _same_memory_payload(
        self,
        memory: DiscordMemory,
        identity: DiscordMemoryIdentity,
        *,
        canonical_fact: str,
        memory_type: str,
    ) -> bool:
        return (
            memory.guild_id == identity.guild_id
            and memory.scope == identity.scope
            and memory.subject_type == identity.subject_type
            and memory.subject_id == identity.subject_id
            and memory.fact_key == identity.fact_key
            and memory.channel_id == identity.channel_id
            and memory.thread_id == identity.thread_id
            and memory.canonical_fact == canonical_fact
            and memory.memory_type == memory_type
        )

    def create_active_version(
        self,
        *,
        candidate_id: UUID,
        identity: DiscordMemoryIdentity,
        canonical_fact: str,
        memory_type: str,
        extractor_model: str,
        extractor_schema_version: str,
        validation_status: str = "accepted",
        source_role: str = "primary",
        evidence_hash: str,
        expires_at: datetime | None = None,
    ) -> tuple[DiscordMemory, bool]:
        candidate = self._candidate_for_memory(candidate_id, identity)
        self._lock_identity(identity)
        existing_origin = self._memory_from_origin(candidate_id)
        if existing_origin is not None:
            if not self._same_memory_payload(
                existing_origin,
                identity,
                canonical_fact=canonical_fact,
                memory_type=memory_type,
            ):
                raise DiscordMemoryConflictError(
                    "candidate already produced a different memory"
                )
            return existing_origin, False
        if self.get_active_memory(identity, lock=True) is not None:
            raise DiscordMemoryConflictError("canonical identity already has an active memory")
        if self.version_history(identity):
            raise DiscordMemoryConflictError(
                "create_active_version only creates the first canonical version"
            )
        now = datetime.now(UTC)
        memory = DiscordMemory(
            id=uuid4(),
            guild_id=identity.guild_id,
            scope=identity.scope,
            subject_type=identity.subject_type,
            subject_id=identity.subject_id,
            channel_id=identity.channel_id,
            thread_id=identity.thread_id,
            memory_type=memory_type,
            fact_key=identity.fact_key,
            canonical_fact=canonical_fact,
            status="active",
            version=1,
            origin_candidate_id=candidate.id,
            valid_from=now,
            expires_at=expires_at,
            extractor_model=extractor_model,
            extractor_schema_version=extractor_schema_version,
            validation_status=validation_status,
            index_status="pending",
            created_at=now,
            updated_at=now,
        )
        self.session.add(memory)
        candidate.decision = "applied"
        candidate.updated_at = now
        self.attach_source(
            memory=memory,
            candidate=candidate,
            source_role=source_role,
            evidence_hash=evidence_hash,
        )
        self.session.flush()
        return memory, True

    def supersede_active_version(
        self,
        *,
        candidate_id: UUID,
        identity: DiscordMemoryIdentity,
        canonical_fact: str,
        memory_type: str,
        extractor_model: str,
        extractor_schema_version: str,
        validation_status: str = "accepted",
        source_role: str = "correction",
        evidence_hash: str,
        expected_active_memory_id: UUID | None = None,
        expires_at: datetime | None = None,
    ) -> tuple[DiscordMemory, bool]:
        candidate = self._candidate_for_memory(candidate_id, identity)
        self._lock_identity(identity)
        existing_origin = self._memory_from_origin(candidate_id)
        if existing_origin is not None:
            if not self._same_memory_payload(
                existing_origin,
                identity,
                canonical_fact=canonical_fact,
                memory_type=memory_type,
            ):
                raise DiscordMemoryConflictError(
                    "candidate already produced a different memory version"
                )
            return existing_origin, False

        active = self.get_active_memory(identity, lock=True)
        if active is None:
            raise DiscordMemoryNotFoundError("active canonical memory was not found")
        if (
            expected_active_memory_id is not None
            and active.id != expected_active_memory_id
        ):
            raise DiscordMemoryConflictError("active memory changed concurrently")
        next_version = int(
            self.session.scalar(
                select(func.max(DiscordMemory.version)).where(
                    self._identity_predicate(identity)
                )
            )
            or 0
        ) + 1
        now = datetime.now(UTC)
        active.status = "superseded"
        active.valid_until = now
        active.updated_at = now
        memory = DiscordMemory(
            id=uuid4(),
            guild_id=identity.guild_id,
            scope=identity.scope,
            subject_type=identity.subject_type,
            subject_id=identity.subject_id,
            channel_id=identity.channel_id,
            thread_id=identity.thread_id,
            memory_type=memory_type,
            fact_key=identity.fact_key,
            canonical_fact=canonical_fact,
            status="active",
            version=next_version,
            origin_candidate_id=candidate.id,
            supersedes_memory_id=active.id,
            valid_from=now,
            expires_at=expires_at,
            extractor_model=extractor_model,
            extractor_schema_version=extractor_schema_version,
            validation_status=validation_status,
            index_status="pending",
            created_at=now,
            updated_at=now,
        )
        self.session.add(memory)
        candidate.target_memory_id = active.id
        candidate.decision = "applied"
        candidate.updated_at = now
        self.attach_source(
            memory=memory,
            candidate=candidate,
            source_role=source_role,
            evidence_hash=evidence_hash,
        )
        self.session.flush()
        return memory, True

    def revive_version(
        self,
        *,
        candidate_id: UUID,
        identity: DiscordMemoryIdentity,
        canonical_fact: str,
        memory_type: str,
        extractor_model: str,
        extractor_schema_version: str,
        validation_status: str = "accepted",
        source_role: str = "primary",
        evidence_hash: str,
        expires_at: datetime | None = None,
    ) -> tuple[DiscordMemory, bool]:
        """Next canonical version for an identity whose history ended without
        an active row (reverted or forgotten). `create_active_version` refuses
        identities with history and `supersede_active_version` demands a live
        predecessor, so without this path a reverted fact could never be
        learned again (P2-1)."""
        candidate = self._candidate_for_memory(candidate_id, identity)
        self._lock_identity(identity)
        existing_origin = self._memory_from_origin(candidate_id)
        if existing_origin is not None:
            if not self._same_memory_payload(
                existing_origin,
                identity,
                canonical_fact=canonical_fact,
                memory_type=memory_type,
            ):
                raise DiscordMemoryConflictError(
                    "candidate already produced a different memory version"
                )
            return existing_origin, False
        if self.get_active_memory(identity, lock=True) is not None:
            raise DiscordMemoryConflictError(
                "canonical identity already has an active memory"
            )
        history = self.version_history(identity)
        if not history:
            raise DiscordMemoryConflictError(
                "revive_version needs prior canonical history"
            )
        now = datetime.now(UTC)
        memory = DiscordMemory(
            id=uuid4(),
            guild_id=identity.guild_id,
            scope=identity.scope,
            subject_type=identity.subject_type,
            subject_id=identity.subject_id,
            channel_id=identity.channel_id,
            thread_id=identity.thread_id,
            memory_type=memory_type,
            fact_key=identity.fact_key,
            canonical_fact=canonical_fact,
            status="active",
            version=history[-1].version + 1,
            origin_candidate_id=candidate.id,
            supersedes_memory_id=history[-1].id,
            valid_from=now,
            expires_at=expires_at,
            extractor_model=extractor_model,
            extractor_schema_version=extractor_schema_version,
            validation_status=validation_status,
            index_status="pending",
            created_at=now,
            updated_at=now,
        )
        self.session.add(memory)
        candidate.target_memory_id = history[-1].id
        candidate.decision = "applied"
        candidate.updated_at = now
        self.attach_source(
            memory=memory,
            candidate=candidate,
            source_role=source_role,
            evidence_hash=evidence_hash,
        )
        self.session.flush()
        return memory, True

    def mark_deleted(
        self,
        *,
        candidate_id: UUID,
        identity: DiscordMemoryIdentity,
        evidence_hash: str,
    ) -> DiscordMemory:
        candidate = self._candidate_for_memory(candidate_id, identity)
        self._lock_identity(identity)
        active = self.get_active_memory(identity, lock=True)
        if active is None:
            raise DiscordMemoryNotFoundError("active canonical memory was not found")
        now = datetime.now(UTC)
        active.status = "deleted"
        active.valid_until = now
        active.deleted_at = now
        active.index_status = "pending_reindex"
        active.updated_at = now
        candidate.target_memory_id = active.id
        candidate.decision = "applied"
        candidate.updated_at = now
        self.attach_source(
            memory=active,
            candidate=candidate,
            source_role="forget_request",
            evidence_hash=evidence_hash,
        )
        self.session.flush()
        return active

    def attach_source(
        self,
        *,
        memory: DiscordMemory,
        candidate: DiscordMemoryCandidate,
        source_role: str,
        evidence_hash: str,
    ) -> tuple[DiscordMemorySource, bool]:
        if source_role not in DISCORD_MEMORY_SOURCE_ROLES_V1:
            raise ValueError("invalid source_role")
        if memory.guild_id != candidate.guild_id:
            raise DiscordMemoryConflictError(
                "a candidate cannot be attached across Discord guilds"
            )
        # The project session factory disables autoflush. Flush earlier source
        # work so a second attachment in the same transaction is idempotent,
        # not deferred to a UNIQUE violation at commit.
        self.session.flush()
        existing = self.session.scalar(
            select(DiscordMemorySource).where(
                DiscordMemorySource.memory_id == memory.id,
                DiscordMemorySource.source_turn_id == candidate.source_turn_id,
                DiscordMemorySource.source_role == source_role,
            )
        )
        if existing is not None:
            if (
                existing.candidate_id != candidate.id
                or existing.source_discord_message_id
                != candidate.source_discord_message_id
                or existing.source_author_id != candidate.source_author_id
                or existing.evidence_hash != evidence_hash
            ):
                raise DiscordMemoryConflictError(
                    "source idempotency key was reused with different evidence"
                )
            return existing, False
        source = DiscordMemorySource(
            memory_id=memory.id,
            candidate_id=candidate.id,
            source_turn_id=candidate.source_turn_id,
            source_discord_message_id=candidate.source_discord_message_id,
            source_author_id=candidate.source_author_id,
            source_role=source_role,
            evidence_hash=evidence_hash,
            created_at=datetime.now(UTC),
        )
        self.session.add(source)
        return source, True

    def list_sources(
        self,
        memory_id: UUID,
        *,
        guild_id: str,
    ) -> list[DiscordMemorySource]:
        if not guild_id:
            raise ValueError("guild_id is required")
        return list(
            self.session.scalars(
                select(DiscordMemorySource)
                .join(
                    DiscordMemory,
                    DiscordMemory.id == DiscordMemorySource.memory_id,
                )
                .where(
                    DiscordMemorySource.memory_id == memory_id,
                    DiscordMemory.guild_id == guild_id,
                )
                .order_by(DiscordMemorySource.created_at)
            )
        )
