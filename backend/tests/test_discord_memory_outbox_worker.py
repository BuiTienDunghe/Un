from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.discord_memory_job_repository import (
    DiscordMemoryJobRepository,
)
from app.postgres.discord_memory_repositories import (
    DiscordMemoryConflictError,
    DiscordMemoryRepository,
)
from app.postgres.models import (
    Conversation,
    DiscordConversationSession,
    DiscordMemory,
    DiscordMemoryCandidate,
    DiscordMemorySource,
    DiscordSessionTurn,
    DiscordTurnDelivery,
    Job,
    OutboxEvent,
    new_id,
)
from app.services.discord_memory_completion_service import (
    DiscordMemoryCompletionTransportError,
    DiscordMemoryCompletionService,
)
from app.services.discord_memory_extractor import (
    DiscordMemoryExtractorOutputError,
    DiscordMemoryExtractorResult,
    DiscordMemoryExtractorTransportError,
    DiscordMemoryProposalV1,
)
from app.services.discord_memory_recovery_service import (
    DiscordMemoryRecoveryService,
)
from app.services.discord_memory_worker_service import (
    DiscordMemoryWorkerService,
)
from app.services.discord_session_service import DiscordSessionService
from app.services.discord_turn_service import DiscordTurnService
from app.services.job_recovery_service import JobRecoveryService
from app.services.job_routing import DISCORD_MEMORY_INGEST_JOB_TYPE
from app.services.job_routing import resolve_job_route
from app.services.outbox_dispatcher_service import OutboxDispatcherService
from app.services import operational_service
from app.services.operational_service import OperationalService


URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")


class ChatStub:
    history_limit = 12

    def respond_with_context(
        self,
        message,
        conversation_id,
        *,
        model_history,
        current_model_message,
        context_system_prompt,
        system_prompt=None,
    ):
        return f"answer:{message}", "test-model", conversation_id, 1


class QueueStub:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    def enqueue(self, job_type: str, job_id: str) -> str:
        self.calls.append((job_type, job_id))
        if self.fail:
            raise ConnectionError("redis unavailable")
        return job_id


class ExtractorStub:
    def __init__(self, *, error=None) -> None:
        self.error = error
        self.calls = []

    def extract(self, envelope):
        self.calls.append(envelope)
        if self.error is not None:
            raise self.error
        raw = {
            "schema_version": "v1",
            "operation": "create",
            "memory_type": "preference",
            "subject_type": "member",
            "subject_id": envelope.current_author_id,
            "scope": "member_in_guild",
            "fact_key": "response.language",
            "canonical_fact": "Người dùng ưu tiên tiếng Việt.",
            "evidence_text": envelope.raw_request_text,
            "source_turn_id": envelope.source_turn_id,
            "source_discord_message_id": (
                envelope.source_discord_message_id
            ),
            "confidence": 0.95,
            "reason_code": "explicit_preference",
            "target_memory_id": None,
        }
        proposal = DiscordMemoryProposalV1.model_validate(raw, strict=True)
        return DiscordMemoryExtractorResult(
            proposal=proposal,
            raw_output=raw,
            model="qwen3.5:2b",
            schema_version="v1",
            prompt_version="discord_memory_extractor_prompt_v1",
            latency_ms=5,
            format_mode="json_schema",
            performance={
                "prompt_eval_count": 100,
                "eval_count": 50,
            },
        )


@pytest.fixture
def memory_transport():
    assert URL is not None
    assert make_url(URL).database == "local_ai_core_test"
    factory = create_session_factory(create_postgres_engine(URL))
    prefix = f"sprint2b3-{uuid4().hex}"
    yield factory, prefix
    with factory.begin() as database:
        database.execute(
            delete(OutboxEvent).where(
                OutboxEvent.idempotency_key.like(f"%{prefix}%")
            )
        )
        memory_job_ids = list(
            database.scalars(
                select(Job.id).where(
                    Job.job_type == DISCORD_MEMORY_INGEST_JOB_TYPE
                )
            )
        )
        if memory_job_ids:
            database.execute(
                delete(OutboxEvent).where(
                    OutboxEvent.job_id.in_(memory_job_ids)
                )
            )
            database.execute(delete(Job).where(Job.id.in_(memory_job_ids)))
        database.execute(delete(DiscordMemorySource))
        database.execute(delete(DiscordMemory))
        database.execute(delete(DiscordMemoryCandidate))
        conversation_ids = [
            str(value)
            for value in database.scalars(
                select(DiscordConversationSession.backend_conversation_id).where(
                    DiscordConversationSession.guild_id.like(f"{prefix}%")
                )
            )
        ]
        database.execute(
            delete(DiscordConversationSession).where(
                DiscordConversationSession.guild_id.like(f"{prefix}%")
            )
        )
        if conversation_ids:
            database.execute(
                delete(Conversation).where(
                    Conversation.id.in_(conversation_ids)
                )
            )
        database.execute(
            delete(Job).where(Job.id.like(f"{prefix}%"))
        )


