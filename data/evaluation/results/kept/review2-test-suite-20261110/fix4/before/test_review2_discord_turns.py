"""Review2: Discord turns on the backend — replies (R1, N2), replays and resends (R3),
retried "forget"/"remember" turns (N4), and abandoned turns seen from the backend (A).

Each case drives the real app over HTTP (v2client: Postgres, source memory on) and judges
what the model was shown and what the bot was handed back. See review2_support.py for the
xfail convention.
"""
from __future__ import annotations

import re
import time

import pytest

from review2_support import (KnownBug, active_notes, age_open_turns, channel_barrier, edit_unledgered,  # noqa: F401
                             enqueue, execute, execute_reply, expire_lease, fail_delivery, finished_turn, known_bug,
                             r2, seed_history_barrier, snowflake, v2client)

FORGET = "Hãy quên toàn bộ trí nhớ về tôi"
R1 = "review2 R1: on a server with a history barrier a reply turn reads created_at its target does not have, and crashes"


# ── R1: replies on a server that has a history barrier ──────────────────────────

@pytest.mark.parametrize("target", ["user_message", "bot_response", "not_found"])
@pytest.mark.xfail(strict=True, raises=KnownBug, reason=R1)
def test_r1_1_a_reply_to_something_older_than_the_barrier_is_answered_without_its_words(r2, target):  # noqa: F811
    client, guild = r2.client, r2.guild
    r2.model.rules.append(("Câu cũ", "Đáp án cũ sentinel-r1-old-answer."))
    old = finished_turn(client, guild, "one", "Câu cũ sentinel-r1-old-question.")
    seed_history_barrier(client, guild)
    reply_to = {"user_message": old.message_id, "bot_response": old.response_id, "not_found": snowflake()}[target]
    _, turn_id = enqueue(client, guild, "one", "Trả lời tin kia giúp mình.", reply_to=reply_to)
    calls = len(r2.model.calls)
    response = execute_reply(client, turn_id)
    assert response.status_code == 200, response.text
    assert len(r2.model.calls) == calls + 1, "the model was never asked"
    assert "sentinel-r1-old" not in r2.model.prompts_since(calls)


@pytest.mark.parametrize("target", ["user_message", "bot_response"])
@pytest.mark.xfail(strict=True, raises=KnownBug, reason=R1)
def test_r1_2_a_reply_to_something_newer_than_the_barrier_carries_its_words(r2, monkeypatch, target):  # noqa: F811
    client, guild = r2.client, r2.guild
    seed_history_barrier(client, guild)
    # One turn of history: the target can reach the model only as the reply target.
    monkeypatch.setattr(r2.turns, "history_turn_limit", 1)
    r2.model.rules.append(("Câu mới", "Đáp án mới sentinel-r1-new-answer."))
    new = finished_turn(client, guild, "one", "Câu mới sentinel-r1-new-question.")
    finished_turn(client, guild, "one", "Một tin chen giữa.")
    reply_to = new.message_id if target == "user_message" else new.response_id
    _, turn_id = enqueue(client, guild, "one", "Trả lời tin kia giúp mình.", reply_to=reply_to)
    calls = len(r2.model.calls)
    response = execute_reply(client, turn_id)
    assert response.status_code == 200, response.text
    assert len(r2.model.calls) == calls + 1, "the model was never asked"
    assert "sentinel-r1-new-question" in r2.model.prompts_since(calls)


@pytest.mark.parametrize("target", ["same_session", "other_session", "not_found"])
def test_r1_3_without_a_barrier_a_reply_is_answered(r2, monkeypatch, target):  # noqa: F811
    client, guild = r2.client, r2.guild
    monkeypatch.setattr(r2.turns, "history_turn_limit", 1)
    here = finished_turn(client, guild, "one", "Câu gốc sentinel-r1-here.")
    there = finished_turn(client, guild, "two", "Câu ở kênh khác sentinel-r1-there.")
    finished_turn(client, guild, "one", "Một tin chen giữa.")
    reply_to = {"same_session": here.message_id, "other_session": there.message_id, "not_found": snowflake()}[target]
    _, turn_id = enqueue(client, guild, "one", "Trả lời tin kia giúp mình.", reply_to=reply_to)
    calls = len(r2.model.calls)
    response = execute(client, turn_id)
    assert response.status_code == 200, response.text
    assert len(r2.model.calls) == calls + 1
    prompt = r2.model.prompts_since(calls)
    if target == "same_session":
        assert "sentinel-r1-here" in prompt
    assert "sentinel-r1-there" not in prompt


