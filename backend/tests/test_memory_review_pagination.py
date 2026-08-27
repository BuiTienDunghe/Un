"""Job 5 (memory_design.md §13.2 E9): the reviewer must see the SOURCE
message, and the queue must paginate past the old 50-row hard ceiling.

The guard's own docstring names the human "the guard"; a reviewer shown only
the model's self-chosen evidence quote is rubber-stamping. And before
`offset`, rows past the newest 50 were unreachable through the API entirely.
"""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.discord_memory_repositories import DiscordMemoryRepository
from app.postgres.models import DiscordSessionTurn
from app.services.discord_memory_review_service import DiscordMemoryReviewService
from scripts.memory_e2e_eval import REASON_BY_KEY, CaseWorld, _NoMirror

URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")

MESSAGES = [
    "card của tôi là RTX 3060",
    "ram máy tôi là 64GB",
    "máy tôi đang chạy python 3.12",
]
FACTS = [
    ("hardware.gpu", "GPU là RTX 3060"),
    ("hardware.ram", "RAM 64GB"),
    ("software.python_version", "Dùng Python 3.12"),
]


def _defer_candidate(world: CaseWorld, index: int, fact_key: str, fact: str) -> None:
    """Candidate left in 'deferred' — in the queue, awaiting the human."""
    message = world.turn_meta[index]
    turn_id = world.turn_ids[index]
    guild_id = world.guild(message["guild"])
    with world.factory.begin() as database:
        turn = database.get(DiscordSessionTurn, turn_id)
        repository = DiscordMemoryRepository(database)
        candidate, _ = repository.create_or_get_candidate(
            source_turn_id=turn_id,
            session_id=turn.session_id,
            source_discord_message_id=turn.discord_message_id,
            source_author_id=turn.author_id,
            source_author_display_name=turn.author_display_name,
            guild_id=guild_id,
            channel_id=f"{world.prefix}-C1",
            thread_id=None,
            extractor_schema_version="e2e-eval-v1",
            filter_decision="candidate",
            filter_reason_code=REASON_BY_KEY[fact_key],
        )
        repository.update_candidate_result(
            candidate.id,
            guild_id=guild_id,
            expected_validation_status="pending",
            extractor_model="e2e-fixture",
            operation="create",
            memory_type="configuration",
            subject_type="discord_member",
            subject_id=turn.author_id,
            scope="member_in_guild",
            fact_key=fact_key,
            canonical_fact=fact,
            evidence_text=message["content"],
            decision="deferred",
        )


def test_pending_rows_carry_their_source_message_and_paginate(tmp_path):
    factory = create_session_factory(create_postgres_engine(str(URL)))
    world = CaseWorld(factory, f"revpage-{uuid4().hex[:8]}", "case")
    try:
        world.ingest([
            {"day": 1, "author": "UA", "guild": "G1", "channel": "C1", "content": text}
            for text in MESSAGES
        ])
        for index, (fact_key, fact) in enumerate(FACTS):
            _defer_candidate(world, index, fact_key, fact)

        service = DiscordMemoryReviewService(factory, _NoMirror())

        everything = service.list_pending(limit=100)
        ours = [row for row in everything if str(row["guild_id"]).startswith(world.prefix)]
        assert len(ours) == 3
        # The reviewer sees the ORIGINAL message, not just the model's quote.
        by_fact = {row["fact_key"]: row for row in ours}
        for index, (fact_key, _) in enumerate(FACTS):
            assert by_fact[fact_key]["source_text"] == MESSAGES[index]

        # Pagination: bounded pages, disjoint, reachable past the first page.
        first = service.list_pending(limit=2, offset=0)
        second = service.list_pending(limit=2, offset=2)
        assert len(first) <= 2
        assert {row["candidate_id"] for row in first}.isdisjoint(
            {row["candidate_id"] for row in second}
        )
        paged_ids = {
            row["candidate_id"]
            for offset in range(0, len(everything) + 2, 2)
            for row in service.list_pending(limit=2, offset=offset)
        }
        assert {row["candidate_id"] for row in ours} <= paged_ids
    finally:
        world.cleanup()