def _service(factory, *, enabled: bool) -> tuple[
    DiscordSessionService,
    DiscordTurnService,
]:
    resolver = DiscordSessionService(factory)
    completion = DiscordMemoryCompletionService(
        enabled=enabled,
        extractor_schema_version="v1",
        max_attempts=3,
    )
    return resolver, DiscordTurnService(
        factory,
        resolver,
        ChatStub(),
        lease_seconds=30,
        memory_completion_service=completion,
    )


def _execute(
    resolver: DiscordSessionService,
    service: DiscordTurnService,
    *,
    guild_id: str,
    channel_id: str = "channel",
    thread_id: str | None = None,
    message_id: str | None = None,
    author_id: str = "author-a",
    display_name: str = "Author A",
    request_text: str = "Hãy nhớ cấu hình bền vững này",
):
    resolved = resolver.resolve(guild_id, channel_id, thread_id)
    turn = service.enqueue(
        resolved.session_id,
        message_id or f"source-{uuid4().hex}",
        request_text,
        author_id=author_id,
        author_display_name=display_name,
    )
    running = service.execute(turn.turn_id)
    assert running.execution_token
    assert running.answer
    return resolved, turn, running


def _complete(service, turn, running, delivery_id: str | None = None):
    return service.complete(
        turn.turn_id,
        running.execution_token or "",
        [delivery_id or f"delivery-{uuid4().hex}"],
    )


def _memory_transport_rows(factory):
    with factory() as database:
        jobs = list(
            database.scalars(
                select(Job).where(
                    Job.job_type == DISCORD_MEMORY_INGEST_JOB_TYPE
                )
            )
        )
        events = list(
            database.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.job_id.in_([job.id for job in jobs])
                )
            )
        ) if jobs else []
        return jobs, events


def test_first_completion_atomically_creates_delivery_job_and_outbox(
    memory_transport,
):
    factory, prefix = memory_transport
    resolver, service = _service(factory, enabled=True)
    _, turn, running = _execute(resolver, service, guild_id=prefix)
    completed = _complete(service, turn, running, "delivery-atomic")
    assert completed.status == "completed"
    jobs, events = _memory_transport_rows(factory)
    assert len(jobs) == len(events) == 1
    job, event = jobs[0], events[0]
    assert job.idempotency_key == (
        f"discord_memory_ingest:{turn.turn_id}:v1"
    )
    assert event.idempotency_key == (
        f"job_enqueue:discord_memory_ingest:{turn.turn_id}:v1"
    )
    assert job.payload == {
        "turn_id": str(turn.turn_id),
        "session_id": str(turn.session_id),
        "extractor_schema_version": "v1",
    }
    assert set(job.payload) == {
        "turn_id",
        "session_id",
        "extractor_schema_version",
    }
    with factory() as database:
        stored = database.get(DiscordSessionTurn, turn.turn_id)
        deliveries = list(
            database.scalars(
                select(DiscordTurnDelivery).where(
                    DiscordTurnDelivery.turn_id == turn.turn_id
                )
            )
        )
        assert stored is not None and stored.status == "completed"
        assert stored.worker_id is stored.lease_expires_at is stored.heartbeat_at is None
        assert [row.discord_message_id for row in deliveries] == [
            "delivery-atomic"
        ]


@pytest.mark.parametrize("failure_point", ["job", "outbox"])
def test_transport_insert_failure_rolls_back_completion(
    memory_transport,
    monkeypatch,
    failure_point,
):
    factory, prefix = memory_transport
    resolver, service = _service(factory, enabled=True)
    _, turn, running = _execute(resolver, service, guild_id=prefix)
    method = "_new_job" if failure_point == "job" else "_new_outbox"
    with monkeypatch.context() as patch:
        patch.setattr(
            DiscordMemoryJobRepository,
            method,
            lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError(f"forced {failure_point} failure")
            ),
        )
        with pytest.raises(
            DiscordMemoryCompletionTransportError,
            match="Job/Outbox persistence failed",
        ):
            _complete(service, turn, running, "delivery-rollback")
    with factory() as database:
        stored = database.get(DiscordSessionTurn, turn.turn_id)
        assert stored is not None and stored.status == "running"
        assert database.scalar(
            select(func.count())
            .select_from(DiscordTurnDelivery)
            .where(DiscordTurnDelivery.turn_id == turn.turn_id)
        ) == 0
    assert _memory_transport_rows(factory) == ([], [])

    retried = _complete(service, turn, running, "delivery-rollback")
    assert retried.status == "completed"
    jobs, events = _memory_transport_rows(factory)
    assert len(jobs) == len(events) == 1


def test_completion_retry_and_concurrent_retry_create_one_pair(
    memory_transport,
):
    factory, prefix = memory_transport
    resolver, service = _service(factory, enabled=True)
    _, turn, running = _execute(resolver, service, guild_id=prefix)
    barrier = threading.Barrier(2)

    def complete():
        barrier.wait(timeout=10)
        return _complete(service, turn, running, "delivery-concurrent")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: complete(), range(2)))
    assert [item.status for item in results] == ["completed", "completed"]
    retry = _complete(service, turn, running, "delivery-concurrent")
    assert retry.status == "completed"
    jobs, events = _memory_transport_rows(factory)
    assert len(jobs) == len(events) == 1
    with factory() as database:
        assert database.scalar(
            select(func.count())
            .select_from(DiscordTurnDelivery)
            .where(DiscordTurnDelivery.turn_id == turn.turn_id)
        ) == 1


