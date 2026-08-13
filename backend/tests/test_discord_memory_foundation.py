from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.discord_memory_repositories import (
    DiscordMemoryConflictError,
    DiscordMemoryIdentity,
    DiscordMemoryRepository,
)
from app.postgres.discord_repositories import DiscordSessionRepository
from app.postgres.models import (
    Conversation,
    DiscordConversationSession,
    DiscordMemory,
    DiscordMemoryCandidate,
    DiscordMemorySource,
    DiscordSessionTurn,
)
from app.services.discord_session_service import DiscordSessionService


URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")


@pytest.fixture
def memory_database():
    assert URL is not None
    database_name = make_url(URL).database or ""
    assert database_name == "local_ai_core_test"
    assert database_name != "local_ai_core"
    factory = create_session_factory(create_postgres_engine(URL))
    prefix = f"sprint2b2-{uuid4().hex}"
    yield factory, prefix
    with factory.begin() as database:
        candidate_ids = list(
            database.scalars(
                select(DiscordMemoryCandidate.id).where(
                    DiscordMemoryCandidate.guild_id.like(f"{prefix}%")
                )
            )
        )
        memory_ids = list(
            database.scalars(
                select(DiscordMemory.id).where(
                    DiscordMemory.guild_id.like(f"{prefix}%")
                )
            )
        )
        if candidate_ids:
            database.execute(
                update(DiscordMemoryCandidate)
                .where(DiscordMemoryCandidate.id.in_(candidate_ids))
                .values(target_memory_id=None)
            )
        if memory_ids:
            database.execute(
                delete(DiscordMemorySource).where(
                    DiscordMemorySource.memory_id.in_(memory_ids)
                )
            )
            database.execute(
                delete(DiscordMemory).where(DiscordMemory.id.in_(memory_ids))
            )
        if candidate_ids:
            database.execute(
                delete(DiscordMemoryCandidate).where(
                    DiscordMemoryCandidate.id.in_(candidate_ids)
                )
            )
        conversation_ids = list(
            database.scalars(
                select(DiscordConversationSession.backend_conversation_id).where(
                    DiscordConversationSession.guild_id.like(f"{prefix}%")
                )
            )
        )
        database.execute(
            delete(DiscordConversationSession).where(
                DiscordConversationSession.guild_id.like(f"{prefix}%")
            )
        )
        if conversation_ids:
            database.execute(
                delete(Conversation).where(
                    Conversation.id.in_([str(value) for value in conversation_ids])
                )
            )


def _create_turn(
    factory,
    *,
    guild_id: str,
    channel_id: str = "channel",
    thread_id: str | None = None,
    author_id: str = "author-a",
    display_name: str = "Author A",
    discord_message_id: str | None = None,
) -> tuple[UUID, UUID, str]:
    resolved = DiscordSessionService(factory).resolve(
        guild_id,
        channel_id,
        thread_id,
    )
    message_id = discord_message_id or f"message-{uuid4().hex}"
    with factory.begin() as database:
        turn, created = DiscordSessionRepository(database).enqueue_turn(
            resolved.session_id,
            message_id,
            "durable source evidence",
            author_id=author_id,
            author_display_name=display_name,
        )
        assert created
        turn.status = "completed"
        turn.response_text = "acknowledged"
        database.flush()
        turn_id = turn.id
    return resolved.session_id, turn_id, message_id


