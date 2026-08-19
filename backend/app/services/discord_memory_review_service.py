"""Human review of Discord memory candidates (P1-4) and the bridge that
unifies approved memories into the web memory store (P1-5).

Proposal mode ends here: the extractor only ever produces candidates in
`decision='deferred'`; this service is the single place a human decision turns
one into a canonical Discord memory AND a web-visible memory. Rejection is
recorded, never deleted — the audit trail (`reviewed_at`, `reviewed_by`,
`decision`, `validation_status`) is the point of proposal mode.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.postgres.discord_memory_repositories import (
    DiscordMemoryIdentity,
    DiscordMemoryRepository,
)
from app.postgres.models import DiscordMemory, DiscordMemoryCandidate
from app.services.memory_service import MemoryService


class CandidateNotFoundError(Exception):
    pass


class CandidateNotReviewableError(Exception):
    """The candidate has no usable proposal or was already decided."""


class MemoryMirrorError(Exception):
    """The Discord memory was applied but the web-store mirror failed."""


REVIEWABLE_DECISIONS = {"deferred", "pending"}


def _candidate_payload(candidate: DiscordMemoryCandidate) -> dict[str, object]:
    return {
        "candidate_id": str(candidate.id),
        "created_at": candidate.created_at.isoformat(),
        "guild_id": candidate.guild_id,
        "channel_id": candidate.channel_id,
        "author_display_name": candidate.source_author_display_name,
        "author_id": candidate.source_author_id,
        "memory_type": candidate.memory_type,
        "scope": candidate.scope,
        "fact_key": candidate.fact_key,
        "canonical_fact": candidate.canonical_fact,
        "evidence_text": candidate.evidence_text,
        "confidence": float(candidate.confidence) if candidate.confidence is not None else None,
        "reason_code": candidate.filter_reason_code,
        "decision": candidate.decision,
        "validation_status": candidate.validation_status,
        "reviewed_at": candidate.reviewed_at.isoformat() if candidate.reviewed_at else None,
        "reviewed_by": candidate.reviewed_by,
    }


class DiscordMemoryReviewService:
    def __init__(self, sessions: sessionmaker, memory_service: MemoryService) -> None:
        self.sessions = sessions
        self.memory_service = memory_service

    def list_pending(self, limit: int = 50) -> list[dict[str, object]]:
        """Candidates awaiting a human decision, newest first.

        Only rows with an actual proposal are reviewable: rows the extractor
        skipped (disabled, filtered) have no canonical_fact and nothing for a
        reviewer to approve.
        """
        with self.sessions() as session:
            rows = session.scalars(
                select(DiscordMemoryCandidate)
                .where(
                    DiscordMemoryCandidate.decision.in_(tuple(REVIEWABLE_DECISIONS)),
                    DiscordMemoryCandidate.canonical_fact.is_not(None),
                )
                .order_by(DiscordMemoryCandidate.created_at.desc())
                .limit(limit)
            )
            return [_candidate_payload(row) for row in rows]

    def approve(self, candidate_id: UUID, reviewed_by: str = "dashboard") -> dict[str, object]:
        """Turn a proposal into a canonical Discord memory and mirror it to the
        web store.

        Two phases on purpose: the database work commits first, then the mirror
        (which embeds — a model call) runs OUTSIDE any transaction, honouring
        the no-transaction-across-model-calls invariant. `create_active_version`
        is idempotent for identical payloads, so re-approving after a failed
        mirror retries only the mirror.
        """
        with self.sessions.begin() as session:
            candidate = session.get(DiscordMemoryCandidate, candidate_id)
            if candidate is None:
                raise CandidateNotFoundError(str(candidate_id))
            already_applied = candidate.decision == "applied"
            if not already_applied:
                if candidate.decision not in REVIEWABLE_DECISIONS:
                    raise CandidateNotReviewableError(f"candidate is already {candidate.decision}")
                if not candidate.canonical_fact or not candidate.memory_type:
                    raise CandidateNotReviewableError("candidate carries no extractor proposal")
                identity = DiscordMemoryIdentity(
                    guild_id=candidate.guild_id,
                    scope=str(candidate.scope),
                    subject_type=str(candidate.subject_type),
                    subject_id=str(candidate.subject_id),
                    fact_key=str(candidate.fact_key),
                    channel_id=candidate.channel_id if candidate.scope == "channel" else None,
                    thread_id=candidate.thread_id if candidate.scope == "thread" else None,
                )
                evidence = candidate.evidence_text or candidate.canonical_fact
                memory, _ = DiscordMemoryRepository(session).create_active_version(
                    candidate_id=candidate.id,
                    identity=identity,
                    canonical_fact=candidate.canonical_fact,
                    memory_type=candidate.memory_type,
                    extractor_model=candidate.extractor_model or "unknown",
                    extractor_schema_version=candidate.extractor_schema_version,
                    evidence_hash=f"sha256:{hashlib.sha256(evidence.encode('utf-8')).hexdigest()}",
                )
            else:
                memory = session.scalar(select(DiscordMemory).where(DiscordMemory.origin_candidate_id == candidate.id))
                if memory is None:
                    raise CandidateNotReviewableError("candidate is applied but its memory is missing")
            candidate.validation_status = "accepted"
            candidate.reviewed_at = datetime.now(UTC)
            candidate.reviewed_by = reviewed_by
            memory_id, canonical_fact, memory_type = memory.id, memory.canonical_fact, memory.memory_type
            confidence = float(candidate.confidence) if candidate.confidence is not None else 0.5

        # ── Mirror into the web store (P1-5), outside any transaction ──
        # Deterministic id makes the mirror idempotent across retries.
        web_memory_id = f"mem_dc_{memory_id.hex}"
        try:
            self.memory_service.upsert_with_id(web_memory_id, canonical_fact, memory_type, confidence)
        except Exception as error:
            with self.sessions.begin() as session:
                stored = session.get(DiscordMemory, memory_id)
                if stored is not None:
                    stored.index_status = "failed"
            raise MemoryMirrorError(str(error)) from error
        with self.sessions.begin() as session:
            stored = session.get(DiscordMemory, memory_id)
            if stored is not None:
                stored.index_status = "indexed"
        return {
            "candidate_id": str(candidate_id),
            "memory_id": str(memory_id),
            "web_memory_id": web_memory_id,
            "canonical_fact": canonical_fact,
        }

    def reject(self, candidate_id: UUID, reviewed_by: str = "dashboard") -> dict[str, object]:
        with self.sessions.begin() as session:
            candidate = session.get(DiscordMemoryCandidate, candidate_id)
            if candidate is None:
                raise CandidateNotFoundError(str(candidate_id))
            if candidate.decision == "rejected":
                return _candidate_payload(candidate)
            if candidate.decision not in REVIEWABLE_DECISIONS:
                raise CandidateNotReviewableError(f"candidate is already {candidate.decision}")
            candidate.decision = "rejected"
            candidate.validation_status = "rejected"
            candidate.reviewed_at = datetime.now(UTC)
            candidate.reviewed_by = reviewed_by
            return _candidate_payload(candidate)