def test_disabled_flag_completes_without_memory_transport(memory_transport):
    factory, prefix = memory_transport
    resolver, service = _service(factory, enabled=False)
    _, turn, running = _execute(resolver, service, guild_id=prefix)
    assert _complete(service, turn, running).status == "completed"
    assert _memory_transport_rows(factory) == ([], [])


@pytest.mark.parametrize(
    "ineligible_case",
    ["author_missing", "session_inactive", "thread"],
)
def test_ineligible_completion_fails_closed(memory_transport, ineligible_case):
    factory, prefix = memory_transport
    resolver, service = _service(factory, enabled=True)
    thread_id = "thread" if ineligible_case == "thread" else None
    resolved, turn, running = _execute(
        resolver,
        service,
        guild_id=prefix,
        thread_id=thread_id,
    )
    if ineligible_case != "thread":
        with factory.begin() as database:
            if ineligible_case == "author_missing":
                stored = database.get(DiscordSessionTurn, turn.turn_id)
                assert stored is not None
                stored.author_id = None
            else:
                session = database.get(
                    DiscordConversationSession,
                    resolved.session_id,
                )
                assert session is not None
                session.status = "closed"
    assert _complete(service, turn, running).status == "completed"
    assert _memory_transport_rows(factory) == ([], [])


def test_no_delivery_failed_cancelled_and_historical_rows_are_not_backfilled(
    memory_transport,
):
    factory, prefix = memory_transport
    resolver, _ = _service(factory, enabled=True)
    resolved = resolver.resolve(prefix, "manual")
    completion = DiscordMemoryCompletionService(
        enabled=True,
        extractor_schema_version="v1",
        max_attempts=3,
    )
    with factory.begin() as database:
        for sequence, status in enumerate(
            ("completed", "failed", "cancelled"),
            start=1,
        ):
            database.add(
                DiscordSessionTurn(
                    id=uuid4(),
                    session_id=resolved.session_id,
                    discord_message_id=f"manual-{sequence}",
                    sequence_number=sequence,
                    request_text="source",
                    response_text="response",
                    author_id="author-a",
                    author_display_name="Author A",
                    status=status,
                )
            )
        database.flush()
        historical = database.scalar(
            select(DiscordSessionTurn).where(
                DiscordSessionTurn.session_id == resolved.session_id,
                DiscordSessionTurn.sequence_number == 1,
            )
        )
        assert historical is not None
        outcome = completion.on_first_completion(database, historical.id)
        assert outcome is not None
        assert outcome.created is False
        assert outcome.eligibility.reason == "delivery_missing"
    assert _memory_transport_rows(factory) == ([], [])


def test_dm_like_session_without_guild_fails_closed(memory_transport):
    factory, _ = memory_transport
    conversation_id = str(uuid4())
    session_id = uuid4()
    turn_id = uuid4()
    with factory.begin() as database:
        database.add(Conversation(id=conversation_id))
        database.add(
            DiscordConversationSession(
                id=session_id,
                guild_id=" ",
                channel_id="dm-channel",
                backend_conversation_id=uuid4(),
                origin="discord",
                visibility="internal",
                status="active",
            )
        )
        database.add(
            DiscordSessionTurn(
                id=turn_id,
                session_id=session_id,
                discord_message_id=f"dm-{uuid4().hex}",
                sequence_number=1,
                request_text="source",
                response_text="response",
                author_id="author-a",
                author_display_name="Author A",
                status="completed",
            )
        )
        database.flush()
        database.add(
            DiscordTurnDelivery(
                id=uuid4(),
                turn_id=turn_id,
                discord_message_id=f"dm-delivery-{uuid4().hex}",
                chunk_index=0,
            )
        )
    with factory.begin() as database:
        outcome = DiscordMemoryCompletionService(
            enabled=True,
            extractor_schema_version="v1",
            max_attempts=3,
        ).on_first_completion(database, turn_id)
        assert outcome is not None
        assert outcome.created is False
        assert outcome.eligibility.reason == "source_ineligible"
    with factory.begin() as database:
        database.execute(
            delete(DiscordConversationSession).where(
                DiscordConversationSession.id == session_id
            )
        )
        database.execute(
            delete(Conversation).where(Conversation.id == conversation_id)
        )


