from __future__ import annotations

import os

import pytest
from sqlalchemy import inspect

from app.postgres.database import create_postgres_engine


URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")


def test_discord_session_schema_and_constraints_exist():
    inspector = inspect(create_postgres_engine(str(URL)))
    tables = set(inspector.get_table_names())
    assert {
        "discord_conversation_sessions",
        "discord_session_turns",
        "discord_turn_deliveries",
    }.issubset(tables)

    session_columns = {column["name"]: column for column in inspector.get_columns("discord_conversation_sessions")}
    assert set(session_columns) == {
        "id", "guild_id", "channel_id", "thread_id", "backend_conversation_id",
        "origin", "visibility", "status", "started_at", "last_active_at",
        "closed_at", "orphaned_at", "created_at", "updated_at",
    }
    assert not session_columns["id"]["nullable"]
    assert not session_columns["backend_conversation_id"]["nullable"]
    assert session_columns["id"]["type"].__class__.__name__ == "UUID"
    assert session_columns["backend_conversation_id"]["type"].__class__.__name__ == "UUID"
    assert session_columns["thread_id"]["nullable"]
    for name in ("started_at", "last_active_at", "closed_at", "orphaned_at", "created_at", "updated_at"):
        assert session_columns[name]["type"].timezone is True

    session_checks = {constraint["name"] for constraint in inspector.get_check_constraints("discord_conversation_sessions")}
    assert {
        "ck_discord_conversation_sessions_status",
        "ck_discord_conversation_sessions_origin",
        "ck_discord_conversation_sessions_visibility",
    }.issubset(session_checks)
    session_indexes = {index["name"]: index for index in inspector.get_indexes("discord_conversation_sessions")}
    assert session_indexes["uq_discord_active_channel_session"]["unique"]
    assert session_indexes["uq_discord_active_thread_session"]["unique"]

    turn_uniques = {constraint["name"] for constraint in inspector.get_unique_constraints("discord_session_turns")}
    turn_columns = {column["name"]: column for column in inspector.get_columns("discord_session_turns")}
    assert {
        "id",
        "session_id",
        "discord_message_id",
        "sequence_number",
        "request_text",
        "author_id",
        "author_display_name",
        "reply_to_discord_message_id",
        "system_prompt",
        "response_text",
        "model_used",
        "status",
        "available_at",
        "started_at",
        "completed_at",
        "error",
        "worker_id",
        "lease_expires_at",
        "heartbeat_at",
        "attempt_count",
        "max_attempts",
        "created_at",
        "updated_at",
    } == set(turn_columns)
    assert not turn_columns["request_text"]["nullable"]
    assert turn_columns["author_id"]["nullable"]
    assert turn_columns["author_display_name"]["nullable"]
    assert turn_columns["reply_to_discord_message_id"]["nullable"]
    assert not turn_columns["attempt_count"]["nullable"]
    assert not turn_columns["max_attempts"]["nullable"]
    for name in (
        "available_at",
        "started_at",
        "completed_at",
        "lease_expires_at",
        "heartbeat_at",
        "created_at",
        "updated_at",
    ):
        assert turn_columns[name]["type"].timezone is True
    assert {"uq_discord_session_turn_message", "uq_discord_session_turn_sequence"}.issubset(turn_uniques)
    turn_checks = {constraint["name"] for constraint in inspector.get_check_constraints("discord_session_turns")}
    assert {
        "ck_discord_session_turns_status",
        "ck_discord_session_turns_positive_sequence",
        "ck_discord_session_turns_attempt_count",
        "ck_discord_session_turns_max_attempts",
    }.issubset(turn_checks)
    turn_indexes = {index["name"]: index for index in inspector.get_indexes("discord_session_turns")}
    assert turn_indexes["uq_discord_session_turn_one_running"]["unique"]
    assert "ix_discord_session_turn_stale_lease" in turn_indexes
    assert any(
        foreign["referred_table"] == "discord_conversation_sessions"
        and foreign["constrained_columns"] == ["session_id"]
        for foreign in inspector.get_foreign_keys("discord_session_turns")
    )

    delivery_columns = {
        column["name"]: column
        for column in inspector.get_columns("discord_turn_deliveries")
    }
    assert set(delivery_columns) == {
        "id",
        "turn_id",
        "discord_message_id",
        "chunk_index",
        "created_at",
    }
    assert all(not column["nullable"] for column in delivery_columns.values())
    assert delivery_columns["created_at"]["type"].timezone is True
    delivery_uniques = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(
            "discord_turn_deliveries"
        )
    }
    assert {
        "uq_discord_turn_delivery_chunk",
        "uq_discord_turn_delivery_message",
    }.issubset(delivery_uniques)
    delivery_checks = {
        constraint["name"]
        for constraint in inspector.get_check_constraints(
            "discord_turn_deliveries"
        )
    }
    assert "ck_discord_turn_deliveries_chunk_index" in delivery_checks
    assert any(
        foreign["referred_table"] == "discord_session_turns"
        and foreign["constrained_columns"] == ["turn_id"]
        and foreign["options"].get("ondelete") == "CASCADE"
        for foreign in inspector.get_foreign_keys("discord_turn_deliveries")
    )
