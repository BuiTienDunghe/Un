"""Review of Discord memory candidates (P1-4) and the bridge that unifies
applied memories into the web memory store (P1-5).

Two reviewers exist since P2-1: a human on the dashboard, and the agent itself
for proposals whose extractor confidence clears the configured threshold
(`reviewed_by="agent"`). Both flow through the same `approve`, so audit trail
and web mirror stay identical either way — and the price of autonomy is paid
in `revert`: every applied memory is one click from gone. Rejection is
recorded, never deleted.
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

    def list_applied(self, limit: int = 20) -> list[dict[str, object]]:
        """Memories currently in service, newest decision first — the oversight
        view of P2-1: who applied each one (human or agent) and the handle to
        revert it."""
        with self.sessions() as session:
            rows = session.execute(
                select(DiscordMemory, DiscordMemoryCandidate)
                .join(
                    DiscordMemoryCandidate,
                    DiscordMemory.origin_candidate_id == DiscordMemoryCandidate.id,
                )
                .where(
                    DiscordMemory.status == "active",
                    DiscordMemoryCandidate.decision == "applied",
                )
                .order_by(DiscordMemory.updated_at.desc())
                .limit(limit)
            ).all()
            return [
                {
                    "candidate_id": str(candidate.id),
                    "memory_id": str(memory.id),
                    "web_memory_id": f"mem_dc_{memory.id.hex}",
                    "canonical_fact": memory.canonical_fact,
                    "memory_type": memory.memory_type,
                    "version": memory.version,
                    "confidence": float(candidate.confidence) if candidate.confidence is not None else None,
                    "author_display_name": candidate.source_author_display_name,
                    "author_id": candidate.source_author_id,
                    "applied_by": candidate.reviewed_by,
                    "applied_at": candidate.reviewed_at.isoformat() if candidate.reviewed_at else None,
                    "index_status": memory.index_status,
                }
                for memory, candidate in rows
            ]

    def approve(self, candidate_id: UUID, reviewed_by: str = "dashboard") -> dict[str, object]:
        """Turn a proposal into the canonical Discord memory version and mirror
        it to the web store.

        Version routing (P2-1): a live active version of the same identity is
        superseded, an identity whose history ended without an active row
        (reverted) is revived, otherwise version 1 is created. Two phases on
        purpose: the database work commits first, then the mirror (which embeds
        — a model call) runs OUTSIDE any transaction, honouring the
        no-transaction-across-model-calls invariant. Every routing target is
        idempotent for identical payloads, so re-approving after a failed
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
                repository = DiscordMemoryRepository(session)
                arguments = dict(
                    candidate_id=candidate.id,
                    identity=identity,
                    canonical_fact=candidate.canonical_fact,
                    memory_type=candidate.memory_type,
                    extractor_model=candidate.extractor_model or "unknown",
                    extractor_schema_version=candidate.extractor_schema_version,
                    evidence_hash=f"sha256:{hashlib.sha256(evidence.encode('utf-8')).hexdigest()}",
                )
                active = repository.get_active_memory(identity)
                if active is not None and active.origin_candidate_id != candidate.id:
                    memory, _ = repository.supersede_active_version(
                        **arguments,
                        expected_active_memory_id=candidate.target_memory_id,
                    )
                elif active is None and repository.version_history(identity):
                    memory, _ = repository.revive_version(**arguments)
                else:
                    memory, _ = repository.create_active_version(**arguments)
            else:
                memory = session.scalar(select(DiscordMemory).where(DiscordMemory.origin_candidate_id == candidate.id))
                if memory is None:
                    raise CandidateNotReviewableError("candidate is applied but its memory is missing")
            candidate.validation_status = "accepted"
            candidate.reviewed_at = datetime.now(UTC)
            candidate.reviewed_by = reviewed_by
            memory_id, canonical_fact, memory_type = memory.id, memory.canonical_fact, memory.memory_type
            superseded_memory_id = memory.supersedes_memory_id
            confidence = float(candidate.confidence) if candidate.confidence is not None else 0.5

        # ── Mirror into the web store (P1-5), outside any transaction ──
        # Deterministic ids keep both steps idempotent across retries: the new
        # version overwrites its own entry and the superseded predecessor's
        # entry is removed, so the web assistant never quotes a stale fact.
        web_memory_id = f"mem_dc_{memory_id.hex}"
        try:
            self.memory_service.upsert_with_id(web_memory_id, canonical_fact, memory_type, confidence)
            if superseded_memory_id is not None:
                self.memory_service.remove_with_id(f"mem_dc_{superseded_memory_id.hex}")
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

    def revert(self, candidate_id: UUID, reviewed_by: str = "dashboard") -> dict[str, object]:
        """Take an applied memory back out of service — the counterpart the
        P2-1 invariant demands: every self-applied memory is one click from
        gone. The canonical row stays as history (`status='deleted'`), the web
        mirror is removed, the candidate records who reverted and when. Only
        the active version can be reverted; a superseded one already left
        service when its successor applied.
        """
        with self.sessions.begin() as session:
            candidate = session.get(DiscordMemoryCandidate, candidate_id)
            if candidate is None:
                raise CandidateNotFoundError(str(candidate_id))
            memory = session.scalar(
                select(DiscordMemory).where(DiscordMemory.origin_candidate_id == candidate.id)
            )
            already_reverted = (
                candidate.decision == "rejected"
                and memory is not None
                and memory.status == "deleted"
            )
            if not already_reverted:
                if candidate.decision != "applied" or memory is None:
                    raise CandidateNotReviewableError("only applied candidates can be reverted")
                if memory.status != "active":
                    raise CandidateNotReviewableError(
                        f"memory is already {memory.status}; revert the version that replaced it"
                    )
                now = datetime.now(UTC)
                memory.status = "deleted"
                memory.valid_until = now
                memory.deleted_at = now
                memory.updated_at = now
                candidate.decision = "rejected"
                candidate.validation_status = "rejected"
                candidate.reviewed_at = now
                candidate.reviewed_by = reviewed_by
            memory_id = memory.id

        # Mirror removal outside any transaction, mirroring approve's shape:
        # a failure leaves `index_status='failed'` and reverting again retries
        # only this step (remove_with_id treats a missing row as done).
        web_memory_id = f"mem_dc_{memory_id.hex}"
        try:
            self.memory_service.remove_with_id(web_memory_id)
        except Exception as error:
            with self.sessions.begin() as session:
                stored = session.get(DiscordMemory, memory_id)
                if stored is not None:
                    stored.index_status = "failed"
            raise MemoryMirrorError(str(error)) from error
        with self.sessions.begin() as session:
            stored = session.get(DiscordMemory, memory_id)
            if stored is not None:
                stored.index_status = "not_required"
        return {
            "candidate_id": str(candidate_id),
            "memory_id": str(memory_id),
            "web_memory_id": web_memory_id,
            "status": "reverted",
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