def test_dispatcher_publishes_memory_job_and_redis_failure_is_retryable(
    memory_transport,
):
    factory, prefix = memory_transport
    resolver, service = _service(factory, enabled=True)
    _, turn, running = _execute(resolver, service, guild_id=prefix)
    _complete(service, turn, running)
    jobs, events = _memory_transport_rows(factory)
    job_id = jobs[0].id
    failing = QueueStub(fail=True)
    assert OutboxDispatcherService(factory, failing).dispatch_pending() == 0
    with factory() as database:
        event = database.get(OutboxEvent, events[0].id)
        stored_turn = database.get(DiscordSessionTurn, turn.turn_id)
        assert event is not None and event.status == "retrying"
        assert stored_turn is not None and stored_turn.status == "completed"
    with factory.begin() as database:
        event = database.get(OutboxEvent, events[0].id)
        assert event is not None
        event.available_at = None
    healthy = QueueStub()
    assert OutboxDispatcherService(factory, healthy).dispatch_pending() == 1
    assert healthy.calls == [(DISCORD_MEMORY_INGEST_JOB_TYPE, job_id)]


def test_two_dispatchers_publish_one_logical_memory_delivery(memory_transport):
    factory, prefix = memory_transport
    resolver, service = _service(factory, enabled=True)
    _, turn, running = _execute(resolver, service, guild_id=prefix)
    _complete(service, turn, running)
    queue = QueueStub()
    barrier = threading.Barrier(2)

    def dispatch():
        barrier.wait(timeout=10)
        return OutboxDispatcherService(factory, queue).dispatch_pending()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: dispatch(), range(2)))
    assert sum(results) == 1
    assert len(queue.calls) == 1


def test_unknown_outbox_job_type_fails_closed(memory_transport):
    factory, prefix = memory_transport
    job_id = f"{prefix}-unknown-job"
    with factory.begin() as database:
        database.add(
            Job(
                id=job_id,
                job_type="unknown_job_type",
                status="queued",
                max_attempts=3,
                idempotency_key=f"{prefix}-unknown-key",
                payload={},
            )
        )
        database.add(
            OutboxEvent(
                id=new_id("outbox"),
                event_type="JOB_ENQUEUE_REQUESTED",
                aggregate_type="job",
                aggregate_id=job_id,
                idempotency_key=f"job_enqueue:{prefix}-unknown-key",
                job_id=job_id,
                payload={
                    "job_id": job_id,
                    "job_type": "unknown_job_type",
                },
                status="pending",
            )
        )

    class RegistryQueue:
        def enqueue(self, job_type, job_id):
            resolve_job_route(
                job_type,
                memory_queue_name="memory_extract",
            )
            raise AssertionError("unknown route unexpectedly resolved")

    assert OutboxDispatcherService(
        factory,
        RegistryQueue(),
    ).dispatch_pending() == 0
    with factory() as database:
        event = database.scalar(
            select(OutboxEvent).where(OutboxEvent.job_id == job_id)
        )
        assert event is not None
        assert event.status == "failed"
        assert "unsupported durable job type" in (event.last_error or "")


def test_worker_filters_one_candidate_receipt_and_creates_no_memory(
    memory_transport,
):
    factory, prefix = memory_transport
    resolver, service = _service(factory, enabled=True)
    _, turn, running = _execute(
        resolver,
        service,
        guild_id=prefix,
        author_id="stable-author",
        display_name="Display Snapshot",
    )
    _complete(service, turn, running)
    jobs, _ = _memory_transport_rows(factory)
    worker = DiscordMemoryWorkerService(
        factory,
        worker_id="memory-worker-a",
        lease_seconds=30,
    )
    first = worker.process(jobs[0].id)
    duplicate = worker.process(jobs[0].id)
    assert first.status == "completed"
    assert first.created is True
    assert duplicate.status == "not_claimed"
    assert duplicate.reason == "completed"
    with factory() as database:
        candidates = list(database.scalars(select(DiscordMemoryCandidate)))
        assert len(candidates) == 1
        candidate = candidates[0]
        assert str(candidate.id) == first.candidate_id
        assert candidate.source_turn_id == turn.turn_id
        assert candidate.session_id == turn.session_id
        assert candidate.source_author_id == "stable-author"
        assert candidate.source_author_display_name == "Display Snapshot"
        assert candidate.guild_id == prefix
        assert candidate.filter_decision == "candidate"
        assert candidate.filter_reason_code == "explicit_remember"
        assert candidate.validation_status == "pending"
        assert candidate.decision == "deferred"
        assert candidate.normalized_output["rule_filter"] == {
            "stage": "rule_filter",
            "policy_version": "discord_memory_rule_filter_v1",
            "decision": "candidate",
            "reason_code": "explicit_remember",
            "candidate_strength": "strong",
            "detected_intent": "remember",
            "matched_rules": ["explicit_remember"],
        }
        assert candidate.normalized_output["extractor"] == {
            "status": "disabled",
            "reason_code": "extractor_disabled",
            "model": "qwen3.5:2b",
            "schema_version": "v1",
        }
        assert candidate.error_code == "extractor_disabled"
        assert candidate.raw_output is None
        assert candidate.operation is None
        assert candidate.canonical_fact is None
        assert candidate.subject_id is None
        assert candidate.extractor_model == "qwen3.5:2b"
        assert database.scalar(
            select(func.count()).select_from(DiscordMemory)
        ) == 0
        assert database.scalar(
            select(func.count()).select_from(DiscordMemorySource)
        ) == 0
        stored_job = database.get(Job, jobs[0].id)
        assert stored_job is not None and stored_job.status == "completed"
        assert (
            stored_job.worker_id
            is stored_job.lease_expires_at
            is stored_job.heartbeat_at
            is None
        )