def _create_candidate(
    factory,
    *,
    guild_id: str,
    channel_id: str = "channel",
    thread_id: str | None = None,
    author_id: str = "author-a",
    display_name: str = "Author A",
    schema_version: str = "discord-memory-v1",
    discord_message_id: str | None = None,
) -> UUID:
    session_id, turn_id, message_id = _create_turn(
        factory,
        guild_id=guild_id,
        channel_id=channel_id,
        thread_id=thread_id,
        author_id=author_id,
        display_name=display_name,
        discord_message_id=discord_message_id,
    )
    with factory.begin() as database:
        candidate, created = DiscordMemoryRepository(
            database
        ).create_or_get_candidate(
            source_turn_id=turn_id,
            session_id=session_id,
            source_discord_message_id=message_id,
            source_author_id=author_id,
            source_author_display_name=display_name,
            guild_id=guild_id,
            channel_id=channel_id,
            thread_id=thread_id,
            extractor_schema_version=schema_version,
            filter_decision="candidate",
            filter_reason_code="explicit_remember",
        )
        assert created
        candidate_id = candidate.id
    return candidate_id


def _identity(
    guild_id: str,
    *,
    scope: str = "member_in_guild",
    subject_id: str = "author-a",
    channel_id: str | None = None,
    thread_id: str | None = None,
    fact_key: str = "preference.drink",
) -> DiscordMemoryIdentity:
    return DiscordMemoryIdentity(
        guild_id=guild_id,
        scope=scope,
        subject_type="discord_member",
        subject_id=subject_id,
        fact_key=fact_key,
        channel_id=channel_id,
        thread_id=thread_id,
    )


def _create_memory(
    factory,
    *,
    candidate_id: UUID,
    identity: DiscordMemoryIdentity,
    fact: str = "Thích trà sữa",
) -> UUID:
    with factory.begin() as database:
        memory, created = DiscordMemoryRepository(database).create_active_version(
            candidate_id=candidate_id,
            identity=identity,
            canonical_fact=fact,
            memory_type="preference",
            extractor_model="test-extractor",
            extractor_schema_version="discord-memory-v1",
            evidence_hash=f"sha256:{uuid4().hex}",
        )
        assert created
        return memory.id


def test_candidate_idempotency_ignores_display_name_but_not_stable_identity(
    memory_database,
):
    factory, prefix = memory_database
    session_id, turn_id, message_id = _create_turn(
        factory,
        guild_id=prefix,
        display_name="Old Name",
    )
    values = {
        "source_turn_id": turn_id,
        "session_id": session_id,
        "source_discord_message_id": message_id,
        "source_author_id": "author-a",
        "source_author_display_name": "Old Name",
        "guild_id": prefix,
        "channel_id": "channel",
        "thread_id": None,
        "extractor_schema_version": "discord-memory-v1",
        "filter_decision": "candidate",
        "filter_reason_code": "explicit_remember",
    }
    with factory.begin() as database:
        repository = DiscordMemoryRepository(database)
        first, first_created = repository.create_or_get_candidate(**values)
        renamed, renamed_created = repository.create_or_get_candidate(
            **{**values, "source_author_display_name": "New Name"}
        )
        assert first_created is True
        assert renamed_created is False
        assert renamed.id == first.id
        assert renamed.source_author_id == "author-a"
        assert renamed.source_author_display_name == "Old Name"

    with factory.begin() as database:
        turn = database.get(DiscordSessionTurn, turn_id)
        assert turn is not None
        turn.author_id = "author-b"
    with factory.begin() as database:
        with pytest.raises(DiscordMemoryConflictError):
            DiscordMemoryRepository(database).create_or_get_candidate(**values)


def test_candidate_message_key_conflict_and_guild_scoped_lookup(memory_database):
    factory, prefix = memory_database
    shared_message_id = f"shared-{uuid4().hex}"
    first_id = _create_candidate(
        factory,
        guild_id=prefix,
        discord_message_id=shared_message_id,
    )
    other_guild = f"{prefix}-other"
    session_id, turn_id, _ = _create_turn(
        factory,
        guild_id=other_guild,
        discord_message_id=shared_message_id,
    )
    with factory.begin() as database:
        repository = DiscordMemoryRepository(database)
        with pytest.raises(DiscordMemoryConflictError):
            repository.create_or_get_candidate(
                source_turn_id=turn_id,
                session_id=session_id,
                source_discord_message_id=shared_message_id,
                source_author_id="author-a",
                source_author_display_name="Same Name",
                guild_id=other_guild,
                channel_id="channel",
                thread_id=None,
                extractor_schema_version="discord-memory-v1",
                filter_decision="candidate",
                filter_reason_code="explicit_remember",
            )
        assert repository.get_candidate(first_id, guild_id=prefix) is not None
        assert repository.get_candidate(first_id, guild_id=other_guild) is None


