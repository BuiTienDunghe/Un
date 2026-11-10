"""Review2 code B: edits and deletes in the raw ledger, and what the next turn is shown.

The bot editing or deleting its own message, and an edit that keeps the text, are covered in
test_source_memory_discord.py. A person changing the words of a message still makes Ún
forget the whole channel; that is today's design, so only the part true under every design
is checked here: the old words never come back.
"""
from __future__ import annotations

import pytest

from review2_support import (complete, enqueue, execute, finished_turn, ledger_message, r2,  # noqa: F401
                             v2client)


def test_b1_the_bot_editing_its_progress_message_leaves_a_queued_turn_and_the_history_alone(r2):  # noqa: F811
    from app.discord.source_memory import STALE_TURN_REPLY
    client, guild = r2.client, r2.guild
    finished_turn(client, guild, "one", "Mật mã của tôi là sentinel-b1.")
    _, turn_id = enqueue(client, guild, "one", "Mật mã của tôi là gì?")
    progress = ledger_message(client, guild, "one", "un-bot", "⏳ Ún đang làm…", bot=True)
    edited = client.post(f"/api/discord/history/messages/{progress}/edit", json={"content": "Câu trả lời cuối."})
    assert edited.status_code == 200, edited.text
    calls = len(r2.model.calls)
    executed = execute(client, turn_id)
    assert executed.status_code == 200, executed.text
    assert executed.json()["answer"] != STALE_TURN_REPLY
    assert len(r2.model.calls) == calls + 1
    assert "sentinel-b1" in r2.model.prompts_since(calls)


@pytest.mark.parametrize("change", ["edit", "delete"])
def test_b2_a_person_changing_a_message_in_the_history_keeps_its_old_words_out(r2, change):  # noqa: F811
    client, guild = r2.client, r2.guild
    # The bot ledgers every heard message, the one that asked Ún included.
    message_id = ledger_message(client, guild, "one", "alice", "Mật mã của tôi là sentinel-b2.")
    _, turn_id = enqueue(client, guild, "one", "Mật mã của tôi là sentinel-b2.", message_id=message_id)
    executed = execute(client, turn_id)
    assert executed.status_code == 200 and executed.json()["answer"], executed.text
    complete(client, turn_id, executed.json()["execution_token"])
    if change == "edit":
        changed = client.post(f"/api/discord/history/messages/{message_id}/edit", json={"content": "Mật mã đã đổi."})
    else:
        changed = client.post(f"/api/discord/history/messages/{message_id}/delete",
                              json={"guild_id": guild, "channel_id": "one"})
    assert changed.status_code == 200 and changed.json()["recorded"], changed.text
    calls = len(r2.model.calls)
    _, asking = enqueue(client, guild, "one", "Mật mã của tôi là gì?")
    asked = execute(client, asking)
    assert asked.status_code == 200, asked.text
    assert len(r2.model.calls) == calls + 1
    assert "sentinel-b2" not in r2.model.prompts_since(calls)