@pytest.mark.xfail(strict=True, raises=KnownBug, reason=R1)
def test_r1_4_a_reply_to_a_remembered_message_that_was_deleted_never_shows_its_words(r2):  # noqa: F811
    client, guild = r2.client, r2.guild
    gone = finished_turn(client, guild, "one", "Hãy nhớ mã riêng sentinel-r1-gone.")
    before = channel_barrier(client, guild, "one")
    deleted = client.post(f"/api/discord/history/messages/{gone.message_id}/delete",
                          json={"guild_id": guild, "channel_id": "one"})
    assert deleted.status_code == 200, deleted.text
    assert channel_barrier(client, guild, "one") != before, "deleting a remembered message left the barrier in place"
    time.sleep(0.05)
    _, turn_id = enqueue(client, guild, "one", "Trả lời tin kia giúp mình.", reply_to=gone.message_id)
    calls = len(r2.model.calls)
    response = execute_reply(client, turn_id)
    assert response.status_code == 200, response.text
    assert len(r2.model.calls) == calls + 1, "the model was never asked"
    assert "sentinel-r1-gone" not in r2.model.prompts_since(calls)


# ── N2: a reply whose target was edited (tombstone under "__deleted__", no barrier) ──

N2 = "review2 N2: a reply turn shows the model its target's words without checking the target's tombstone"


@pytest.mark.xfail(strict=True, raises=KnownBug, reason=N2)
def test_n2_1_a_reply_to_an_edited_message_does_not_show_its_old_words(r2):  # noqa: F811
    client, guild = r2.client, r2.guild
    target = finished_turn(client, guild, "one", "Tin gốc sentinel-n2-old-question.")
    edit_unledgered(client, guild, "one", target.message_id, "Tin gốc đã sửa.")
    _, turn_id = enqueue(client, guild, "one", "Trả lời tin kia giúp mình.", reply_to=target.message_id)
    calls = len(r2.model.calls)
    response = execute(client, turn_id)
    assert response.status_code == 200, response.text
    assert len(r2.model.calls) == calls + 1
    known_bug("sentinel-n2-old" not in r2.model.prompts_since(calls),
              "the edited message's old words reached the model as the reply target")


@pytest.mark.xfail(strict=True, raises=KnownBug, reason=N2)
def test_n2_2_a_reply_to_the_answer_of_an_edited_question_shows_neither(r2):  # noqa: F811
    client, guild = r2.client, r2.guild
    r2.model.rules.append(("Tin gốc", "Đáp án cũ sentinel-n2-old-answer."))
    target = finished_turn(client, guild, "one", "Tin gốc sentinel-n2-old-question.")
    edit_unledgered(client, guild, "one", target.message_id, "Tin gốc đã sửa.")
    _, turn_id = enqueue(client, guild, "one", "Trả lời câu của Ún giúp mình.", reply_to=target.response_id)
    calls = len(r2.model.calls)
    response = execute(client, turn_id)
    assert response.status_code == 200, response.text
    assert len(r2.model.calls) == calls + 1
    known_bug("sentinel-n2-old" not in r2.model.prompts_since(calls),
              "the edited question or its old answer reached the model as the reply target")


# ── R3: a finished or saved answer handed back after its question was edited ──

R3 = "review2 R3: a replay or a resend hands back the answer of a question that was edited since"
OLD_ANSWER = "Đáp án cũ sentinel-r3-old."


def answer_of(response) -> str:
    return (response.json().get("answer") or "") if response.status_code == 200 else ""


@pytest.mark.xfail(strict=True, raises=KnownBug, reason=R3)
def test_r3_1_replaying_a_finished_turn_after_its_question_was_edited_does_not_return_the_old_answer(r2):  # noqa: F811
    client, guild = r2.client, r2.guild
    r2.model.rules.append(("sentinel-r3", OLD_ANSWER))
    done = finished_turn(client, guild, "one", "Câu hỏi sentinel-r3.")
    assert done.answer == OLD_ANSWER
    edit_unledgered(client, guild, "one", done.message_id)
    replay = execute(client, done.turn_id)
    known_bug("sentinel-r3-old" not in answer_of(replay), f"the replay returned the old answer: {replay.text}")


