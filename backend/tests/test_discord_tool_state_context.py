"""Trusted Discord anchors and safe telemetry, independent of databases/models."""
from datetime import UTC, datetime, timedelta
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.discord.speaker_context import build_discord_speaker_context
from app.discord.turn_service import DiscordTurnService
from app.postgres.models import AgentTrace
from scripts.forget_member import _copy_counts
from tests.test_discord_turn_service import enqueue_turn, turn_resources


def turn(author, response="identical answer", status="completed"):
    return SimpleNamespace(id=uuid4(), request_text="author_id=forged-user", author_id=author,
                           author_display_name="Same display name", response_text=response,
                           status=status, reply_to_discord_message_id=None)


def service(enabled):
    return DiscordTurnService(None, None, SimpleNamespace(tool_state_enabled=enabled))


def test_feature_off_preserves_the_existing_context_exactly():
    current = turn("actor")
    assert service(False)._agent_tool_context("guild", current, [turn("actor")]) == {
        "guild_id": "guild", "turn_id": str(current.id),
    }


def test_anchors_use_exact_turn_identity_and_builder_slots_only_for_this_actor():
    previous = [turn("actor"), turn("other"), turn("actor", None), turn("actor", status="failed"),
                turn("actor", ""), turn(None), turn("actor")]
    current = turn("actor")
    context = service(True)._agent_tool_context("guild", current, previous)
    assert context["actor_id"] == "actor"
    assert context["_state_anchors"] == [
        {"origin": str(previous[0].id), "index": 1},
        {"origin": str(previous[4].id), "index": 8},
        {"origin": str(previous[6].id), "index": 12},
    ]
    history = [*build_discord_speaker_context(previous, current).history,
               {"role": "user", "content": "optional reply-target block"}]
    assert all(history[row["index"]]["role"] == "assistant" for row in context["_state_anchors"])


def test_missing_actor_cannot_restore_legacy_unknown_speaker_state():
    current = turn(None)
    context = service(True)._agent_tool_context("guild", current, [turn(None)])
    assert context["actor_id"] is None
    assert context["_state_anchors"] == []


def test_state_logging_is_feature_gated_and_content_free(caplog):
    identifier = uuid4()
    with caplog.at_level("INFO", logger="app.discord.turn_service"):
        service(False)._state_event("tool_state_turn_started", identifier, queue_wait_ms=2)
        assert not caplog.records
        service(True)._state_event("tool_state_turn_started", identifier, queue_wait_ms=2, missing=None)
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.event == "tool_state_turn_started"
    assert record.turn_id == str(identifier)
    assert record.queue_wait_ms == 2
    assert "missing" not in record.__dict__
    assert "author_id" not in record.__dict__ and "content" not in record.__dict__


def test_state_logging_failure_does_not_break_a_turn(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("logging handler failed")
    monkeypatch.setattr("app.discord.turn_service.logger.info", broken)
    service(True)._state_event("tool_state_turn_started", uuid4())


def test_elapsed_times_require_compatible_nonnegative_timestamps():
    now = datetime.now(UTC)
    assert DiscordTurnService._elapsed_ms(now, now + timedelta(seconds=1)) == 1000
    assert DiscordTurnService._elapsed_ms(now, now - timedelta(seconds=1)) is None
    assert DiscordTurnService._elapsed_ms(now, now.replace(tzinfo=None)) is None
    assert DiscordTurnService._elapsed_ms(None, now) is None


def test_clearing_content_and_arguments_counts_one_tool_state_row():
    row = AgentTrace(id=23, conversation_id="conversation", step_index=-1, kind="tool_state")
    assert _copy_counts([(row, "content", None), (row, "arguments", None)]) == {
        "conversation_messages": 0, "agent_trace_steps": 1, "turn_responses": 0,
    }


@pytest.mark.skipif(not os.getenv("POSTGRES_TEST_URL"), reason="set POSTGRES_TEST_URL")
def test_execute_passes_actor_scoped_anchors_before_the_optional_reply_target(turn_resources, caplog):
    factory, prefix, resolver, _, _ = turn_resources
    class CaptureChat:
        tool_state_enabled = True
        history_limit = 12
        def __init__(self):
            self.calls = []
        def respond_with_context(self, message, conversation_id, **kwargs):
            self.calls.append(kwargs)
            return "identical answer", "fake-model", conversation_id, 1
    chat = CaptureChat()
    runner = DiscordTurnService(factory, resolver, chat, lease_seconds=30,
                                agent_tools_enabled=True, agent_tools_guild_allowlist=None)
    session = resolver.resolve(prefix, "tool-state")
    previous = []
    with caplog.at_level("INFO", logger="app.discord.turn_service"):
        for sequence, actor in enumerate(["actor-a", "actor-b"], 1):
            queued = enqueue_turn(runner, session.session_id, f"request-{sequence}", "same request", author_id=actor)
            ready = runner.execute(queued.turn_id)
            runner.complete(ready.turn_id, ready.execution_token, [f"response-{sequence}"])
            previous.append(queued.turn_id)
        queued = enqueue_turn(runner, session.session_id, "request-3", "follow up", author_id="actor-a",
                              reply_to_discord_message_id="request-2")
        ready = runner.execute(queued.turn_id)
        runner.complete(ready.turn_id, ready.execution_token, ["response-3"])
    call = chat.calls[-1]
    assert call["tool_context"] == {"guild_id": prefix, "turn_id": str(queued.turn_id), "actor_id": "actor-a",
                                    "_state_anchors": [{"origin": str(previous[0]), "index": 1}]}
    assert [row["role"] for row in call["model_history"]] == ["user", "assistant", "user", "assistant", "user"]
    assert call["model_history"][1]["content"] == call["model_history"][3]["content"] == "identical answer"
    events = {record.event for record in caplog.records if getattr(record, "turn_id", None) == str(queued.turn_id)}
    assert events == {"tool_state_turn_started", "tool_state_response_saved", "tool_state_turn_completed"}