def test_memory_job_claim_heartbeat_and_lease_ownership(memory_transport):
    factory, prefix = memory_transport
    resolver, service = _service(factory, enabled=True)
    _, turn, running = _execute(resolver, service, guild_id=prefix)
    _complete(service, turn, running)
    jobs, _ = _memory_transport_rows(factory)
    with factory.begin() as database:
        repository = DiscordMemoryJobRepository(database)
        claimed = repository.claim_job(
            jobs[0].id,
            worker_id="memory-worker-a",
            lease_seconds=30,
        )
        assert claimed is not None
        assert claimed.status == "running"
        assert claimed.attempts == 1
        assert claimed.worker_id == "memory-worker-a"
        assert claimed.heartbeat_at is not None
        assert claimed.lease_expires_at is not None
        assert repository.heartbeat(
            jobs[0].id,
            worker_id="memory-worker-a",
            lease_seconds=30,
        )
        assert not repository.heartbeat(
            jobs[0].id,
            worker_id="other-worker",
            lease_seconds=30,
        )


def test_worker_persists_terminal_no_op_without_model_or_memory(
    memory_transport,
):
    factory, prefix = memory_transport
    resolver, service = _service(factory, enabled=True)
    _, turn, running = _execute(
        resolver,
        service,
        guild_id=prefix,
        request_text="Tôi có một cốc trà sữa.",
    )
    _complete(service, turn, running)
    jobs, _ = _memory_transport_rows(factory)
    extractor = ExtractorStub(error=AssertionError("extractor must not run"))
    outcome = DiscordMemoryWorkerService(
        factory,
        worker_id="memory-worker-no-op",
        lease_seconds=30,
        extractor_enabled=True,
        extractor=extractor,
    ).process(jobs[0].id)
    assert outcome.status == "completed"
    assert extractor.calls == []
    with factory() as database:
        candidate = database.scalar(
            select(DiscordMemoryCandidate).where(
                DiscordMemoryCandidate.source_turn_id == turn.turn_id
            )
        )
        assert candidate is not None
        assert candidate.filter_decision == "no_op"
        assert candidate.filter_reason_code == "transient_state"
        assert candidate.validation_status == "not_required"
        assert candidate.decision == "no_op"
        assert candidate.normalized_output["policy_version"] == (
            "discord_memory_rule_filter_v1"
        )
        assert candidate.operation is None
        assert database.scalar(
            select(func.count()).select_from(DiscordMemory)
        ) == 0
        assert database.scalar(
            select(func.count()).select_from(DiscordMemorySource)
        ) == 0


def test_worker_filter_exception_retries_without_touching_completed_turn(
    memory_transport,
):
    class BrokenFilter:
        def evaluate(self, source):
            raise RuntimeError("deterministic filter unavailable")

    factory, prefix = memory_transport
    resolver, service = _service(factory, enabled=True)
    _, turn, running = _execute(resolver, service, guild_id=prefix)
    _complete(service, turn, running, "delivery-filter-failure")
    jobs, _ = _memory_transport_rows(factory)
    outcome = DiscordMemoryWorkerService(
        factory,
        worker_id="memory-worker-filter-error",
        lease_seconds=30,
        rule_filter=BrokenFilter(),
    ).process(jobs[0].id)
    assert outcome.status == "retrying"
    assert outcome.reason == "memory_rule_filter_error"
    with factory() as database:
        stored_turn = database.get(DiscordSessionTurn, turn.turn_id)
        delivery = database.scalar(
            select(DiscordTurnDelivery).where(
                DiscordTurnDelivery.turn_id == turn.turn_id
            )
        )
        assert stored_turn is not None and stored_turn.status == "completed"
        assert delivery is not None
        assert database.scalar(
            select(func.count()).select_from(DiscordMemory)
        ) == 0
        assert database.scalar(
            select(func.count()).select_from(DiscordMemorySource)
        ) == 0


def test_worker_persists_policy_rejection_when_policy_is_disabled(
    memory_transport,
):
    factory, prefix = memory_transport
    resolver, service = _service(factory, enabled=True)
    _, turn, running = _execute(resolver, service, guild_id=prefix)
    _complete(service, turn, running)
    jobs, _ = _memory_transport_rows(factory)
    extractor = ExtractorStub(error=AssertionError("extractor must not run"))
    outcome = DiscordMemoryWorkerService(
        factory,
        worker_id="memory-worker-policy-off",
        lease_seconds=30,
        memory_policy_enabled=False,
        extractor_enabled=True,
        extractor=extractor,
    ).process(jobs[0].id)
    assert outcome.status == "completed"
    assert extractor.calls == []
    with factory() as database:
        candidate = database.scalar(
            select(DiscordMemoryCandidate).where(
                DiscordMemoryCandidate.source_turn_id == turn.turn_id
            )
        )
        assert candidate is not None
        assert candidate.filter_decision == "rejected_policy"
        assert candidate.filter_reason_code == "memory_policy_disabled"
        assert candidate.validation_status == "rejected"
        assert candidate.decision == "rejected"
        assert candidate.normalized_output["candidate_strength"] == "none"