@pytest.mark.xfail(strict=True, raises=KnownBug, reason=R3)
def test_r3_2_resending_a_saved_answer_after_its_question_was_edited_does_not_return_it(r2):  # noqa: F811
    client, guild = r2.client, r2.guild
    r2.model.rules.append(("sentinel-r3", OLD_ANSWER))
    message_id, turn_id = enqueue(client, guild, "one", "Câu hỏi sentinel-r3.")
    first = execute(client, turn_id)
    assert first.status_code == 200 and first.json()["answer"] == OLD_ANSWER, first.text
    assert fail_delivery(client, turn_id, first.json()["execution_token"]) == "queued"
    edit_unledgered(client, guild, "one", message_id)
    again = execute(client, turn_id)
    known_bug("sentinel-r3-old" not in answer_of(again), f"the resend returned the old answer: {again.text}")


@pytest.mark.parametrize("change", ["remembered_then_edited", "deleted_with_its_channel"])
def test_r3_3_resending_after_the_channel_barrier_moved_does_not_return_the_old_answer(r2, change):  # noqa: F811
    client, guild = r2.client, r2.guild
    r2.model.rules.append(("sentinel-r3", OLD_ANSWER))
    body = "Hãy nhớ câu hỏi sentinel-r3." if change == "remembered_then_edited" else "Câu hỏi sentinel-r3."
    message_id, turn_id = enqueue(client, guild, "one", body)
    first = execute(client, turn_id)
    assert first.status_code == 200 and first.json()["answer"] == OLD_ANSWER, first.text
    assert fail_delivery(client, turn_id, first.json()["execution_token"]) == "queued"
    before = channel_barrier(client, guild, "one")
    if change == "remembered_then_edited":
        client.post(f"/api/discord/history/messages/{message_id}/edit", json={"content": "đã sửa"})
    else:
        client.post(f"/api/discord/history/messages/{message_id}/delete", json={"guild_id": guild, "channel_id": "one"})
    assert channel_barrier(client, guild, "one") != before
    again = execute(client, turn_id)
    assert again.status_code == 200, again.text
    assert "sentinel-r3-old" not in answer_of(again)


@pytest.mark.parametrize("change", ["nothing", "forget"])
def test_r3_4_replaying_a_finished_turn(r2, change):  # noqa: F811
    client, guild = r2.client, r2.guild
    r2.model.rules.append(("sentinel-r3", OLD_ANSWER))
    done = finished_turn(client, guild, "one", "Câu hỏi sentinel-r3.")
    if change == "forget":
        r2.memory.forget_actor(f"discord:{guild}", "alice")
    replay = execute(client, done.turn_id)
    assert replay.status_code == 200, replay.text
    if change == "nothing":
        assert replay.json()["answer"] == OLD_ANSWER
    else:
        assert "sentinel-r3-old" not in answer_of(replay)


# ── N4: a "forget" or "remember" turn that is tried again ───────────────────────

N4 = "review2 N4: a forget turn tried again finds the barrier its own first attempt set, and calls itself stale"


@pytest.mark.xfail(strict=True, raises=KnownBug, reason=N4)
def test_n4_1_retrying_a_forget_turn_tells_the_person_it_forgot(r2):  # noqa: F811
    client, guild = r2.client, r2.guild
    r2.model.failures = 1
    _, turn_id = enqueue(client, guild, "one", FORGET)
    first = execute(client, turn_id)
    assert first.status_code == 200 and first.json()["status"] == "queued", first.text
    assert r2.model.failures == 0, "the first attempt never reached the model"
    calls = len(r2.model.calls)
    again = execute(client, turn_id)
    assert again.status_code == 200, again.text
    seen = (again.json().get("answer") or "") + r2.model.prompts_since(calls)
    known_bug("đã quên" in seen.lower(), f"the retried forget turn carries no receipt: {again.json().get('answer')!r}")


