from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.discord_repositories import DiscordSessionRepository
from app.postgres.models import Conversation, DiscordConversationSession, DiscordSessionTurn
from app.services.discord_session_service import DiscordDirectMessageUnsupportedError, DiscordSessionService
from app.stores.postgres_auxiliary_store import PostgresAuxiliaryStore


URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")


@pytest.fixture
def discord_database():
    factory = create_session_factory(create_postgres_engine(str(URL)))
    prefix = f"sprint1-{uuid4().hex}"
    yield factory, prefix
    with factory.begin() as database:
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
            database.execute(delete(Conversation).where(Conversation.id.in_(conversation_ids)))
        database.execute(delete(Conversation).where(Conversation.id.like(f"{prefix}%")))


def test_same_location_is_reused_and_discord_defaults_are_set(discord_database):
    factory, prefix = discord_database
    service = DiscordSessionService(factory)
    first = service.resolve(prefix, "channel")
    second = service.resolve(prefix, "channel")

    assert first.created is True
    assert second.created is False
    assert second.session_id == first.session_id
    assert second.backend_conversation_id == first.backend_conversation_id
    with factory() as database:
        row = database.get(DiscordConversationSession, first.session_id)
        assert row is not None
        assert row.origin == "discord"
        assert row.visibility == "internal"
        assert row.status == "active"
        assert row.thread_id is None


def test_canonical_location_boundaries(discord_database):
    factory, prefix = discord_database
    service = DiscordSessionService(factory)
    channel = service.resolve(prefix, "parent")
    other_channel = service.resolve(prefix, "other")
    other_guild = service.resolve(f"{prefix}-other", "parent")
    thread = service.resolve(prefix, "parent", "thread-1")
    other_thread = service.resolve(prefix, "parent", "thread-2")
    forum_post = service.resolve(prefix, "forum-parent", "forum-post")
    forum_post_again = service.resolve(prefix, "forum-parent", "forum-post")
    private_thread = service.resolve(prefix, "private-parent", "private-thread")

    assert len({
        channel.session_id,
        other_channel.session_id,
        other_guild.session_id,
        thread.session_id,
        other_thread.session_id,
        forum_post.session_id,
        private_thread.session_id,
    }) == 7
    assert forum_post_again.session_id == forum_post.session_id
    assert thread.session_id != channel.session_id
    assert thread.session_id != other_thread.session_id


def test_dm_is_explicitly_unsupported(discord_database):
    factory, _ = discord_database
    with pytest.raises(DiscordDirectMessageUnsupportedError):
        DiscordSessionService(factory).resolve(None, "dm-channel")


def test_missing_backend_conversation_orphans_and_replaces_session(discord_database):
    factory, prefix = discord_database
    service = DiscordSessionService(factory)
    original = service.resolve(prefix, "channel")
    with factory.begin() as database:
        database.execute(
            delete(Conversation).where(Conversation.id == str(original.backend_conversation_id))
        )

    replacement = service.resolve(prefix, "channel")
    assert replacement.created is True
    assert replacement.session_id != original.session_id
    assert replacement.backend_conversation_id != original.backend_conversation_id
    with factory() as database:
        old = database.get(DiscordConversationSession, original.session_id)
        assert old is not None
        assert old.status == "orphaned"
        assert old.orphaned_at is not None
        assert database.get(Conversation, str(replacement.backend_conversation_id)) is not None
        active_count = database.scalar(
            select(func.count()).select_from(DiscordConversationSession).where(
                DiscordConversationSession.guild_id == prefix,
                DiscordConversationSession.channel_id == "channel",
                DiscordConversationSession.thread_id.is_(None),
                DiscordConversationSession.status == "active",
            )
        )
        assert active_count == 1


@pytest.mark.parametrize("thread_id", [None, "thread"])
def test_partial_unique_indexes_reject_duplicate_active_sessions(discord_database, thread_id):
    factory, prefix = discord_database
    service = DiscordSessionService(factory)
    service.resolve(prefix, "channel", thread_id)
    with pytest.raises(IntegrityError):
        with factory.begin() as database:
            repository = DiscordSessionRepository(database)
            conversation_id = repository.create_backend_conversation()
            repository.create_session(prefix, "channel", thread_id, conversation_id)
            database.flush()