def test_same_display_name_does_not_merge_two_stable_authors(memory_database):
    factory, prefix = memory_database
    first_id = _create_candidate(
        factory,
        guild_id=prefix,
        author_id="author-a",
        display_name="Same Display",
    )
    second_id = _create_candidate(
        factory,
        guild_id=prefix,
        author_id="author-b",
        display_name="Same Display",
    )
    with factory() as database:
        first = database.get(DiscordMemoryCandidate, first_id)
        second = database.get(DiscordMemoryCandidate, second_id)
        assert first is not None and second is not None
        assert first.id != second.id
        assert first.source_author_display_name == second.source_author_display_name
        assert first.source_author_id != second.source_author_id


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("confidence", Decimal("1.001")),
        ("confidence", Decimal("-0.001")),
        ("operation", "invent"),
        ("scope", "global"),
        ("filter_decision", "maybe"),
        ("filter_reason_code", "unbounded_reason"),
        ("validation_status", "unchecked"),
        ("decision", "mystery"),
    ],
)
def test_candidate_database_constraints_reject_invalid_values(
    memory_database,
    field,
    value,
):
    factory, prefix = memory_database
    candidate_id = _create_candidate(factory, guild_id=prefix)
    with pytest.raises(IntegrityError):
        with factory.begin() as database:
            candidate = database.get(DiscordMemoryCandidate, candidate_id)
            assert candidate is not None
            setattr(candidate, field, value)
            database.flush()


def test_candidate_result_update_is_idempotent_and_optimistic(memory_database):
    factory, prefix = memory_database
    candidate_id = _create_candidate(factory, guild_id=prefix)
    changes = {
        "operation": "create",
        "scope": "member_in_guild",
        "confidence": Decimal("0.950"),
        "validation_status": "accepted",
        "decision": "approved",
    }
    with factory.begin() as database:
        repository = DiscordMemoryRepository(database)
        candidate, changed = repository.update_candidate_result(
            candidate_id,
            guild_id=prefix,
            expected_validation_status="pending",
            **changes,
        )
        assert changed is True
        same, changed_again = repository.update_candidate_result(
            candidate_id,
            guild_id=prefix,
            expected_validation_status="pending",
            **changes,
        )
        assert changed_again is False
        assert same.id == candidate.id
        with pytest.raises(DiscordMemoryConflictError):
            repository.update_candidate_result(
                candidate_id,
                guild_id=prefix,
                expected_validation_status="pending",
                canonical_fact="different result",
            )


def test_rule_filter_result_is_terminal_idempotent_and_versioned(
    memory_database,
):
    factory, prefix = memory_database
    session_id, turn_id, message_id = _create_turn(
        factory,
        guild_id=prefix,
    )
    with factory.begin() as database:
        repository = DiscordMemoryRepository(database)
        candidate, _ = repository.create_or_get_candidate(
            source_turn_id=turn_id,
            session_id=session_id,
            source_discord_message_id=message_id,
            source_author_id="author-a",
            source_author_display_name="Snapshot",
            guild_id=prefix,
            channel_id="channel",
            thread_id=None,
            extractor_schema_version="discord-memory-v1",
            filter_decision="not_run",
            filter_reason_code="foundation_receipt_only",
        )
        first, changed = repository.record_filter_result(
            candidate.id,
            guild_id=prefix,
            policy_version="discord_memory_rule_filter_v1",
            filter_decision="candidate",
            filter_reason_code="explicit_remember",
            candidate_strength="strong",
            detected_intent="remember",
            matched_rules=("explicit_remember",),
        )
        same, changed_again = repository.record_filter_result(
            candidate.id,
            guild_id=prefix,
            policy_version="discord_memory_rule_filter_v1",
            filter_decision="candidate",
            filter_reason_code="explicit_remember",
            candidate_strength="strong",
            detected_intent="remember",
            matched_rules=("explicit_remember",),
        )
        assert changed is True
        assert changed_again is False
        assert same.id == first.id
        with pytest.raises(DiscordMemoryConflictError):
            repository.record_filter_result(
                candidate.id,
                guild_id=prefix,
                policy_version="discord_memory_rule_filter_v2",
                filter_decision="candidate",
                filter_reason_code="explicit_remember",
                candidate_strength="strong",
                detected_intent="remember",
                matched_rules=("explicit_remember",),
            )


