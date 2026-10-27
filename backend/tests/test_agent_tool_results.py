"""Tool results that overflow tool_result_max_chars lose whole items, never half of one.

Agent Eval baseline v0.1 (27/10): the old character cut broke the JSON of every
top_k=5 document search, and on the chronological "latest N" history read it cut
exactly the newest messages (hist-05: 8 of 18 gone). No stack: the backends are
fakes; this exercises AgentService._execute_tool as the model receives it.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from app.discord import agent_tools
from app.discord.history_service import DiscordHistoryHit, history_hit_payload
from app.services.agent_service import AgentService


def hit(index: int, content: str | None = None) -> DiscordHistoryHit:
    return DiscordHistoryHit(
        discord_message_id=str(7000 + index), channel_id="50", thread_id=None,
        author_id="1001", author_display_name="Lan", is_bot=False,
        content=content or f"Tin số {index}: " + "nội dung khá dài để đầy giới hạn " * 3,
        sent_at=datetime(2026, 10, 1, tzinfo=UTC) + timedelta(hours=index),
        link=f"https://discord.com/channels/1/50/{7000 + index}",
    )


class History:
    def __init__(self, count: int):
        self.hits = [hit(i) for i in range(1, count + 1)]  # chronological, like the real service

    def recent(self, *, guild_id, limit=20, author_id=None):
        return self.hits[-limit:]

    def search(self, *, guild_id, query, author_id=None, days=None, limit=5):
        return list(reversed(self.hits))[:limit]  # densest first; here: newest first


class Retrieval:
    def retrieve(self, query, top_k, document_id=None):
        return [{"filename": f"tai_lieu_{i}.pdf", "page": i, "content": "x" * 600, "score": 1 - i / 10} for i in range(1, top_k + 1)]


def agent(history=None, limit=2400) -> AgentService:
    service = AgentService(router=None, retrieval_service=Retrieval(), operational_service=None, tool_result_max_chars=limit)
    agent_tools.register(service.registry, history)  # search_history, as the API plugs it in (ticket 22, C4)
    return service


def test_latest_messages_keep_the_newest_and_say_how_many_older_ones_went():
    output = agent(History(18))._execute_tool("search_history", {"limit": 25}, {"guild_id": "g"})

    payload = json.loads(output)  # whole JSON, never cut mid-item
    assert len(output) <= 2400
    # An overflow is an object, so the note can never be counted as a message.
    assert set(payload) == {"omitted", "note", "items"}
    messages = payload["items"]
    assert payload["omitted"] == 18 - len(messages) and "cũ nhất" in payload["note"]
    assert all("message" in item for item in messages)
    assert messages[-1]["message"].startswith("Tin số 18:"), "the newest message survives"
    assert messages[0]["message"].startswith(f"Tin số {payload['omitted'] + 1}:"), "only the oldest went, in order"


def test_a_ranked_list_gives_up_its_lowest_ranked_items():
    # Six 400-character excerpts cannot fit in 2400 (real chunks overflow at five:
    # their newlines and quotes double in JSON).
    output = agent()._execute_tool("search_documents", {"query": "q", "top_k": 6}, None)

    payload = json.loads(output)
    chunks = payload["items"]
    assert len(output) <= 2400
    assert [c["filename"] for c in chunks] == [f"tai_lieu_{i}.pdf" for i in range(1, len(chunks) + 1)], "top ranks kept"
    assert payload["omitted"] == 6 - len(chunks) >= 1 and "xếp cuối" in payload["note"]

    searched = json.loads(agent(History(18))._execute_tool("search_history", {"query": "tin", "limit": 10}, {"guild_id": "g"}))
    assert searched["items"][0]["message"].startswith("Tin số 18:") and searched["omitted"] >= 1, "a keyword search is ranked: its tail goes"


def test_a_result_that_fits_is_byte_identical_to_before():
    hits = History(3).hits
    small = agent(History(3))._execute_tool("search_history", {"limit": 3}, {"guild_id": "g"})
    assert small == json.dumps([history_hit_payload(h) for h in hits], ensure_ascii=False, default=str)

    four = agent()._execute_tool("search_documents", {"query": "q", "top_k": 4}, None)
    assert isinstance(json.loads(four), list) and len(json.loads(four)) == 4 and "omitted" not in four


def test_a_discord_length_message_is_capped_so_whole_items_still_fit():
    # 2000 characters, Discord's limit, with the newlines and quotes that double in JSON.
    long_text = 'Tin dài "có nháy"\n' * 112
    history = History(0)
    history.hits = [hit(i, f"Tin số {i}: {long_text}") for i in range(1, 4)]

    output = agent(history)._execute_tool("search_history", {"limit": 3}, {"guild_id": "g"})

    payload = json.loads(output)  # valid JSON: no fallback to cutting mid-string
    assert len(output) <= 2400
    messages = payload["items"] if isinstance(payload, dict) else payload
    assert all(len(m["message"]) == 800 and m["message"].endswith("…") for m in messages)
    assert messages[-1]["message"].startswith("Tin số 3:"), "still the newest that survives"


def test_what_cannot_be_split_into_items_keeps_the_character_cut():
    status = AgentService(None, None, type("S", (), {"health": lambda self: {"note": "x" * 5000}})(), tool_result_max_chars=300)
    output = status._execute_tool("system_status", {}, None)
    assert len(output) == 300 and output.endswith("…")

    # One item alone longer than the limit: nothing whole fits, so the old cut applies.
    lonely = agent(History(1), limit=200)._execute_tool("search_history", {"limit": 1}, {"guild_id": "g"})
    assert len(lonely) == 200 and lonely.endswith("…")


def test_the_history_tool_tells_the_model_messages_are_capped():
    # Without it the model may quote a clipped message as if it were complete (review 27/10).
    from app.discord.agent_tools import HISTORY_MESSAGE_MAX_CHARS

    history = next(tool["function"] for tool in agent().registry.schemas() if tool["function"]["name"] == "search_history")
    assert f"mỗi tin tối đa {HISTORY_MESSAGE_MAX_CHARS} ký tự" in history["description"]