def test_worker_persists_valid_proposal_once_without_applying_memory(
    memory_transport,
):
    factory, prefix = memory_transport
    resolver, service = _service(factory, enabled=True)
    _, turn, running = _execute(
        resolver,
        service,
        guild_id=prefix,
        author_id="stable-author",
        display_name="Mutable Snapshot",
        request_text="Hãy nhớ rằng tôi ưu tiên dùng tiếng Việt.",
    )
    _complete(service, turn, running, "delivery-extractor-valid")
    jobs, _ = _memory_transport_rows(factory)
    extractor = ExtractorStub()
    worker = DiscordMemoryWorkerService(
        factory,
        worker_id="memory-extractor-a",
        lease_seconds=30,
        extractor_enabled=True,
        extractor=extractor,
    )
    first = worker.process(jobs[0].id)
    duplicate = worker.process(jobs[0].id)
    assert first.status == "completed"
    assert first.reason == "extractor_proposal_deferred"
    assert duplicate.status == "not_claimed"
    assert len(extractor.calls) == 1
    envelope = extractor.calls[0]
    assert envelope.current_author_id == "stable-author"
    assert envelope.trusted_subjects[0].subject_id == "stable-author"
    assert not hasattr(envelope, "author_display_name")
    with factory() as database:
        candidate = database.scalar(
            select(DiscordMemoryCandidate).where(
                DiscordMemoryCandidate.source_turn_id == turn.turn_id
            )
        )
        assert candidate is not None
        assert candidate.extractor_model == "qwen3.5:2b"
        assert candidate.raw_output["operation"] == "create"
        assert candidate.normalized_output["rule_filter"]["decision"] == (
            "candidate"
        )
        proposal = candidate.normalized_output["extractor_proposal"]
        assert proposal["source_turn_id"] == str(turn.turn_id)
        assert proposal["subject_id"] == "stable-author"
        assert candidate.operation == "create"
        assert candidate.subject_id == "stable-author"
        assert candidate.validation_status == "pending"
        assert candidate.decision == "deferred"
        assert candidate.error_code is None
        stored_turn = database.get(DiscordSessionTurn, turn.turn_id)
        assert stored_turn is not None
        assert stored_turn.request_text == (
            "Hãy nhớ rằng tôi ưu tiên dùng tiếng Việt."
        )
        assert stored_turn.status == "completed"
        assert database.scalar(
            select(func.count()).select_from(DiscordMemory)
        ) == 0
        assert database.scalar(
            select(func.count()).select_from(DiscordMemorySource)
        ) == 0
    with factory.begin() as database:
        candidate = database.scalar(
            select(DiscordMemoryCandidate).where(
                DiscordMemoryCandidate.source_turn_id == turn.turn_id
            )
        )
        assert candidate is not None
        repository = DiscordMemoryRepository(database)
        _, changed = repository.record_extractor_proposal(
            candidate.id,
            guild_id=prefix,
            extractor_model="qwen3.5:2b",
            raw_output=candidate.raw_output,
            proposal=candidate.normalized_output["extractor_proposal"],
            prompt_version="discord_memory_extractor_prompt_v1",
            format_mode="json_schema",
            latency_ms=999,
        )
        assert changed is False
        with pytest.raises(DiscordMemoryConflictError):
            repository.record_extractor_proposal(
                candidate.id,
                guild_id=prefix,
                extractor_model="qwen3.5:2b",
                raw_output={
                    **candidate.raw_output,
                    "canonical_fact": "different proposal",
                },
                proposal={
                    **candidate.normalized_output["extractor_proposal"],
                    "canonical_fact": "different proposal",
                },
                prompt_version="discord_memory_extractor_prompt_v1",
                format_mode="json_schema",
                latency_ms=999,
            )


def test_schema_invalid_output_is_terminal_rejected_without_memory(
    memory_transport,
):
    factory, prefix = memory_transport
    resolver, service = _service(factory, enabled=True)
    _, turn, running = _execute(resolver, service, guild_id=prefix)
    _complete(service, turn, running)
    jobs, _ = _memory_transport_rows(factory)
    extractor = ExtractorStub(
        error=DiscordMemoryExtractorOutputError(
            "extractor_schema_invalid",
            "invalid deterministic output",
            raw_output={"schema_version": "v1", "unexpected": True},
        )
    )
    outcome = DiscordMemoryWorkerService(
        factory,
        worker_id="memory-extractor-invalid",
        lease_seconds=30,
        extractor_enabled=True,
        extractor=extractor,
    ).process(jobs[0].id)
    assert outcome.status == "completed"
    assert outcome.reason == "extractor_schema_invalid"
    assert len(extractor.calls) == 1
    with factory() as database:
        candidate = database.scalar(
            select(DiscordMemoryCandidate).where(
                DiscordMemoryCandidate.source_turn_id == turn.turn_id
            )
        )
        assert candidate is not None
        assert candidate.validation_status == "rejected"
        assert candidate.decision == "rejected"
        assert candidate.error_code == "extractor_schema_invalid"
        assert candidate.raw_output == {
            "schema_version": "v1",
            "unexpected": True,
        }
        assert "extractor_proposal" not in candidate.normalized_output
        assert database.scalar(
            select(func.count()).select_from(DiscordMemory)
        ) == 0
        assert database.scalar(
            select(func.count()).select_from(DiscordMemorySource)
        ) == 0