def test_extractor_target_lookup_is_exact_guild_member_scope_and_bounded(
    memory_database,
):
    factory, prefix = memory_database
    own_candidate = _create_candidate(
        factory,
        guild_id=prefix,
        author_id="author-a",
    )
    other_member_candidate = _create_candidate(
        factory,
        guild_id=prefix,
        author_id="author-b",
    )
    other_guild_candidate = _create_candidate(
        factory,
        guild_id=f"{prefix}-other",
        author_id="author-a",
    )
    own_memory = _create_memory(
        factory,
        candidate_id=own_candidate,
        identity=_identity(prefix, subject_id="author-a", fact_key="own.fact"),
    )
    _create_memory(
        factory,
        candidate_id=other_member_candidate,
        identity=_identity(
            prefix,
            subject_id="author-b",
            fact_key="other.member.fact",
        ),
    )
    _create_memory(
        factory,
        candidate_id=other_guild_candidate,
        identity=_identity(
            f"{prefix}-other",
            subject_id="author-a",
            fact_key="other.guild.fact",
        ),
    )
    with factory() as database:
        targets = DiscordMemoryRepository(
            database
        ).list_active_extractor_targets(
            guild_id=prefix,
            subject_id="author-a",
        )
        assert [target.memory_id for target in targets] == [own_memory]
        assert all(target.scope == "member_in_guild" for target in targets)
        assert DiscordMemoryRepository(
            database
        ).list_active_extractor_targets(
            guild_id=prefix,
            subject_id="author-a",
            memory_types=("configuration",),
        ) == []


@pytest.mark.parametrize(
    ("scope", "channel_id", "thread_id"),
    [
        ("member_in_guild", None, None),
        ("guild", None, None),
        ("channel", "channel-a", None),
        ("thread", "channel-a", "thread-a"),
    ],
)
def test_every_scope_enforces_one_active_version(
    memory_database,
    scope,
    channel_id,
    thread_id,
):
    factory, prefix = memory_database
    first_candidate = _create_candidate(
        factory,
        guild_id=prefix,
        channel_id=channel_id or "source-channel",
        thread_id=thread_id,
    )
    second_candidate = _create_candidate(
        factory,
        guild_id=prefix,
        channel_id=channel_id or "source-channel",
        thread_id=thread_id,
    )
    identity = _identity(
        prefix,
        scope=scope,
        channel_id=channel_id,
        thread_id=thread_id,
    )
    _create_memory(factory, candidate_id=first_candidate, identity=identity)
    with pytest.raises(DiscordMemoryConflictError):
        _create_memory(factory, candidate_id=second_candidate, identity=identity)
    with factory() as database:
        assert database.scalar(
            select(func.count())
            .select_from(DiscordMemory)
            .where(
                DiscordMemoryRepository._identity_predicate(identity),
                DiscordMemory.status == "active",
            )
        ) == 1


