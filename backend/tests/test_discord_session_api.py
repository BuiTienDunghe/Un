from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import (
    Conversation,
    DiscordConversationSession,
    DiscordSessionTurn,
)


URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set POSTGRES_TEST_URL")


@pytest.fixture
def discord_api_cleanup():
    factory = create_session_factory(create_postgres_engine(str(URL)))
    prefix = f"sprint1-api-{uuid4().hex}"
    yield prefix
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


def test_resolve_api_is_idempotent_and_uses_canonical_key(client, discord_api_cleanup):
    prefix = discord_api_cleanup
    payload = {"guild_id": prefix, "channel_id": "parent", "thread_id": "thread"}
    first = client.post("/api/discord/sessions/resolve", json=payload)
    second = client.post("/api/discord/sessions/resolve", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["created"] is True
    assert second.json()["created"] is False
    assert first.json()["session_id"] == second.json()["session_id"]
    assert first.json()["backend_conversation_id"] == second.json()["backend_conversation_id"]
    assert first.json()["status"] == "active"


def test_resolve_api_rejects_dm_empty_ids_and_user_id(client, discord_api_cleanup):
    prefix = discord_api_cleanup
    dm = client.post(
        "/api/discord/sessions/resolve",
        json={"guild_id": None, "channel_id": "dm", "thread_id": None},
    )
    empty = client.post(
        "/api/discord/sessions/resolve",
        json={"guild_id": prefix, "channel_id": " ", "thread_id": None},
    )
    empty_guild = client.post(
        "/api/discord/sessions/resolve",
        json={"guild_id": " ", "channel_id": "channel", "thread_id": None},
    )
    user_key = client.post(
        "/api/discord/sessions/resolve",
        json={"guild_id": prefix, "channel_id": "channel", "thread_id": None, "user_id": "123"},
    )

    assert dm.status_code == 422
    assert dm.json()["error_code"] == "INVALID_INPUT"
    assert empty.status_code == 422
    assert empty_guild.status_code == 422
    assert user_key.status_code == 422


def test_openapi_requires_non_nullable_bounded_guild_id(client):
    schema = client.get("/openapi.json").json()["components"]["schemas"]["DiscordSessionResolveRequest"]
    guild = schema["properties"]["guild_id"]

    assert "guild_id" in schema["required"]
    assert guild["type"] == "string"
    assert guild["minLength"] == 1
    assert guild["maxLength"] == 64
    assert "anyOf" not in guild


def test_discord_session_is_hidden_from_web_ui_conversation_api(client, discord_api_cleanup):
    prefix = discord_api_cleanup
    resolved = client.post(
        "/api/discord/sessions/resolve",
        json={"guild_id": prefix, "channel_id": "channel", "thread_id": None},
    )
    backend_conversation_id = resolved.json()["backend_conversation_id"]

    listing = client.get("/conversations")
    assert listing.status_code == 200
    assert backend_conversation_id not in {row["id"] for row in listing.json()}


def test_turn_enqueue_is_idempotent_and_server_owns_sequence_and_status(
    client,
    discord_api_cleanup,
):
    prefix = discord_api_cleanup
    session_id = client.post(
        "/api/discord/sessions/resolve",
        json={"guild_id": prefix, "channel_id": "channel", "thread_id": None},
    ).json()["session_id"]
    path = f"/api/discord/sessions/{session_id}/turns"
    payload = {
        "discord_message_id": "message-1",
        "message": "Hello",
        "author_id": "author-1",
        "author_display_name": "Dũng",
        "reply_to_discord_message_id": "message-parent",
    }

    first = client.post(path, json=payload)
    duplicate = client.post(
        path,
        json={
            **payload,
            "author_id": "conflicting-retry-author",
            "author_display_name": "Conflicting Retry",
        },
    )
    client_owned = client.post(path, json={**payload, "sequence_number": 99, "status": "running"})

    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert first.json()["created"] is True
    assert duplicate.json()["created"] is False
    assert first.json()["turn_id"] == duplicate.json()["turn_id"]
    assert first.json()["sequence_number"] == 1
    assert first.json()["status"] == "queued"
    assert client_owned.status_code == 422

    factory = create_session_factory(create_postgres_engine(str(URL)))
    with factory() as database:
        row = database.get(DiscordSessionTurn, first.json()["turn_id"])
        assert row is not None
        # Idempotency is first-write-wins; a retry cannot rewrite attribution.
        assert row.author_id == "author-1"
        assert row.author_display_name == "Dũng"
        assert row.reply_to_discord_message_id == "message-parent"


def test_turn_enqueue_requires_trusted_author_metadata(
    client,
    discord_api_cleanup,
):
    prefix = discord_api_cleanup
    session_id = client.post(
        "/api/discord/sessions/resolve",
        json={"guild_id": prefix, "channel_id": "channel", "thread_id": None},
    ).json()["session_id"]
    response = client.post(
        f"/api/discord/sessions/{session_id}/turns",
        json={"discord_message_id": "message-no-author", "message": "Hello"},
    )
    assert response.status_code == 422

    schema = client.get("/openapi.json").json()["components"]["schemas"][
        "DiscordTurnEnqueueRequest"
    ]
    assert {"author_id", "author_display_name"}.issubset(schema["required"])


def test_turn_execute_waits_for_delivery_ack_before_completion(
    client,
    mock_ollama,
    discord_api_cleanup,
):
    prefix = discord_api_cleanup
    session_id = client.post(
        "/api/discord/sessions/resolve",
        json={"guild_id": prefix, "channel_id": "channel", "thread_id": None},
    ).json()["session_id"]
    turn_id = client.post(
        f"/api/discord/sessions/{session_id}/turns",
        json={
            "discord_message_id": "message-execute",
            "message": "Hello",
            "author_id": "author-execute",
            "author_display_name": "Executor",
            "system_prompt": "Discord prompt",
        },
    ).json()["turn_id"]

    execution = client.post(f"/api/discord/sessions/turns/{turn_id}/execute")
    assert execution.status_code == 200
    assert execution.json()["status"] == "running"
    assert execution.json()["answer"]
    token = execution.json()["execution_token"]
    assert token

    completed = client.post(
        f"/api/discord/sessions/turns/{turn_id}/complete",
        json={
            "execution_token": token,
            "discord_response_message_ids": ["discord-response-execute"],
        },
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    idempotent_retry = client.post(
        f"/api/discord/sessions/turns/{turn_id}/complete",
        json={
            "execution_token": token,
            "discord_response_message_ids": ["discord-response-execute"],
        },
    )
    assert idempotent_retry.status_code == 200
    assert idempotent_retry.json()["status"] == "completed"
    conflict = client.post(
        f"/api/discord/sessions/turns/{turn_id}/complete",
        json={
            "execution_token": token,
            "discord_response_message_ids": ["discord-response-different"],
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "DISCORD_TURN_DELIVERY_CONFLICT"


def test_operator_stop_api_terminally_cancels_open_turns(
    client,
    discord_api_cleanup,
):
    prefix = discord_api_cleanup
    session_id = client.post(
        "/api/discord/sessions/resolve",
        json={"guild_id": prefix, "channel_id": "operator-stop", "thread_id": None},
    ).json()["session_id"]
    path = f"/api/discord/sessions/{session_id}/turns"
    first = client.post(
        path,
        json={
            "discord_message_id": "operator-stop-1",
            "message": "one",
            "author_id": "author-1",
            "author_display_name": "Operator",
        },
    ).json()["turn_id"]
    second = client.post(
        path,
        json={
            "discord_message_id": "operator-stop-2",
            "message": "two",
            "author_id": "author-1",
            "author_display_name": "Operator",
        },
    ).json()["turn_id"]

    response = client.post("/api/discord/sessions/turns/cancel-open", json={})

    assert response.status_code == 200
    assert response.json() == {"cancelled_turns": 2}
    factory = create_session_factory(create_postgres_engine(str(URL)))
    with factory() as database:
        assert database.get(DiscordSessionTurn, first).status == "cancelled"
        assert database.get(DiscordSessionTurn, second).status == "cancelled"
