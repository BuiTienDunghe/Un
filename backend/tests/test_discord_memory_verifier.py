"""Job 4: the 1-vs-1 verifier adapter and its fail-safe parsing, plus the
worker step that records the verdict and the autonomy gate on top of it.
"""
from __future__ import annotations

import os
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import DiscordMemoryCandidate
from app.services.discord_memory_verifier import DiscordMemoryVerifierAdapter
from app.services.discord_memory_worker_service import DiscordMemoryWorkerService
from scripts.memory_e2e_eval import CaseWorld
from tests.test_memory_review_pagination import _defer_candidate

URL = os.getenv("POSTGRES_TEST_URL")


class _ScriptedClient:
    def __init__(self, answer: str | Exception):
        self.answer = answer
        self.last_payload = None

    def post(self, url, *, json, timeout):
        if isinstance(self.answer, Exception):
            raise self.answer
        self.last_payload = json
        request = httpx.Request("POST", url)
        return httpx.Response(
            200, request=request, json={"message": {"content": self.answer}}
        )


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("ENTAILMENT", "entailment"),
        ("contradiction", "contradiction"),
        ("Unknown — không đủ căn cứ", "unknown"),
        ("Tôi nghĩ là đúng.", "unknown"),
        ("", "unknown"),
    ],
)
def test_parse_is_forgiving_but_fail_safe(answer, expected):
    adapter = DiscordMemoryVerifierAdapter(
        base_url="http://ollama.test", client=_ScriptedClient(answer)
    )
    verdict = adapter.verify(canonical_fact="GPU là RTX 3060", source_text="card RTX 3060")
    assert verdict.result == expected
    assert verdict.method.startswith("nli-1v1:")


def test_transport_failure_is_unknown_never_raised():
    adapter = DiscordMemoryVerifierAdapter(
        base_url="http://ollama.test",
        client=_ScriptedClient(httpx.ConnectError("down")),
    )
    verdict = adapter.verify(canonical_fact="x y", source_text="z")
    assert verdict.result == "unknown"


@pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")
def test_worker_records_verdict_on_the_candidate():
    factory = create_session_factory(create_postgres_engine(str(URL)))
    world = CaseWorld(factory, f"verify-{uuid4().hex[:8]}", "case")
    try:
        world.ingest([
            {"day": 1, "author": "UA", "guild": "G1", "channel": "C1",
             "content": "card của tôi là RTX 3060"},
        ])
        _defer_candidate(world, 0, "hardware.gpu", "GPU là RTX 3060")
        with world.factory() as database:
            candidate = database.scalar(
                select(DiscordMemoryCandidate).where(
                    DiscordMemoryCandidate.guild_id.like(f"{world.prefix}-%")
                )
            )
            candidate_id = str(candidate.id)

        worker = DiscordMemoryWorkerService(
            factory,
            worker_id="verify-test",
            lease_seconds=30,
            verifier=DiscordMemoryVerifierAdapter(
                base_url="http://ollama.test", client=_ScriptedClient("ENTAILMENT")
            ),
        )
        from app.services.discord_memory_worker_service import (
            DiscordMemoryWorkerOutcome,
        )
        outcome = worker.verify_proposal(
            DiscordMemoryWorkerOutcome(
                status="completed",
                job_id="job-x",
                candidate_id=candidate_id,
                reason="extractor_proposal_deferred",
            )
        )
        assert outcome.candidate_id == candidate_id
        with world.factory() as database:
            stored = database.get(DiscordMemoryCandidate, UUID(candidate_id))
            assert stored.verification_result == "entailment"
            assert stored.verification_method.startswith("nli-1v1:")
    finally:
        world.cleanup()