def test_scope_isolation_allows_other_guild_member_channel_and_thread(
    memory_database,
):
    factory, prefix = memory_database
    cases = [
        (_identity(prefix), prefix, "source-a", None, "author-a"),
        (_identity(f"{prefix}-other"), f"{prefix}-other", "source-a", None, "author-a"),
        (
            _identity(prefix, subject_id="author-b"),
            prefix,
            "source-a",
            None,
            "author-b",
        ),
        (
            _identity(prefix, scope="channel", channel_id="channel-a"),
            prefix,
            "channel-a",
            None,
            "author-a",
        ),
        (
            _identity(prefix, scope="channel", channel_id="channel-b"),
            prefix,
            "channel-b",
            None,
            "author-a",
        ),
        (
            _identity(
                prefix,
                scope="thread",
                channel_id="forum",
                thread_id="thread-a",
            ),
            prefix,
            "forum",
            "thread-a",
            "author-a",
        ),
        (
            _identity(
                prefix,
                scope="thread",
                channel_id="forum",
                thread_id="thread-b",
            ),
            prefix,
            "forum",
            "thread-b",
            "author-a",
        ),
    ]
    ids = []
    for identity, guild_id, channel_id, thread_id, author_id in cases:
        candidate_id = _create_candidate(
            factory,
            guild_id=guild_id,
            channel_id=channel_id,
            thread_id=thread_id,
            author_id=author_id,
        )
        ids.append(
            _create_memory(
                factory,
                candidate_id=candidate_id,
                identity=identity,
            )
        )
    assert len(set(ids)) == len(cases)


@pytest.mark.parametrize(
    "identity",
    [
        lambda guild: _identity(
            guild,
            scope="member_in_guild",
            channel_id="invalid",
        ),
        lambda guild: _identity(guild, scope="guild", thread_id="invalid"),
        lambda guild: _identity(guild, scope="channel"),
        lambda guild: _identity(
            guild,
            scope="channel",
            channel_id="channel",
            thread_id="invalid",
        ),
        lambda guild: _identity(guild, scope="thread", channel_id="channel"),
    ],
)
def test_identity_rejects_invalid_scope_location_before_database(
    memory_database,
    identity,
):
    _, prefix = memory_database
    with pytest.raises(ValueError):
        identity(prefix)


def test_database_scope_location_check_cannot_be_bypassed(memory_database):
    factory, prefix = memory_database
    candidate_id = _create_candidate(factory, guild_id=prefix)
    with pytest.raises(IntegrityError):
        with factory.begin() as database:
            database.add(
                DiscordMemory(
                    id=uuid4(),
                    guild_id=prefix,
                    scope="channel",
                    subject_type="discord_member",
                    subject_id="author-a",
                    channel_id=None,
                    thread_id=None,
                    memory_type="preference",
                    fact_key="preference.drink",
                    canonical_fact="invalid",
                    status="active",
                    version=1,
                    origin_candidate_id=candidate_id,
                    valid_from=func.now(),
                    extractor_model="test",
                    extractor_schema_version="discord-memory-v1",
                    validation_status="accepted",
                    index_status="pending",
                )
            )
            database.flush()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", 0),
        ("status", "unknown"),
        ("index_status", "unknown"),
        ("validation_status", "unknown"),
    ],
)
def test_memory_state_constraints_are_database_boundaries(
    memory_database,
    field,
    value,
):
    factory, prefix = memory_database
    candidate_id = _create_candidate(factory, guild_id=prefix)
    values = {
        "id": uuid4(),
        "guild_id": prefix,
        "scope": "member_in_guild",
        "subject_type": "discord_member",
        "subject_id": "author-a",
        "memory_type": "preference",
        "fact_key": f"constraint.{field}",
        "canonical_fact": "test",
        "status": "active",
        "version": 1,
        "origin_candidate_id": candidate_id,
        "valid_from": func.now(),
        "extractor_model": "test",
        "extractor_schema_version": "discord-memory-v1",
        "validation_status": "accepted",
        "index_status": "pending",
    }
    values[field] = value
    with pytest.raises(IntegrityError):
        with factory.begin() as database:
            database.add(DiscordMemory(**values))
            database.flush()


