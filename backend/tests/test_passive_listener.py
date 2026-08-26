"""memory_design.md §13.6 job 1: the passive counter that gates the raw
ledger. Pure logic plus the two failure rules — a thread counts toward its
parent channel, and a write failure never raises into the answering path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from discord_bot.passive_listener import (  # noqa: E402
    PassiveListener,
    parse_listen_channel_ids,
    resolve_listened_channel,
)


def test_parse_is_whitespace_and_empty_tolerant():
    assert parse_listen_channel_ids("") == frozenset()
    assert parse_listen_channel_ids(" 123 , 456 ,, ") == frozenset({"123", "456"})


def test_threads_count_toward_their_parent_channel():
    listened = frozenset({"100"})
    assert resolve_listened_channel("100", None, listened) == "100"
    # A thread inside the listened channel inherits the decision (§5.4).
    assert resolve_listened_channel("999", "100", listened) == "100"
    # An unrelated channel — and a thread under one — stays out.
    assert resolve_listened_channel("200", None, listened) is None
    assert resolve_listened_channel("999", "200", listened) is None


def test_record_writes_ids_and_flags_but_never_content(tmp_path):
    path = tmp_path / "counts.jsonl"
    listener = PassiveListener(path, frozenset({"100"}))

    assert listener.record(
        guild_id="g1", channel_id="100", parent_channel_id=None,
        author_id="u1", author_is_bot=False, is_mention=False,
    )
    assert listener.record(
        guild_id="g1", channel_id="777", parent_channel_id="100",
        author_id="u2", author_is_bot=True, is_mention=True,
    )
    # Not listened, DM (no guild), disabled listener: all refused.
    assert not listener.record(
        guild_id="g1", channel_id="200", parent_channel_id=None,
        author_id="u1", author_is_bot=False, is_mention=False,
    )
    assert not listener.record(
        guild_id=None, channel_id="100", parent_channel_id=None,
        author_id="u1", author_is_bot=False, is_mention=False,
    )
    assert not PassiveListener(path, frozenset()).record(
        guild_id="g1", channel_id="100", parent_channel_id=None,
        author_id="u1", author_is_bot=False, is_mention=False,
    )

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2 and listener.recorded == 2
    assert rows[0]["channel_id"] == "100" and rows[0]["thread_id"] is None
    # The thread row counts toward the parent and remembers which thread.
    assert rows[1]["channel_id"] == "100" and rows[1]["thread_id"] == "777"
    assert rows[1]["author_is_bot"] is True and rows[1]["is_mention"] is True
    for row in rows:
        assert "content" not in row and "text" not in row


def test_write_failure_is_swallowed_not_raised(tmp_path, monkeypatch):
    listener = PassiveListener(tmp_path / "counts.jsonl", frozenset({"100"}))
    monkeypatch.setattr(Path, "open", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    assert not listener.record(
        guild_id="g1", channel_id="100", parent_channel_id=None,
        author_id="u1", author_is_bot=False, is_mention=False,
    )
    assert listener.recorded == 0
