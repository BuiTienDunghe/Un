"""P2-1: the agent applies its own high-confidence proposals, every applied
memory is one click from reverted, and a fact stays one live version.

Seeding mirrors test_memory_review_api: the real Discord session API creates
the turn (FK integrity), then the extractor's result is written through the
repository — extraction itself is P1-3's suite. The worker's auto-apply step
is exercised directly on the persisted outcome, exactly as `process()` calls
it after the extraction job commits.
"""
from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.discord_memory_repositories import DiscordMemoryRepository
from app.postgres.models import (
    Conversation,
    DiscordConversationSession,
    DiscordMemory,
    DiscordMemoryCandidate,
    DiscordMemorySource,
    DiscordSessionTurn,
    DiscordTurnDelivery,
    Memory,
)
from app.services.discord_memory_worker_service import (
    DiscordMemoryWorkerOutcome,
    DiscordMemoryWorkerService,
)

URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")


@pytest.fixture
def factory():
    return create_session_factory(create_postgres_engine(str(URL)))


@pytest.fixture
def auto_cleanup(factory):
    guild = f"auto-{uuid4().hex[:10]}"
    yield guild
    with factory.begin() as session:
        # Version chains and supersede bookkeeping hold RESTRICT FKs in both
        # directions (memory→memory, candidate→memory), so break the links
        # before deleting either side.
        session.execute(
            update(DiscordMemory).where(DiscordMemory.guild_id == guild).values(supersedes_memory_id=None)
        )
        session.execute(
            update(DiscordMemoryCandidate)
            .where(DiscordMemoryCandidate.guild_id == guild)
            .values(target_memory_id=None)
        )
        candidate_ids = list(session.scalars(select(DiscordMemoryCandidate.id).where(DiscordMemoryCandidate.guild_id == guild)))
        if candidate_ids:
            session.execute(delete(DiscordMemorySource).where(DiscordMemorySource.candidate_id.in_(candidate_ids)))
        session.execute(delete(DiscordMemory).where(DiscordMemory.guild_id == guild))
        session.execute(delete(DiscordMemoryCandidate).where(DiscordMemoryCandidate.guild_id == guild))
        sessions = list(session.scalars(select(DiscordConversationSession).where(DiscordConversationSession.guild_id == guild)))
        session_ids = [row.id for row in sessions]
        conversation_ids = [str(row.backend_conversation_id) for row in sessions]
        if session_ids:
            turn_ids = list(session.scalars(select(DiscordSessionTurn.id).where(DiscordSessionTurn.session_id.in_(session_ids))))
            if turn_ids:
                session.execute(delete(DiscordTurnDelivery).where(DiscordTurnDelivery.turn_id.in_(turn_ids)))
                session.execute(delete(DiscordSessionTurn).where(DiscordSessionTurn.id.in_(turn_ids)))
            session.execute(delete(DiscordConversationSession).where(DiscordConversationSession.id.in_(session_ids)))
        if conversation_ids:
            session.execute(delete(Conversation).where(Conversation.id.in_(conversation_ids)))
        session.execute(delete(Memory).where(Memory.content.like(f"%{guild}%")))