def test_create_and_supersede_retries_with_same_candidate_are_idempotent(
    memory_database,
):
    factory, prefix = memory_database
    identity = _identity(prefix)
    create_candidate = _create_candidate(factory, guild_id=prefix)
    version_one_id = _create_memory(
        factory,
        candidate_id=create_candidate,
        identity=identity,
    )
    with factory.begin() as database:
        same, created = DiscordMemoryRepository(database).create_active_version(
            candidate_id=create_candidate,
            identity=identity,
            canonical_fact="Thích trà sữa",
            memory_type="preference",
            extractor_model="test-extractor",
            extractor_schema_version="discord-memory-v1",
            evidence_hash="sha256:retry",
        )
        assert created is False
        assert same.id == version_one_id

    correction_candidate = _create_candidate(factory, guild_id=prefix)
    with factory.begin() as database:
        version_two, created = DiscordMemoryRepository(
            database
        ).supersede_active_version(
            candidate_id=correction_candidate,
            identity=identity,
            canonical_fact="Thích hồng trà",
            memory_type="preference",
            extractor_model="test-extractor",
            extractor_schema_version="discord-memory-v1",
            evidence_hash="sha256:correction",
        )
        assert created is True
        version_two_id = version_two.id
    with factory.begin() as database:
        same, created = DiscordMemoryRepository(
            database
        ).supersede_active_version(
            candidate_id=correction_candidate,
            identity=identity,
            canonical_fact="Thích hồng trà",
            memory_type="preference",
            extractor_model="test-extractor",
            extractor_schema_version="discord-memory-v1",
            evidence_hash="sha256:correction",
        )
        assert created is False
        assert same.id == version_two_id


def test_versioning_is_immutable_and_source_history_survives_delete(
    memory_database,
):
    factory, prefix = memory_database
    identity = _identity(prefix)
    create_candidate = _create_candidate(factory, guild_id=prefix)
    version_one_id = _create_memory(
        factory,
        candidate_id=create_candidate,
        identity=identity,
        fact="RAM là 16 GB",
    )
    correction_candidate = _create_candidate(factory, guild_id=prefix)
    with factory.begin() as database:
        repository = DiscordMemoryRepository(database)
        version_two, created = repository.supersede_active_version(
            candidate_id=correction_candidate,
            identity=identity,
            canonical_fact="RAM là 32 GB",
            memory_type="configuration",
            extractor_model="test-extractor",
            extractor_schema_version="discord-memory-v1",
            evidence_hash="sha256:correction",
            expected_active_memory_id=version_one_id,
        )
        assert created is True
        assert version_two.version == 2
        version_two_id = version_two.id

    with factory() as database:
        repository = DiscordMemoryRepository(database)
        history = repository.version_history(identity)
        assert [(row.version, row.status) for row in history] == [
            (1, "superseded"),
            (2, "active"),
        ]
        assert history[0].canonical_fact == "RAM là 16 GB"
        assert history[1].canonical_fact == "RAM là 32 GB"
        assert repository.list_sources(version_one_id, guild_id=prefix)
        assert repository.list_sources(version_two_id, guild_id=prefix)

    delete_candidate = _create_candidate(factory, guild_id=prefix)
    with factory.begin() as database:
        deleted = DiscordMemoryRepository(database).mark_deleted(
            candidate_id=delete_candidate,
            identity=identity,
            evidence_hash="sha256:forget",
        )
        assert deleted.id == version_two_id
    with factory() as database:
        repository = DiscordMemoryRepository(database)
        history = repository.version_history(identity)
        assert [(row.version, row.status) for row in history] == [
            (1, "superseded"),
            (2, "deleted"),
        ]
        assert repository.get_active_memory(identity) is None
        roles = {
            source.source_role
            for source in repository.list_sources(version_two_id, guild_id=prefix)
        }
        assert roles == {"correction", "forget_request"}