def test_transport_retry_keeps_same_candidate_and_completed_discord_turn(
    memory_transport,
):
    factory, prefix = memory_transport
    resolver, service = _service(factory, enabled=True)
    _, turn, running = _execute(resolver, service, guild_id=prefix)
    _complete(service, turn, running, "delivery-extractor-timeout")
    jobs, _ = _memory_transport_rows(factory)
    failing = ExtractorStub(
        error=DiscordMemoryExtractorTransportError("temporary timeout")
    )
    first = DiscordMemoryWorkerService(
        factory,
        worker_id="memory-extractor-timeout",
        lease_seconds=30,
        extractor_enabled=True,
        extractor=failing,
    ).process(jobs[0].id)
    assert first.status == "retrying"
    with factory.begin() as database:
        candidates = list(database.scalars(select(DiscordMemoryCandidate)))
        assert len(candidates) == 1
        candidate_id = candidates[0].id
        assert candidates[0].raw_output is None
        assert candidates[0].filter_decision == "candidate"
        job = database.get(Job, jobs[0].id)
        assert job is not None
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
        stored_turn = database.get(DiscordSessionTurn, turn.turn_id)
        assert stored_turn is not None and stored_turn.status == "completed"

    succeeding = ExtractorStub()
    second = DiscordMemoryWorkerService(
        factory,
        worker_id="memory-extractor-retry",
        lease_seconds=30,
        extractor_enabled=True,
        extractor=succeeding,
    ).process(jobs[0].id)
    assert second.status == "completed"
    assert second.candidate_id == str(candidate_id)
    assert len(failing.calls) == 1
    assert len(succeeding.calls) == 1
    with factory() as database:
        assert database.scalar(
            select(func.count()).select_from(DiscordMemoryCandidate)
        ) == 1
        delivery = database.scalar(
            select(DiscordTurnDelivery).where(
                DiscordTurnDelivery.turn_id == turn.turn_id
            )
        )
        assert delivery is not None
        assert delivery.discord_message_id == "delivery-extractor-timeout"


def test_worker_fails_closed_when_source_disappears_after_dispatch(
    memory_transport,
):
    factory, prefix = memory_transport
    resolver, service = _service(factory, enabled=True)
    _, turn, running = _execute(resolver, service, guild_id=prefix)
    _complete(service, turn, running)
    jobs, _ = _memory_transport_rows(factory)
    with factory.begin() as database:
        database.execute(
            delete(DiscordSessionTurn).where(
                DiscordSessionTurn.id == turn.turn_id
            )
        )
    outcome = DiscordMemoryWorkerService(
        factory,
        worker_id="memory-worker-a",
        lease_seconds=30,
    ).process(jobs[0].id)
    assert outcome.status == "failed"
    assert outcome.reason == "source_missing"
    with factory() as database:
        assert database.scalar(
            select(func.count()).select_from(DiscordMemoryCandidate)
        ) == 0


def test_worker_revalidates_source_and_does_not_change_completed_turn(
    memory_transport,
):
    factory, prefix = memory_transport
    resolver, service = _service(factory, enabled=True)
    resolved, turn, running = _execute(resolver, service, guild_id=prefix)
    _complete(service, turn, running)
    jobs, _ = _memory_transport_rows(factory)
    with factory.begin() as database:
        session = database.get(
            DiscordConversationSession,
            resolved.session_id,
        )
        assert session is not None
        session.status = "closed"
    outcome = DiscordMemoryWorkerService(
        factory,
        worker_id="memory-worker-a",
        lease_seconds=30,
    ).process(jobs[0].id)
    assert outcome.status == "failed"
    assert outcome.reason == "session_inactive"
    with factory() as database:
        stored_turn = database.get(DiscordSessionTurn, turn.turn_id)
        assert stored_turn is not None and stored_turn.status == "completed"
        assert database.scalar(
            select(func.count()).select_from(DiscordMemoryCandidate)
        ) == 0


def test_worker_error_retries_without_changing_turn_or_delivery(
    memory_transport,
    monkeypatch,
):
    factory, prefix = memory_transport
    resolver, service = _service(factory, enabled=True)
    _, turn, running = _execute(resolver, service, guild_id=prefix)
    _complete(service, turn, running, "delivery-worker-failure")
    jobs, _ = _memory_transport_rows(factory)
    monkeypatch.setattr(
        DiscordMemoryRepository,
        "create_or_get_candidate",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("foundation unavailable")
        ),
    )
    outcome = DiscordMemoryWorkerService(
        factory,
        worker_id="memory-worker-a",
        lease_seconds=30,
    ).process(jobs[0].id)
    assert outcome.status == "retrying"
    with factory() as database:
        job = database.get(Job, jobs[0].id)
        turn_row = database.get(DiscordSessionTurn, turn.turn_id)
        delivery = database.scalar(
            select(DiscordTurnDelivery).where(
                DiscordTurnDelivery.turn_id == turn.turn_id
            )
        )
        assert job is not None and job.status == "retrying"
        assert turn_row is not None and turn_row.status == "completed"
        assert delivery is not None
        assert delivery.discord_message_id == "delivery-worker-failure"