def seed_candidate(
    client,
    factory,
    guild: str,
    *,
    fact: str,
    confidence: float,
    operation: str = "create",
) -> str:
    """One completed turn plus its extracted candidate, exactly as the worker
    leaves them right before the auto-apply step. Identity fields are constant
    so several candidates in one guild target the same canonical fact."""
    session_id = client.post(
        "/api/discord/sessions/resolve",
        json={"guild_id": guild, "channel_id": "kenh", "thread_id": None},
    ).json()["session_id"]
    discord_message_id = f"msg-{uuid4().hex[:8]}"
    turn = client.post(
        f"/api/discord/sessions/{session_id}/turns",
        json={
            "discord_message_id": discord_message_id,
            "message": "Hãy nhớ rằng tôi thích trả lời ngắn gọn.",
            "author_id": "auto-target",
            "author_display_name": "Dũng",
        },
    ).json()
    execution = client.post(f"/api/discord/sessions/turns/{turn['turn_id']}/execute").json()
    client.post(
        f"/api/discord/sessions/turns/{turn['turn_id']}/complete",
        json={"execution_token": execution["execution_token"], "discord_response_message_ids": [f"resp-{uuid4().hex[:8]}"]},
    )
    with factory.begin() as session:
        repository = DiscordMemoryRepository(session)
        candidate, _ = repository.create_or_get_candidate(
            source_turn_id=UUID(turn["turn_id"]),
            session_id=UUID(session_id),
            source_discord_message_id=discord_message_id,
            source_author_id="auto-target",
            source_author_display_name="Dũng",
            guild_id=guild,
            channel_id="kenh",
            thread_id=None,
            extractor_schema_version="v1",
            filter_decision="candidate",
            filter_reason_code="explicit_remember",
        )
        repository.update_candidate_result(
            candidate.id,
            guild_id=guild,
            expected_validation_status="pending",
            extractor_model="qwen3.5:2b",
            operation=operation,
            memory_type="preference",
            subject_type="member",
            subject_id="auto-target",
            scope="member_in_guild",
            fact_key="user.answer_style",
            canonical_fact=fact,
            evidence_text="Hãy nhớ rằng tôi thích trả lời ngắn gọn.",
            confidence=confidence,
            decision="deferred",
        )
        return str(candidate.id)


def make_worker(client, factory, threshold: float | None) -> DiscordMemoryWorkerService:
    return DiscordMemoryWorkerService(
        factory,
        worker_id="auto-apply-test",
        lease_seconds=5,
        review_service=client.app.state.memory_review_service if threshold is not None else None,
        auto_apply_threshold=threshold,
    )


def persisted_outcome(candidate_id: str) -> DiscordMemoryWorkerOutcome:
    """What `_persist_valid_result` returns right before auto_apply runs."""
    return DiscordMemoryWorkerOutcome(
        status="completed",
        job_id=f"job-{uuid4().hex[:8]}",
        candidate_id=candidate_id,
        reason="extractor_proposal_deferred",
        created=True,
    )


def test_worker_auto_applies_high_confidence_proposal(client, mock_ollama, factory, auto_cleanup):
    guild = auto_cleanup
    fact = f"User prefers concise answers ({guild})."
    candidate_id = seed_candidate(client, factory, guild, fact=fact, confidence=0.93)

    outcome = make_worker(client, factory, 0.8).auto_apply(persisted_outcome(candidate_id))

    assert outcome.reason == "extractor_proposal_auto_applied"
    with factory() as session:
        candidate = session.get(DiscordMemoryCandidate, UUID(candidate_id))
        memory = session.scalar(select(DiscordMemory).where(DiscordMemory.origin_candidate_id == candidate.id))
        # The agent is a first-class reviewer: same audit trail, its own name.
        assert candidate.decision == "applied" and candidate.validation_status == "accepted"
        assert candidate.reviewed_by == "agent" and candidate.reviewed_at is not None
        assert memory.status == "active" and memory.index_status == "indexed"
        # P1-5 bridge ran too: the fact is live in the web store.
        assert session.get(Memory, f"mem_dc_{memory.id.hex}") is not None
    # Nothing left for the human queue.
    listed = client.get("/api/memory-review/candidates").json()
    assert all(item["candidate_id"] != candidate_id for item in listed)
    # The oversight panel shows who applied it.
    applied = client.get("/api/memory-review/applied").json()
    row = next(item for item in applied if item["candidate_id"] == candidate_id)
    assert row["applied_by"] == "agent" and row["canonical_fact"] == fact


def test_below_threshold_waits_for_the_human_queue(client, mock_ollama, factory, auto_cleanup):
    guild = auto_cleanup
    candidate_id = seed_candidate(client, factory, guild, fact=f"User likes tables ({guild}).", confidence=0.6)

    outcome = make_worker(client, factory, 0.8).auto_apply(persisted_outcome(candidate_id))

    assert outcome.reason == "extractor_proposal_deferred"
    with factory() as session:
        candidate = session.get(DiscordMemoryCandidate, UUID(candidate_id))
        assert candidate.decision == "deferred" and candidate.reviewed_by is None
        assert session.scalar(select(DiscordMemory).where(DiscordMemory.guild_id == guild)) is None
    listed = client.get("/api/memory-review/candidates").json()
    assert any(item["candidate_id"] == candidate_id for item in listed)