def test_supersede_transaction_rollback_keeps_old_version_active(memory_database):
    factory, prefix = memory_database
    identity = _identity(prefix)
    create_candidate = _create_candidate(factory, guild_id=prefix)
    version_one_id = _create_memory(
        factory,
        candidate_id=create_candidate,
        identity=identity,
    )
    correction_candidate = _create_candidate(factory, guild_id=prefix)
    with pytest.raises(RuntimeError, match="forced rollback"):
        with factory.begin() as database:
            DiscordMemoryRepository(database).supersede_active_version(
                candidate_id=correction_candidate,
                identity=identity,
                canonical_fact="new value",
                memory_type="preference",
                extractor_model="test-extractor",
                extractor_schema_version="discord-memory-v1",
                evidence_hash="sha256:rollback",
            )
            raise RuntimeError("forced rollback")
    with factory() as database:
        active = DiscordMemoryRepository(database).get_active_memory(identity)
        assert active is not None
        assert active.id == version_one_id
        assert active.version == 1
        assert active.status == "active"


def test_concurrent_create_has_one_winner_and_one_active(memory_database):
    factory, prefix = memory_database
    identity = _identity(prefix)
    candidate_ids = [
        _create_candidate(factory, guild_id=prefix),
        _create_candidate(factory, guild_id=prefix),
    ]
    barrier = threading.Barrier(2)

    def create(candidate_id):
        try:
            with factory.begin() as database:
                barrier.wait(timeout=10)
                memory, _ = DiscordMemoryRepository(database).create_active_version(
                    candidate_id=candidate_id,
                    identity=identity,
                    canonical_fact="one canonical value",
                    memory_type="preference",
                    extractor_model="test-extractor",
                    extractor_schema_version="discord-memory-v1",
                    evidence_hash=f"sha256:{candidate_id}",
                )
                return ("created", memory.id)
        except DiscordMemoryConflictError:
            return ("conflict", None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, candidate_ids))
    assert sorted(result[0] for result in results) == ["conflict", "created"]
    with factory() as database:
        assert database.scalar(
            select(func.count())
            .select_from(DiscordMemory)
            .where(
                DiscordMemoryRepository._identity_predicate(identity),
                DiscordMemory.status == "active",
            )
        ) == 1


def test_concurrent_update_keeps_one_active_version(memory_database):
    factory, prefix = memory_database
    identity = _identity(prefix)
    initial_candidate = _create_candidate(factory, guild_id=prefix)
    version_one_id = _create_memory(
        factory,
        candidate_id=initial_candidate,
        identity=identity,
    )
    candidate_ids = [
        _create_candidate(factory, guild_id=prefix),
        _create_candidate(factory, guild_id=prefix),
    ]
    barrier = threading.Barrier(2)

    def update_memory(pair):
        index, candidate_id = pair
        try:
            with factory.begin() as database:
                barrier.wait(timeout=10)
                memory, _ = DiscordMemoryRepository(
                    database
                ).supersede_active_version(
                    candidate_id=candidate_id,
                    identity=identity,
                    canonical_fact=f"value {index}",
                    memory_type="preference",
                    extractor_model="test-extractor",
                    extractor_schema_version="discord-memory-v1",
                    evidence_hash=f"sha256:{candidate_id}",
                    expected_active_memory_id=version_one_id,
                )
                return ("updated", memory.id)
        except DiscordMemoryConflictError:
            return ("conflict", None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update_memory, enumerate(candidate_ids)))
    assert sorted(result[0] for result in results) == ["conflict", "updated"]
    with factory() as database:
        repository = DiscordMemoryRepository(database)
        history = repository.version_history(identity)
        assert [row.version for row in history] == [1, 2]
        assert sum(row.status == "active" for row in history) == 1