def _make_stale_memory_job(factory, prefix, *, exhausted: bool = False):
    resolver, service = _service(factory, enabled=True)
    _, turn, running = _execute(resolver, service, guild_id=prefix)
    _complete(service, turn, running)
    jobs, events = _memory_transport_rows(factory)
    job = jobs[-1]
    old = datetime.now(UTC) - timedelta(minutes=5)
    with factory.begin() as database:
        stored = database.get(Job, job.id)
        assert stored is not None
        stored.status = "running"
        stored.attempts = stored.max_attempts if exhausted else 1
        stored.worker_id = "dead-memory-worker"
        stored.heartbeat_at = old
        stored.lease_expires_at = old
        stored.redis_job_id = job.id
        event = database.get(OutboxEvent, events[-1].id)
        assert event is not None
        event.status = "completed"
    return turn.turn_id, job.id


@pytest.mark.parametrize(
    ("exhausted", "expected_status"),
    [(False, "retrying"), (True, "failed")],
)
def test_memory_stale_recovery_is_job_type_isolated(
    memory_transport,
    exhausted,
    expected_status,
):
    factory, prefix = memory_transport
    turn_id, job_id = _make_stale_memory_job(
        factory,
        prefix,
        exhausted=exhausted,
    )
    document_job_id = f"{prefix}-document-job"
    old = datetime.now(UTC) - timedelta(minutes=5)
    with factory.begin() as database:
        database.add(
            Job(
                id=document_job_id,
                job_type="extract_document",
                status="running",
                attempts=1,
                max_attempts=3,
                worker_id="document-worker",
                heartbeat_at=old,
                lease_expires_at=old,
                idempotency_key=f"{prefix}-document-key",
                payload={},
            )
        )
    assert DiscordMemoryRecoveryService(factory).recover_stale() == 1
    with factory() as database:
        memory_job = database.get(Job, job_id)
        document_job = database.get(Job, document_job_id)
        turn = database.get(DiscordSessionTurn, turn_id)
        assert memory_job is not None and memory_job.status == expected_status
        assert memory_job.worker_id is None
        assert document_job is not None and document_job.status == "running"
        assert turn is not None and turn.status == "completed"
        event = database.scalar(
            select(OutboxEvent).where(OutboxEvent.job_id == job_id)
        )
        if exhausted:
            assert event is not None and event.status == "completed"
        else:
            assert event is not None and event.status == "retrying"


def test_document_recovery_does_not_touch_memory_job(memory_transport):
    factory, prefix = memory_transport
    _, job_id = _make_stale_memory_job(factory, prefix)

    class NoQueue:
        def enqueue(self, *args, **kwargs):
            raise AssertionError("document recovery routed a memory job")

    assert JobRecoveryService(factory, NoQueue()).recover_stale() == 0
    with factory() as database:
        job = database.get(Job, job_id)
        assert job is not None and job.status == "running"


@pytest.mark.parametrize(
    ("enabled", "expected_status", "expected_worker"),
    [(False, "ok", "disabled"), (True, "degraded", "unavailable")],
)
def test_memory_health_and_metrics_are_observable_without_real_redis(
    memory_transport,
    monkeypatch,
    enabled,
    expected_status,
    expected_worker,
):
    factory, _ = memory_transport

    class FakeRedis:
        def ping(self):
            return True

    class FakeQueue:
        def __init__(self, *_args, **_kwargs):
            self.count = 0

    monkeypatch.setattr(
        operational_service.Redis,
        "from_url",
        lambda *_: FakeRedis(),
    )
    monkeypatch.setattr(
        operational_service.Worker,
        "all",
        lambda **_: [],
    )
    monkeypatch.setattr(operational_service, "Queue", FakeQueue)
    service = OperationalService(
        sessions=factory,
        redis_url="redis://unused",
        prefix="local-ai:test",
        qdrant=SimpleNamespace(healthcheck=lambda: True),
        ollama=SimpleNamespace(healthcheck=lambda: True),
        memory_ingestion_enabled=enabled,
        memory_queue_name="memory_extract",
    )
    health = service.health()
    metrics = service.metrics()
    assert health["status"] == expected_status
    assert health["worker_memory"] == expected_worker
    assert health["memory_queue"] == "local-ai:test:memory_extract"
    assert metrics["memory_jobs_pending"] == 0
    assert metrics["memory_jobs_retrying"] == 0
    assert metrics["memory_jobs_failed"] == 0
    assert metrics["memory_outbox_pending"] == 0
    assert metrics["memory_outbox_retrying"] == 0
    assert metrics["memory_outbox_processing"] == 0
    assert metrics["queue_length"]["memory"] == 0