def test_delete_proposals_and_disabled_threshold_never_auto_apply(client, mock_ollama, factory, auto_cleanup):
    guild = auto_cleanup
    forget = seed_candidate(client, factory, guild, fact=f"Forget this ({guild}).", confidence=0.99, operation="delete")
    assert make_worker(client, factory, 0.8).auto_apply(persisted_outcome(forget)).reason == "extractor_proposal_deferred"

    plain = seed_candidate(client, factory, guild, fact=f"No autonomy ({guild}).", confidence=0.99)
    assert make_worker(client, factory, None).auto_apply(persisted_outcome(plain)).reason == "extractor_proposal_deferred"
    with factory() as session:
        assert session.scalar(select(DiscordMemory).where(DiscordMemory.guild_id == guild)) is None


def test_approve_supersedes_and_replaces_the_web_mirror(client, mock_ollama, factory, auto_cleanup):
    guild = auto_cleanup
    first = seed_candidate(client, factory, guild, fact=f"User prefers Vietnamese ({guild}).", confidence=0.9)
    first_applied = client.post(f"/api/memory-review/candidates/{first}/approve").json()

    second = seed_candidate(client, factory, guild, fact=f"User prefers English ({guild}).", confidence=0.9, operation="update")
    second_applied = client.post(f"/api/memory-review/candidates/{second}/approve")

    assert second_applied.status_code == 200
    body = second_applied.json()
    with factory() as session:
        old = session.get(DiscordMemory, UUID(first_applied["memory_id"]))
        new = session.get(DiscordMemory, UUID(body["memory_id"]))
        assert old.status == "superseded" and old.valid_until is not None
        assert new.status == "active" and new.version == old.version + 1
        assert new.supersedes_memory_id == old.id
        # The web store serves exactly the current fact — stale mirror is gone.
        assert session.get(Memory, body["web_memory_id"]) is not None
        assert session.get(Memory, first_applied["web_memory_id"]) is None


def test_revert_takes_memory_out_of_service_and_relearning_revives(client, mock_ollama, factory, auto_cleanup):
    guild = auto_cleanup
    candidate_id = seed_candidate(client, factory, guild, fact=f"User prefers short answers ({guild}).", confidence=0.9)
    applied = client.post(f"/api/memory-review/candidates/{candidate_id}/approve").json()

    reverted = client.post(f"/api/memory-review/candidates/{candidate_id}/revert")
    repeat = client.post(f"/api/memory-review/candidates/{candidate_id}/revert")

    assert reverted.status_code == 200 and repeat.status_code == 200
    assert reverted.json()["status"] == "reverted"
    with factory() as session:
        candidate = session.get(DiscordMemoryCandidate, UUID(candidate_id))
        memory = session.get(DiscordMemory, UUID(applied["memory_id"]))
        # History survives; service does not.
        assert memory is not None and memory.status == "deleted" and memory.deleted_at is not None
        assert memory.index_status == "not_required"
        assert candidate.decision == "rejected" and candidate.validation_status == "rejected"
        assert session.get(Memory, applied["web_memory_id"]) is None
    assert all(item["candidate_id"] != candidate_id for item in client.get("/api/memory-review/applied").json())

    # A revert must not dead-end the fact: relearning creates the next version.
    relearn = seed_candidate(client, factory, guild, fact=f"User prefers short answers again ({guild}).", confidence=0.9)
    revived = client.post(f"/api/memory-review/candidates/{relearn}/approve")
    assert revived.status_code == 200
    with factory() as session:
        new = session.get(DiscordMemory, UUID(revived.json()["memory_id"]))
        assert new.status == "active" and new.version == 2
        assert session.get(Memory, revived.json()["web_memory_id"]) is not None
