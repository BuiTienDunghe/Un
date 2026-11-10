"""Review2 code F: three clocks compared against one barrier.

Turn and web-message times come from the application's clock, Discord message times from
the snowflake, and every barrier from Postgres. Here only the application's clock (or the
snowflake) runs 30 s off; the forget is a real call, so the barrier keeps Postgres time.
F-0 is the same story with no skew, so the skewed cases can fail only because of the skew.
"""
from __future__ import annotations

import time

import pytest

from review2_support import (KnownBug, app_clock, enqueue, execute, finished_turn, known_bug, ledger_message,  # noqa: F401
                             r2, snowflake, v2client)

FORGET = "Hãy quên toàn bộ trí nhớ về tôi"
SKEW = 30
TRADE_OFF = ("; trade-off of the obvious fix: comparing by arrival time instead lets a message sent "
             "before the barrier but delivered after it slip through")
F_FAST = "review2 F: an app clock running ahead stamps words said before a forget as newer than the barrier" + TRADE_OFF
F_SLOW = "review2 F: an app clock running behind stamps a message sent after a forget as older than the barrier"
F_SNOWFLAKE = "review2 F: search_history compares Discord's clock with the Postgres barrier" + TRADE_OFF


def say_forget_ask(r2) -> bool:  # noqa: F811
    """Say a code, forget everything, ask for the code: True when the code stayed out."""
    client, guild = r2.client, r2.guild
    finished_turn(client, guild, "one", "Mật mã của tôi là sentinel-f1.")
    finished_turn(client, guild, "one", FORGET)
    time.sleep(0.05)
    calls = len(r2.model.calls)
    _, turn_id = enqueue(client, guild, "one", "Mật mã của tôi là gì?")
    response = execute(client, turn_id)
    assert response.status_code == 200, response.text
    assert len(r2.model.calls) == calls + 1, "the question never reached the model"
    return "sentinel-f1" not in r2.model.prompts_since(calls)


def forget_then_ask(r2) -> bool:  # noqa: F811
    """Forget everything, then send a new message: True when it is answered as usual."""
    from app.discord.source_memory import STALE_TURN_REPLY
    client, guild = r2.client, r2.guild
    finished_turn(client, guild, "one", FORGET)
    time.sleep(0.05)
    calls = len(r2.model.calls)
    _, turn_id = enqueue(client, guild, "one", "Hôm nay mình hỏi câu mới nhé.")
    response = execute(client, turn_id)
    assert response.status_code == 200, response.text
    return response.json()["answer"] != STALE_TURN_REPLY and len(r2.model.calls) == calls + 1


@pytest.mark.parametrize("story", ["say_forget_ask", "forget_then_ask"])
def test_f0_with_true_clocks_both_stories_behave(r2, story):  # noqa: F811
    assert {"say_forget_ask": say_forget_ask, "forget_then_ask": forget_then_ask}[story](r2)


@pytest.mark.xfail(strict=True, raises=KnownBug, reason=F_FAST)
def test_f1_discord_with_the_app_clock_30s_fast_forgotten_words_stay_out(r2, monkeypatch):  # noqa: F811
    app_clock(monkeypatch, +SKEW)
    known_bug(say_forget_ask(r2), "the code said before the forget reached the model again")


@pytest.mark.xfail(strict=True, raises=KnownBug, reason=F_SLOW)
def test_f2_discord_with_the_app_clock_30s_slow_a_message_after_a_forget_is_answered(r2, monkeypatch):  # noqa: F811
    app_clock(monkeypatch, -SKEW)
    known_bug(forget_then_ask(r2), "a message sent after the forget was called stale")


def search_history(r2) -> str:  # noqa: F811
    from app.services.source_memory import MemoryReader
    service = r2.client.app.state.agent_service
    tool = service.registry.get("search_history").run
    context = {"_memory_reader": MemoryReader.discord(r2.guild, "one", None, "alice"),
               "guild_id": r2.guild, "channel_id": "one", "thread_id": None}
    found, _, _ = tool(service, {}, context)
    return found


@pytest.mark.parametrize("case", ["fast_snowflake_written_before_the_forget", "slow_snowflake_written_after_the_forget"])
@pytest.mark.xfail(strict=True, raises=KnownBug, reason=F_SNOWFLAKE)
def test_f3_search_history_with_discord_30s_off(r2, case):  # noqa: F811
    from datetime import UTC, datetime, timedelta
    client, guild = r2.client, r2.guild
    if case == "fast_snowflake_written_before_the_forget":
        ledger_message(client, guild, "one", "alice", "Mật mã của tôi là sentinel-f3.",
                       message_id=snowflake(datetime.now(UTC) + timedelta(seconds=SKEW)))
        assert "sentinel-f3" in search_history(r2), "search_history never finds the message"
        time.sleep(0.05)
        r2.memory.forget_actor(f"discord:{guild}", "alice")
        known_bug("sentinel-f3" not in search_history(r2), "a message written before the forget came back")
    else:
        r2.memory.forget_actor(f"discord:{guild}", "alice")
        time.sleep(0.05)
        ledger_message(client, guild, "one", "alice", "Mật mã của tôi là sentinel-f3.",
                       message_id=snowflake(datetime.now(UTC) - timedelta(seconds=SKEW)))
        known_bug("sentinel-f3" in search_history(r2), "a message written after the forget is not found")


@pytest.mark.xfail(strict=True, raises=KnownBug, reason=F_FAST)
def test_f4_web_with_the_app_clock_30s_fast_forgotten_words_stay_out(r2, monkeypatch):  # noqa: F811
    client = r2.client
    app_clock(monkeypatch, +SKEW)
    first = client.post("/chat", json={"message": "Mật mã của tôi là sentinel-f4."})
    assert first.status_code == 200, first.text
    conversation = first.json()["conversation_id"]
    assert client.post("/chat", json={"message": FORGET, "conversation_id": conversation}).status_code == 200
    time.sleep(0.05)
    calls = len(r2.model.calls)
    asked = client.post("/chat", json={"message": "Mật mã của tôi là gì?", "conversation_id": conversation})
    assert asked.status_code == 200, asked.text
    assert len(r2.model.calls) == calls + 1
    known_bug("sentinel-f4" not in r2.model.prompts_since(calls), "the code said before the forget reached the model")


@pytest.mark.xfail(strict=True, raises=KnownBug, reason=F_SLOW)
def test_f5_web_with_the_app_clock_30s_slow_what_was_said_after_a_forget_is_kept(r2, monkeypatch):  # noqa: F811
    client = r2.client
    app_clock(monkeypatch, -SKEW)
    forgot = client.post("/chat", json={"message": FORGET})
    assert forgot.status_code == 200, forgot.text
    conversation = forgot.json()["conversation_id"]
    time.sleep(0.05)
    said = client.post("/chat", json={"message": "Câu A của tôi là sentinel-f5.", "conversation_id": conversation})
    assert said.status_code == 200, said.text
    calls = len(r2.model.calls)
    asked = client.post("/chat", json={"message": "Nhắc lại câu A giúp tôi.", "conversation_id": conversation})
    assert asked.status_code == 200, asked.text
    assert len(r2.model.calls) == calls + 1
    known_bug("sentinel-f5" in r2.model.prompts_since(calls), "what was said after the forget is missing from the history")
