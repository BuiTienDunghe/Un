"""Job 1+2 (memory_design.md §5, §13.5-6): raw ledger writes + guild-scoped
verbatim history search over Postgres FTS ('simple' config on
tokenize_vietnamese output — incremental, no rebuild-on-read cliff).
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import DiscordChannelMessage, DiscordChannelPolicy
from app.services.discord_history_service import (
    DiscordHistoryService,
    snowflake_to_datetime,
)

URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")

_DISCORD_EPOCH_MS = 1_420_070_400_000


def _snowflake(at: datetime, sequence: int = 0) -> str:
    return str(((int(at.timestamp() * 1000) - _DISCORD_EPOCH_MS) << 22) + sequence)


@pytest.fixture
def history_world():
    factory = create_session_factory(create_postgres_engine(str(URL)))
    prefix = f"hist-{uuid4().hex}"
    service = DiscordHistoryService(factory)
    yield factory, prefix, service
    with factory.begin() as database:
        database.execute(
            delete(DiscordChannelMessage).where(
                DiscordChannelMessage.guild_id.like(f"{prefix}%")
            )
        )
        database.execute(
            delete(DiscordChannelPolicy).where(
                DiscordChannelPolicy.guild_id.like(f"{prefix}%")
            )
        )


def _record(service, prefix, content, *, sequence, guild="g1", author="u1",
            is_bot=False, at=None):
    at = at or datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    message_id = _snowflake(at, sequence)
    assert service.record_message(
        guild_id=f"{prefix}-{guild}",
        channel_id="chan-1",
        thread_id=None,
        discord_message_id=message_id,
        author_id=author,
        author_display_name=f"User {author}",
        is_bot=is_bot,
        content=content,
    )
    return message_id


def test_question_query_finds_short_verbatim_message(history_world):
    _, prefix, service = history_world
    _record(service, prefix, "chốt dùng Postgres nhé", sequence=1, author="u2")
    _record(service, prefix, "hôm nay trời đẹp quá", sequence=2)

    hits = service.search(
        guild_id=f"{prefix}-g1",
        query="tôi nói 'chốt dùng Postgres' khi nào",
        limit=5,
    )
    assert hits
    assert hits[0].content == "chốt dùng Postgres nhé"
    assert hits[0].author_id == "u2"
    assert hits[0].link.startswith("https://discord.com/channels/")


def test_one_changed_word_misquote_still_ranks_the_target(history_world):
    _, prefix, service = history_world
    _record(service, prefix, "chốt dùng Postgres nhé", sequence=1)
    hits = service.search(
        guild_id=f"{prefix}-g1",
        query="tôi nói 'chốt xài Postgres' khi nào",
        limit=5,
    )
    assert hits and "chốt dùng Postgres" in hits[0].content


def test_search_never_crosses_the_guild_boundary(history_world):
    _, prefix, service = history_world
    _record(service, prefix, "mật khẩu wifi là bí mật", sequence=1, guild="g1")
    hits = service.search(
        guild_id=f"{prefix}-g2", query="mật khẩu wifi", limit=5
    )
    assert hits == []


def test_edit_keeps_first_version_once_and_search_sees_latest(history_world):
    factory, prefix, service = history_world
    message_id = _record(service, prefix, "mai họp lúc 3 giờ", sequence=1)

    assert service.record_edit(discord_message_id=message_id, content="mai họp lúc 4 giờ")
    assert service.record_edit(discord_message_id=message_id, content="mai họp lúc 5 giờ")
    with factory() as database:
        row = database.scalar(
            select(DiscordChannelMessage).where(
                DiscordChannelMessage.discord_message_id == message_id
            )
        )
        # §5.3: content_original is the FIRST version, set exactly once.
        assert row.content_original == "mai họp lúc 3 giờ"
        assert row.content == "mai họp lúc 5 giờ"
        assert row.edited_at is not None

    hits = service.search(guild_id=f"{prefix}-g1", query="họp lúc 5 giờ", limit=5)
    assert hits and hits[0].content == "mai họp lúc 5 giờ"


def test_delete_clears_texts_and_leaves_search(history_world):
    factory, prefix, service = history_world
    message_id = _record(service, prefix, "tin nhắn sắp bị xóa", sequence=1)
    assert service.record_delete(discord_message_id=message_id)

    with factory() as database:
        row = database.scalar(
            select(DiscordChannelMessage).where(
                DiscordChannelMessage.discord_message_id == message_id
            )
        )
        # §9.5: texts cleared at event time, skeleton kept for audit.
        assert row.content is None
        assert row.content_original is None
        assert row.deleted_at is not None

    assert service.search(guild_id=f"{prefix}-g1", query="tin nhắn sắp bị xóa") == []


def test_duplicate_delivery_is_idempotent(history_world):
    _, prefix, service = history_world
    at = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    message_id = _snowflake(at, 7)
    kwargs = dict(
        guild_id=f"{prefix}-g1",
        channel_id="chan-1",
        thread_id=None,
        discord_message_id=message_id,
        author_id="u1",
        author_display_name="User u1",
        is_bot=False,
        content="một lần thôi nhé",
    )
    assert service.record_message(**kwargs) is True
    assert service.record_message(**kwargs) is False


def test_policy_row_is_created_once_for_audit(history_world):
    factory, prefix, service = history_world
    _record(service, prefix, "tin một", sequence=1)
    _record(service, prefix, "tin hai", sequence=2)
    with factory() as database:
        rows = list(
            database.scalars(
                select(DiscordChannelPolicy).where(
                    DiscordChannelPolicy.guild_id == f"{prefix}-g1"
                )
            )
        )
    assert len(rows) == 1
    assert rows[0].listening_enabled is True
    assert rows[0].enabled_by == "env"


def test_sent_at_derives_from_snowflake_and_days_filter_uses_it(history_world):
    _, prefix, service = history_world
    old = datetime.now(UTC) - timedelta(days=30)
    recent = datetime.now(UTC) - timedelta(days=1)
    _record(service, prefix, "chuyện cũ về dự án", sequence=1, at=old)
    _record(service, prefix, "chuyện mới về dự án", sequence=2, at=recent)

    assert snowflake_to_datetime(_snowflake(old, 1)) - old < timedelta(seconds=1)
    hits = service.search(
        guild_id=f"{prefix}-g1", query="chuyện về dự án", days=7, limit=5
    )
    assert [hit.content for hit in hits] == ["chuyện mới về dự án"]


def test_bot_rows_are_stored_tagged_and_author_filter_works(history_world):
    _, prefix, service = history_world
    _record(service, prefix, "Ún trả lời về ngày sinh", sequence=1,
            author="bot-1", is_bot=True)
    _record(service, prefix, "người thật nói về ngày sinh", sequence=2,
            author="u1")

    hits = service.search(guild_id=f"{prefix}-g1", query="ngày sinh", limit=5)
    assert {hit.is_bot for hit in hits} == {True, False}

    only_human = service.search(
        guild_id=f"{prefix}-g1", query="ngày sinh", author_id="u1", limit=5
    )
    assert [hit.author_id for hit in only_human] == ["u1"]


def test_delete_before_insert_leaves_tombstone_and_blocks_the_late_insert(history_world):
    factory, prefix, service = history_world
    at = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
    message_id = _snowflake(at, 11)
    guild = f"{prefix}-g1"

    assert service.record_delete(
        discord_message_id=message_id, guild_id=guild, channel_id="chan-1"
    ) is True
    # The racing insert must die on the unique message id.
    assert service.record_message(
        guild_id=guild,
        channel_id="chan-1",
        thread_id=None,
        discord_message_id=message_id,
        author_id="u1",
        author_display_name="User u1",
        is_bot=False,
        content="noi dung da xoa truoc khi ghi",
    ) is False
    with factory() as database:
        row = database.scalar(
            select(DiscordChannelMessage).where(
                DiscordChannelMessage.discord_message_id == message_id
            )
        )
        assert row.deleted_at is not None
        assert row.content is None


def test_malformed_message_id_returns_recorded_false(history_world):
    _, prefix, service = history_world
    assert service.record_message(
        guild_id=f"{prefix}-g1",
        channel_id="chan-1",
        thread_id=None,
        discord_message_id="khong-phai-snowflake",
        author_id="u1",
        author_display_name="User u1",
        is_bot=False,
        content="tin nhan loi id",
    ) is False


def test_policy_kill_switch_stops_recording(history_world):
    factory, prefix, service = history_world
    _record(service, prefix, "tin truoc khi tat", sequence=21)
    with factory.begin() as database:
        row = database.scalar(
            select(DiscordChannelPolicy).where(
                DiscordChannelPolicy.guild_id == f"{prefix}-g1"
            )
        )
        row.listening_enabled = False

    at = datetime(2026, 8, 22, 9, 0, tzinfo=UTC)
    assert service.record_message(
        guild_id=f"{prefix}-g1",
        channel_id="chan-1",
        thread_id=None,
        discord_message_id=_snowflake(at, 22),
        author_id="u1",
        author_display_name="User u1",
        is_bot=False,
        content="tin sau khi tat",
    ) is False
    hits = service.search(guild_id=f"{prefix}-g1", query="tin sau khi tat")
    # OR-ranking may surface the pre-switch-off message (shared lexemes);
    # what must NOT exist is the post-switch-off content itself.
    assert all(hit.content != "tin sau khi tat" for hit in hits)


def test_recent_returns_latest_messages_in_chronological_order(history_world):
    _, prefix, service = history_world
    base = datetime(2026, 8, 25, 10, 0, tzinfo=UTC)
    for offset, content in enumerate(
        ["tin thu nhat", "tin thu hai", "tin thu ba", "tin thu tu"]
    ):
        _record(service, prefix, content, sequence=offset + 30,
                at=base + timedelta(minutes=offset))
    deleted_id = _record(service, prefix, "tin bi xoa", sequence=40,
                         at=base + timedelta(minutes=10))
    assert service.record_delete(discord_message_id=deleted_id)

    hits = service.recent(guild_id=f"{prefix}-g1", limit=3)
    # The 3 newest surviving messages, oldest-first for natural reading;
    # the deleted one never appears.
    assert [hit.content for hit in hits] == [
        "tin thu hai", "tin thu ba", "tin thu tu"
    ]

    assert service.recent(guild_id=f"{prefix}-khac", limit=5) == []