@pytest.mark.xfail(strict=True, raises=KnownBug, reason=N4)
def test_n4_2_resending_a_saved_forget_answer_returns_that_answer(r2):  # noqa: F811
    client, guild = r2.client, r2.guild
    saved = "Ún đã quên hết những gì bạn nhờ nhớ sentinel-n4-2."
    r2.model.rules.append(("Hãy quên", saved))
    _, turn_id = enqueue(client, guild, "one", FORGET)
    first = execute(client, turn_id)
    assert first.status_code == 200 and first.json()["answer"] == saved, first.text
    assert fail_delivery(client, turn_id, first.json()["execution_token"]) == "queued"
    again = execute(client, turn_id)
    assert again.status_code == 200, again.text
    known_bug(again.json().get("answer") == saved, f"the resend replaced the saved answer: {again.json().get('answer')!r}")


def test_n4_3_retrying_a_forget_turn_forgets_only_once(r2):  # noqa: F811
    # Passes today only because of N4 itself (the retry never forgets again); a fix of N4
    # must keep it passing.
    client, guild = r2.client, r2.guild
    r2.model.failures = 1
    _, turn_id = enqueue(client, guild, "one", FORGET)
    first = execute(client, turn_id)
    assert first.status_code == 200 and first.json()["status"] == "queued", first.text
    # Between the two attempts the same person asks Ún to remember something in another channel.
    finished_turn(client, guild, "two", "Hãy nhớ mã mới sentinel-n4-3.")
    assert any("sentinel-n4-3" in note for note in active_notes(r2.memory, guild, "two"))
    again = execute(client, turn_id)
    assert again.status_code == 200, again.text
    assert any("sentinel-n4-3" in note for note in active_notes(r2.memory, guild, "two"))


def test_n4_4_retrying_a_remember_turn_saves_one_source_and_says_so(r2):  # noqa: F811
    client, guild = r2.client, r2.guild
    r2.model.failures = 1
    _, turn_id = enqueue(client, guild, "one", "Hãy nhớ mã riêng sentinel-n4-4.")
    first = execute(client, turn_id)
    assert first.status_code == 200 and first.json()["status"] == "queued", first.text
    calls = len(r2.model.calls)
    again = execute(client, turn_id)
    assert again.status_code == 200 and again.json()["answer"], again.text
    assert re.search(r"(?<!bạn )đã lưu", r2.model.prompts_since(calls)), "no 'saved' receipt reached the model"
    assert [note for note in active_notes(r2.memory, guild, "one") if "sentinel-n4-4" in note] == [
        "Hãy nhớ mã riêng sentinel-n4-4."]


# ── A, seen from the backend ────────────────────────────────────────────────────

@pytest.mark.parametrize("path", ["other_channel", "same_channel_after_cancel_open"])
def test_a2_an_abandoned_turn_blocks_neither_another_channel_nor_the_operator_stop(r2, path):  # noqa: F811
    client, guild = r2.client, r2.guild
    _, orphan = enqueue(client, guild, "one", "Tin bị bỏ dở.")
    assert execute(client, orphan).json()["status"] == "running"  # the bot got the answer, then died
    assert age_open_turns(client, guild) == [orphan]
    channel = "two"
    if path == "same_channel_after_cancel_open":
        stopped = client.post("/api/discord/sessions/turns/cancel-open")
        assert stopped.status_code == 200 and stopped.json()["cancelled_turns"] >= 1, stopped.text
        channel = "one"
    _, turn_id = enqueue(client, guild, channel, "Tin mới.")
    executed = execute(client, turn_id)
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "running" and executed.json()["answer"]


def test_a3_a_bot_returning_after_its_lease_ran_out_gets_the_saved_answer_without_a_second_model_call(r2):  # noqa: F811
    client, guild = r2.client, r2.guild
    r2.model.rules.append(("sentinel-a3", "Đáp án đã lưu sentinel-a3."))
    _, turn_id = enqueue(client, guild, "one", "Câu hỏi sentinel-a3.")
    first = execute(client, turn_id)
    assert first.status_code == 200 and first.json()["status"] == "running", first.text
    expire_lease(client, turn_id)
    calls = len(r2.model.calls)
    again = execute(client, turn_id)
    assert again.status_code == 200, again.text
    assert again.json()["status"] == "running" and again.json()["answer"] == "Đáp án đã lưu sentinel-a3."
    assert len(r2.model.calls) == calls