def test_source_attachment_is_idempotent_and_rejects_cross_guild(memory_database):
    factory, prefix = memory_database
    identity = _identity(prefix)
    candidate_id = _create_candidate(factory, guild_id=prefix)
    memory_id = _create_memory(
        factory,
        candidate_id=candidate_id,
        identity=identity,
    )
    with factory.begin() as database:
        repository = DiscordMemoryRepository(database)
        memory = database.get(DiscordMemory, memory_id)
        candidate = database.get(DiscordMemoryCandidate, candidate_id)
        assert memory is not None and candidate is not None
        existing, created = repository.attach_source(
            memory=memory,
            candidate=candidate,
            source_role="primary",
            evidence_hash=repository.list_sources(
                memory_id,
                guild_id=prefix,
            )[0].evidence_hash,
        )
        assert created is False
        assert existing.source_role == "primary"
        supporting, supporting_created = repository.attach_source(
            memory=memory,
            candidate=candidate,
            source_role="supporting",
            evidence_hash="sha256:supporting",
        )
        supporting_retry, retry_created = repository.attach_source(
            memory=memory,
            candidate=candidate,
            source_role="supporting",
            evidence_hash="sha256:supporting",
        )
        assert supporting_created is True
        assert retry_created is False
        assert supporting_retry.source_role == supporting.source_role

    other_candidate_id = _create_candidate(
        factory,
        guild_id=f"{prefix}-other",
    )
    with factory.begin() as database:
        repository = DiscordMemoryRepository(database)
        memory = database.get(DiscordMemory, memory_id)
        candidate = database.get(DiscordMemoryCandidate, other_candidate_id)
        assert memory is not None and candidate is not None
        with pytest.raises(DiscordMemoryConflictError):
            repository.attach_source(
                memory=memory,
                candidate=candidate,
                source_role="supporting",
                evidence_hash="sha256:cross-guild",
            )
        assert repository.list_sources(
            memory_id,
            guild_id=f"{prefix}-other",
        ) == []


def test_source_foreign_keys_and_uniqueness_are_database_boundaries(
    memory_database,
):
    factory, prefix = memory_database
    identity = _identity(prefix)
    candidate_id = _create_candidate(factory, guild_id=prefix)
    memory_id = _create_memory(
        factory,
        candidate_id=candidate_id,
        identity=identity,
    )
    with factory() as database:
        source = database.scalar(
            select(DiscordMemorySource).where(
                DiscordMemorySource.memory_id == memory_id
            )
        )
        assert source is not None
        values = {
            "memory_id": source.memory_id,
            "candidate_id": source.candidate_id,
            "source_turn_id": source.source_turn_id,
            "source_discord_message_id": source.source_discord_message_id,
            "source_author_id": source.source_author_id,
            "source_role": source.source_role,
            "evidence_hash": source.evidence_hash,
        }
    with pytest.raises(IntegrityError):
        with factory.begin() as database:
            database.add(DiscordMemorySource(**values))
            database.flush()
    with pytest.raises(IntegrityError):
        with factory.begin() as database:
            database.add(
                DiscordMemorySource(
                    **{
                        **values,
                        "candidate_id": uuid4(),
                        "source_role": "supporting",
                    }
                )
            )
            database.flush()


def test_source_evidence_restricts_source_turn_deletion(memory_database):
    factory, prefix = memory_database
    identity = _identity(prefix)
    candidate_id = _create_candidate(factory, guild_id=prefix)
    memory_id = _create_memory(
        factory,
        candidate_id=candidate_id,
        identity=identity,
    )
    with factory() as database:
        source_turn_id = database.scalar(
            select(DiscordMemorySource.source_turn_id).where(
                DiscordMemorySource.memory_id == memory_id
            )
        )
        assert source_turn_id is not None
    with pytest.raises(IntegrityError):
        with factory.begin() as database:
            database.execute(
                delete(DiscordSessionTurn).where(
                    DiscordSessionTurn.id == source_turn_id
                )
            )
