"""Review2 R4 (web chat): a "remember" sent before a "forget" is never saved after it.

A web turn notes when the message arrived, then reads the memory's state (the snapshot), then
saves. A forget that committed between the arrival and the snapshot moved the barrier past the
message, but the snapshot already showed the forget's new epoch, so the save went through: the
words were hidden from the history yet kept as a note.

The forget here is a real call, made the first time the turn asks for its snapshot. That point
pins the fix chosen on 11/11/2026: the send time is read from the database clock BEFORE the
snapshot, and save() refuses a send time at or before the barrier. This is not the meeting's
"4b", which reads the time inside the snapshot itself: under that fix a forget landing before
the snapshot counts as earlier than the remember, the note is saved, and R4-1 would have to be
rewritten with two threads. DECISIONS.md left R4-1 out of the first suite until the owner
chose; the choice is recorded as changeable. Before the fix R4-1 fails whatever the clocks say: the snapshot carries the
post-forget epoch, so the epoch check passes and the note is saved. R4-0 is the same turn with
nothing in between, so R4-1 can fail only because of the forget. No case waits on a timer.
"""
from __future__ import annotations

from uuid import uuid4

from review2_support import r2, v2client  # noqa: F401  (fixtures)


def remember_a_code(r2, monkeypatch, *, forget_before_the_snapshot: bool) -> bool:  # noqa: F811
    """Ask over /chat to remember a fresh code. True when the code is among the notes after."""
    from app.services.source_memory import MemoryReader
    client, memory = r2.client, r2.memory
    code = f"sentinel-r4-{uuid4().hex[:8]}"
    original, forgotten = memory.snapshot, []

    def snapshot(reader):
        # One-shot: later snapshots of the same turn (history reads) pass straight through.
        if forget_before_the_snapshot and not forgotten:
            forgotten.append(memory.forget_actor(reader.tenant, reader.actor))
        return original(reader)

    monkeypatch.setattr(memory, "snapshot", snapshot)
    said = client.post("/chat", json={"message": f"Hãy nhớ mật mã của tôi là {code}."})
    assert said.status_code == 200, said.text
    assert len(forgotten) == int(forget_before_the_snapshot), "the forget did not run once, at the snapshot"
    listed = client.get("/memory/notes")
    assert listed.status_code == 200, listed.text
    kept = [row for row in listed.json() if code in row["content"]]
    for row in kept:  # no active note is left behind for later tests
        memory.retract(MemoryReader.web(None), row["id"])
    return bool(kept)


def test_r4_0_a_remember_with_nothing_in_between_is_saved(r2, monkeypatch):  # noqa: F811
    assert remember_a_code(r2, monkeypatch, forget_before_the_snapshot=False), \
        "a plain remember was not saved, so R4-1 would prove nothing"


def test_r4_1_a_forget_between_the_send_and_the_snapshot_keeps_the_remember_out(r2, monkeypatch):  # noqa: F811
    assert not remember_a_code(r2, monkeypatch, forget_before_the_snapshot=True), \
        "the remember sent before the forget was saved after it"