@pytest.mark.parametrize(
    ("field", "value"),
    [("origin", "web_ui"), ("visibility", "public"), ("status", "unknown")],
)
def test_session_check_constraints_reject_invalid_values(discord_database, field, value):
    factory, prefix = discord_database
    values = {
        "guild_id": prefix,
        "channel_id": f"invalid-{field}",
        "thread_id": None,
        "backend_conversation_id": uuid4(),
        "origin": "discord",
        "visibility": "internal",
        "status": "active",
    }
    values[field] = value
    with pytest.raises(IntegrityError):
        with factory.begin() as database:
            database.add(DiscordConversationSession(**values))
            database.flush()


def test_concurrent_resolve_creates_one_session_and_conversation(discord_database):
    factory, prefix = discord_database
    service = DiscordSessionService(factory)
    worker_count = 8
    barrier = threading.Barrier(worker_count)

    def resolve():
        barrier.wait(timeout=10)
        return service.resolve(prefix, "shared-channel")

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        results = list(pool.map(lambda _: resolve(), range(worker_count)))

    assert len({result.session_id for result in results}) == 1
    assert len({result.backend_conversation_id for result in results}) == 1
    assert sum(result.created for result in results) == 1
    with factory() as database:
        sessions = list(
            database.scalars(
                select(DiscordConversationSession).where(
                    DiscordConversationSession.guild_id == prefix,
                    DiscordConversationSession.channel_id == "shared-channel",
                    DiscordConversationSession.status == "active",
                )
            )
        )
        assert len(sessions) == 1
        assert database.scalar(
            select(func.count()).select_from(Conversation).where(
                Conversation.id == str(sessions[0].backend_conversation_id)
            )
        ) == 1


def test_web_ui_list_excludes_discord_conversation_and_keeps_web_conversation(discord_database):
    factory, prefix = discord_database
    discord = DiscordSessionService(factory).resolve(prefix, "channel")
    web_id = f"{prefix}-web"
    with factory.begin() as database:
        database.add(Conversation(id=web_id))

    listed = PostgresAuxiliaryStore(factory).list_conversations()
    listed_ids = {row["id"] for row in listed}
    assert str(discord.backend_conversation_id) not in listed_ids
    assert web_id in listed_ids


def test_fifo_sequence_is_per_session_and_message_enqueue_is_idempotent(discord_database):
    factory, prefix = discord_database
    service = DiscordSessionService(factory)
    first_session = service.resolve(prefix, "first")
    second_session = service.resolve(prefix, "second")
    with factory.begin() as database:
        repository = DiscordSessionRepository(database)
        metadata = {
            "author_id": "author-1",
            "author_display_name": "Author One",
        }
        first, created_first = repository.enqueue_turn(
            first_session.session_id, "message-1", "first", **metadata
        )
        second, created_second = repository.enqueue_turn(
            first_session.session_id, "message-2", "second", **metadata
        )
        other, created_other = repository.enqueue_turn(
            second_session.session_id, "message-3", "other", **metadata
        )
        duplicate, created_duplicate = repository.enqueue_turn(
            first_session.session_id, "message-1", "first", **metadata
        )
        assert (first.sequence_number, second.sequence_number, other.sequence_number) == (1, 2, 1)
        assert created_first and created_second and created_other
        assert not created_duplicate
        assert duplicate.id == first.id


def test_fifo_constraints_reject_duplicate_sequence_invalid_status_and_two_running(discord_database):
    factory, prefix = discord_database
    resolution = DiscordSessionService(factory).resolve(prefix, "channel")
    with factory.begin() as database:
        repository = DiscordSessionRepository(database)
        first, _ = repository.enqueue_turn(
            resolution.session_id,
            "message-1",
            "first",
            author_id="author-1",
            author_display_name="Author One",
        )
        second, _ = repository.enqueue_turn(
            resolution.session_id,
            "message-2",
            "second",
            author_id="author-2",
            author_display_name="Author Two",
        )
        first_id, second_id = first.id, second.id

    with pytest.raises(IntegrityError):
        with factory.begin() as database:
            database.add(
                DiscordSessionTurn(
                    session_id=resolution.session_id,
                    discord_message_id="duplicate-sequence",
                    sequence_number=1,
                    request_text="duplicate",
                )
            )
            database.flush()

    with pytest.raises(IntegrityError):
        with factory.begin() as database:
            database.add(
                DiscordSessionTurn(
                    session_id=resolution.session_id,
                    discord_message_id="invalid-status",
                    sequence_number=3,
                    request_text="invalid",
                    status="invalid",
                )
            )
            database.flush()

    with pytest.raises(IntegrityError):
        with factory.begin() as database:
            database.get(DiscordSessionTurn, first_id).status = "running"
            database.get(DiscordSessionTurn, second_id).status = "running"
            database.flush()
