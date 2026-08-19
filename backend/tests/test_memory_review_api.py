"""P1-4/P1-5: human review of Discord memory candidates and the web-store bridge.

Seeding goes through the real Discord session API (so FK integrity holds) and
then writes the extractor's result directly via the repository — the extractor
itself is P1-3's concern and already covered elsewhere.
"""
from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

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

URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")


@pytest.fixture
def factory():
    return create_session_factory(create_postgres_engine(str(URL)))


@pytest.fixture
def review_cleanup(factory):
    guild = f"review-{uuid4().hex[:10]}"
    yield guild
    with factory.begin() as session:
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
        session.execute(delete(Memory).where(Memory.content.like("User prefers review-test%")))


def seed_candidate(client, factory, guild: str, *, with_proposal: bool = True) -> str:
    """One completed turn plus its extracted candidate, exactly as the worker
    would have left them in proposal mode."""
    session_id = client.post(
        "/api/discord/sessions/resolve",
        json={"guild_id": guild, "channel_id": "kenh", "thread_id": None},
    ).json()["session_id"]
    # The repository cross-checks the candidate's source identity against the
    # persisted turn, so the candidate must reuse this exact message id.
    discord_message_id = f"msg-{uuid4().hex[:8]}"
    turn = client.post(
        f"/api/discord/sessions/{session_id}/turns",
        json={
            "discord_message_id": discord_message_id,
            "message": "Hãy nhớ rằng tôi thích trả lời ngắn gọn.",
            "author_id": "reviewer-target",
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
            source_author_id="reviewer-target",
            source_author_display_name="Dũng",
            guild_id=guild,
            channel_id="kenh",
            thread_id=None,
            extractor_schema_version="v1",
            filter_decision="candidate",
            filter_reason_code="explicit_remember",
        )
        if with_proposal:
            repository.update_candidate_result(
                candidate.id,
                guild_id=guild,
                expected_validation_status="pending",
                extractor_model="qwen3.5:2b",
                memory_type="preference",
                subject_type="member",
                subject_id="reviewer-target",
                scope="member_in_guild",
                fact_key="user.answer_style",
                canonical_fact=f"User prefers review-test concise answers ({guild}).",
                evidence_text="Hãy nhớ rằng tôi thích trả lời ngắn gọn.",
                confidence=0.93,
                decision="deferred",
            )
        return str(candidate.id)


def test_pending_candidates_are_listed_with_their_proposal(client, mock_ollama, factory, review_cleanup):
    guild = review_cleanup
    candidate_id = seed_candidate(client, factory, guild)

    listed = client.get("/api/memory-review/candidates")

    assert listed.status_code == 200
    match = next(item for item in listed.json() if item["candidate_id"] == candidate_id)
    assert match["canonical_fact"].startswith("User prefers review-test")
    assert match["evidence_text"] == "Hãy nhớ rằng tôi thích trả lời ngắn gọn."
    assert match["confidence"] == pytest.approx(0.93)
    assert match["reason_code"] == "explicit_remember"


def test_candidates_without_a_proposal_are_not_reviewable(client, mock_ollama, factory, review_cleanup):
    guild = review_cleanup
    candidate_id = seed_candidate(client, factory, guild, with_proposal=False)

    listed = client.get("/api/memory-review/candidates").json()
    assert all(item["candidate_id"] != candidate_id for item in listed)

    approved = client.post(f"/api/memory-review/candidates/{candidate_id}/approve")
    assert approved.status_code == 422
    assert approved.json()["error_code"] == "CANDIDATE_NOT_REVIEWABLE"


def _hash_embed(monkeypatch):
    """Content-sensitive fake embedding: identical text → identical vector.

    The shared test Qdrant collection accumulates points from other runs, all
    stored under the constant mock vector; a constant query vector ties with
    every one of them and top-k becomes a lottery. Hash vectors make an
    exact-text query rank first deterministically — the plumbing is what this
    suite proves, semantic quality is the live eval's job.
    """
    import hashlib

    def fake_embed(self, model, text):
        # Three dimensions to match the collection the constant mock created;
        # exact-text queries still hit cosine 1.0 while different texts do not.
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [byte / 255 for byte in digest[:3]]

    monkeypatch.setattr("app.llm_clients.ollama_client.OllamaClient.embed", fake_embed)


def test_approve_applies_the_memory_and_bridges_it_to_the_web_store(client, mock_ollama, factory, review_cleanup, monkeypatch):
    _hash_embed(monkeypatch)
    guild = review_cleanup
    candidate_id = seed_candidate(client, factory, guild)

    approved = client.post(f"/api/memory-review/candidates/{candidate_id}/approve")

    assert approved.status_code == 200
    body = approved.json()
    assert body["web_memory_id"] == f"mem_dc_{UUID(body['memory_id']).hex}"
    with factory() as session:
        candidate = session.get(DiscordMemoryCandidate, UUID(candidate_id))
        memory = session.get(DiscordMemory, UUID(body["memory_id"]))
        # Audit trail: the decision, who made it and when are all recorded.
        assert candidate.decision == "applied"
        assert candidate.validation_status == "accepted"
        assert candidate.reviewed_at is not None and candidate.reviewed_by == "dashboard"
        assert memory.status == "active" and memory.index_status == "indexed"
        assert memory.origin_candidate_id == candidate.id
        # P1-5: the same fact now lives in the web memory store.
        web_row = session.get(Memory, body["web_memory_id"])
        assert web_row is not None and web_row.content == memory.canonical_fact

    # The bridged memory is what /memory/search serves. Exact-text query pins
    # cosine 1.0, so the assertion is deterministic on a shared collection.
    search = client.post("/memory/search", json={"query": f"User prefers review-test concise answers ({guild}).", "top_k": 5})
    assert search.status_code == 200
    assert any(item["memory_id"] == body["web_memory_id"] for item in search.json())

    # An approved candidate no longer waits for review.
    listed = client.get("/api/memory-review/candidates").json()
    assert all(item["candidate_id"] != candidate_id for item in listed)


def test_approve_is_idempotent_and_retries_only_the_mirror(client, mock_ollama, factory, review_cleanup):
    guild = review_cleanup
    candidate_id = seed_candidate(client, factory, guild)

    first = client.post(f"/api/memory-review/candidates/{candidate_id}/approve")
    second = client.post(f"/api/memory-review/candidates/{candidate_id}/approve")

    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["memory_id"] == second.json()["memory_id"]
    with factory() as session:
        rows = list(session.scalars(select(DiscordMemory).where(DiscordMemory.guild_id == guild)))
        assert len(rows) == 1


def test_reject_records_the_decision_without_deleting_anything(client, mock_ollama, factory, review_cleanup):
    guild = review_cleanup
    candidate_id = seed_candidate(client, factory, guild)

    rejected = client.post(f"/api/memory-review/candidates/{candidate_id}/reject")
    repeat = client.post(f"/api/memory-review/candidates/{candidate_id}/reject")

    assert rejected.status_code == 200 and repeat.status_code == 200
    with factory() as session:
        candidate = session.get(DiscordMemoryCandidate, UUID(candidate_id))
        assert candidate is not None  # audit: never deleted
        assert candidate.decision == "rejected"
        assert candidate.validation_status == "rejected"
        assert candidate.reviewed_at is not None
        # Nothing was applied anywhere.
        assert session.scalar(select(DiscordMemory).where(DiscordMemory.guild_id == guild)) is None

    # A rejected candidate cannot be approved afterwards.
    approved = client.post(f"/api/memory-review/candidates/{candidate_id}/approve")
    assert approved.status_code == 422


def test_unknown_and_malformed_candidate_ids_are_404(client, mock_ollama):
    assert client.post(f"/api/memory-review/candidates/{uuid4()}/approve").status_code == 404
    assert client.post("/api/memory-review/candidates/not-a-uuid/approve").status_code == 404


def test_discord_learning_reaches_web_chat_with_memory_on(client, mock_ollama, factory, review_cleanup, monkeypatch):
    """P1-5 acceptance verbatim: turning on "Ghi nhớ" in web chat makes the
    assistant use what it learned from Discord."""
    _hash_embed(monkeypatch)
    guild = review_cleanup
    candidate_id = seed_candidate(client, factory, guild)
    client.post(f"/api/memory-review/candidates/{candidate_id}/approve")

    captured: list[dict[str, str]] = []

    def capture_chat(self, model, messages, options, keep_alive, think=None):
        captured.extend(messages)
        return f"Mock response from {model}"

    monkeypatch.setattr("app.llm_clients.ollama_client.OllamaClient.chat", capture_chat)

    # The exact stored text as the message pins the memory search to rank 1 on
    # the shared collection; semantic matching is exercised by the live eval.
    response = client.post("/chat", json={"message": f"User prefers review-test concise answers ({guild}).", "use_memory": True})

    assert response.status_code == 200
    memory_blocks = [m["content"] for m in captured if m["role"] == "system" and "Relevant memories" in m["content"]]
    assert memory_blocks, "web chat with memory on must inject the memory context"
    assert any("review-test concise answers" in block for block in memory_blocks)
    client.delete(f"/conversations/{response.json()['conversation_id']}")
