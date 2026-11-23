"""The small-model aids of 23/11/2026 and the v2 search_history fix. No stack: fakes and a scripted model.

Each aid is off by default and off means the turn is what it was; on, each does one thing:
- scoped_tools: a Discord-only tool is not offered on a turn without a guild, and the guide names only
  the tools offered (Agent Eval doc-31: qwen3.5:2b called search_history on a web document task).
- dedupe_calls: a call identical to one that already ran this turn is answered with a note, not run
  (doc-51, doc-53, doc-54: the same search two or three times in a row).
- focused_excerpts: the search excerpt is the part of a chunk the query is about (doc-33..37).
- history_hints: a search_history keyword miss says how to read the latest messages (hist-08).
The fix: the v2 latest-N history read kept the oldest messages and cut the newest.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from app.discord import agent_tools
from app.discord.agent_tools import HISTORY_NO_MATCH, HISTORY_NO_MATCH_HINT
from app.discord.history_service import DiscordHistoryHit
from app.discord.source_memory import HISTORY_ITEM_OVERHEAD, HISTORY_RESULT_BUDGET, fit_history
from app.services.agent_service import (
    AGENT_GUIDE,
    DUPLICATE_CALL,
    SEARCH_DOCUMENTS_FOCUSED_SCHEMA,
    SEARCH_DOCUMENTS_SCHEMA,
    SEARCH_EXCERPT_CHARS,
    UNKNOWN_TOOL,
    AgentService,
    AgentTool,
    _clip,
    agent_guide_for,
)
from app.services.excerpts import ELLIPSIS, focused_excerpt

FIVE = ("search_documents", "search_history", "system_status", "current_time", "calculate")


def final(text: str) -> dict:
    return {"content": text, "tool_calls": [], "raw_tool_calls": []}


def call(name: str, arguments: dict) -> dict:
    return {"content": "", "tool_calls": [{"name": name, "arguments": arguments}], "raw_tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


class Router:
    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.prompts: list[list[dict]] = []
        self.tools: list[list[str]] = []

    def chat_tools(self, role, messages, tools):
        self.prompts.append([dict(message) for message in messages])
        self.tools.append([tool["function"]["name"] for tool in tools])
        return self.rounds.pop(0), "fake"

    def chat(self, role, messages):
        self.prompts.append([dict(message) for message in messages])
        return "hết lượt", "fake"


class Retrieval:
    def __init__(self, content: str = "Phụ cấp lưu trú là 300.000 đồng/người/ngày."):
        self.content = content
        self.queries: list[str] = []

    def retrieve(self, query, top_k, document_id=None):
        self.queries.append(query)
        return [{"filename": "quy_dinh.pdf", "page": 2, "content": self.content, "score": 0.9}]


def hit(index: int) -> DiscordHistoryHit:
    return DiscordHistoryHit(
        discord_message_id=str(9000 + index), channel_id="50", thread_id=None, author_id="1001",
        author_display_name="Lan", is_bot=False, content=f"Tin số {index}: " + "nội dung " * 20,
        sent_at=datetime(2026, 10, 1, tzinfo=UTC) + timedelta(hours=index), link=f"https://discord.com/channels/1/50/{9000 + index}",
    )


class History:
    def __init__(self, count: int = 3, found: bool = True):
        self.hits = [hit(i) for i in range(1, count + 1)]
        self.found = found

    def recent(self, *, guild_id, limit=20, author_id=None):
        return self.hits[-limit:]

    def search(self, *, guild_id, query, author_id=None, days=None, limit=5):
        return list(reversed(self.hits))[:limit] if self.found else []


def agent(router=None, retrieval=None, history=None, **aids) -> AgentService:
    service = AgentService(router, retrieval or Retrieval(), None, **aids)
    agent_tools.register(service.registry, history or History())
    return service


def run(service: AgentService, user: str, tool_context=None):
    return service.run([{"role": "system", "content": "Bạn là Ún."}, {"role": "user", "content": user}], tool_context)


# --- the v2 search_history fix ------------------------------------------------------------------


def item(index: int, size: int = 600) -> dict:
    return {"source_id": f"discord:{index}", "message": f"tin {index} " + "x" * size, "sent_at": f"2026-10-{index:02d}"}


def test_a_latest_n_read_keeps_the_newest_messages_in_time_order():
    newest_first = [item(index) for index in range(30, 0, -1)]
    payload, drop = fit_history(newest_first, chronological=True)
    kept = [entry["source_id"] for entry in payload]
    assert kept[-1] == "discord:30", "the newest message survives the budget"
    assert kept == sorted(kept, key=lambda source: int(source.split(":")[1])), "shown oldest to newest"
    assert drop == "first", "an overflow at the tool cap gives up the oldest"
    assert sum(len(entry["message"]) + HISTORY_ITEM_OVERHEAD for entry in payload) <= HISTORY_RESULT_BUDGET


def test_a_keyword_search_keeps_its_best_matches_first():
    ranked = [item(index) for index in (7, 3, 9, 1, 5, 2, 8, 4, 6)]
    payload, drop = fit_history(ranked, chronological=False)
    assert [entry["source_id"] for entry in payload] == [entry["source_id"] for entry in ranked[: len(payload)]]
    assert drop == "last"


def test_at_the_tool_cap_the_newest_message_still_reaches_the_model():
    newest_first = [{**item(index, 200), "author_id": "1", "link": "l"} for index in range(25, 0, -1)]
    payload, drop = fit_history(newest_first, chronological=True)
    output = json.loads(AgentService(None, None, None)._dump(payload, drop=drop))
    shown = output["items"] if isinstance(output, dict) else output
    assert shown[-1]["source_id"] == "discord:25"


# --- scoped_tools ---------------------------------------------------------------------------


def test_the_guide_built_from_all_five_tools_is_agent_guide_byte_for_byte():
    assert agent_guide_for(frozenset(FIVE)) == AGENT_GUIDE


def test_without_search_history_the_guide_names_neither_it_nor_its_citation_rule():
    guide = agent_guide_for(frozenset(FIVE) - {"search_history"})
    assert "search_history" not in guide and "tin nhắn cũ" not in guide
    assert "`search_documents`" in guide and guide.endswith("trả lời trọn vẹn bằng tiếng Việt.")
    assert agent_guide_for(frozenset()).startswith("Bạn có thể dùng công cụ khi cần dữ liệu thật. Chỉ gọi")


def test_off_a_web_turn_is_offered_search_history_as_before():
    router = Router([final("Chào bạn.")])
    run(agent(router), "Chào")
    assert "search_history" in router.tools[0]
    assert router.prompts[0][1]["content"] == AGENT_GUIDE


def test_on_a_web_turn_is_not_offered_discord_only_tools_and_the_guide_follows():
    router = Router([final("Chào bạn.")])
    run(agent(router, scoped_tools=True), "Chào")
    assert "search_history" not in router.tools[0] and "search_documents" in router.tools[0]
    assert "search_history" not in router.prompts[0][1]["content"]


def test_on_a_discord_turn_keeps_them():
    router = Router([final("Chào bạn.")])
    run(agent(router, scoped_tools=True), "Chào", {"guild_id": "g"})
    assert "search_history" in router.tools[0]
    assert router.prompts[0][1]["content"] == AGENT_GUIDE


def test_on_a_hidden_tool_called_by_name_is_an_unknown_tool():
    router = Router([call("search_history", {"query": "họp"}), final("Ở đây không xem được tin Discord.")])
    _, _, steps = run(agent(router, scoped_tools=True), "Hôm qua họp gì?")
    result = next(step for step in steps if step["kind"] == "tool_result")
    assert result["error_code"] == UNKNOWN_TOOL and result["tool_declared"] is False


def test_a_promised_discord_only_tool_still_counts_on_a_discord_turn():
    service = agent(scoped_tools=True)
    schema = {"type": "function", "function": {"name": "remind", "parameters": {"type": "object", "properties": {}}}}
    service.registry.register(AgentTool(schema, lambda *_: ("{}", None, None), promised=lambda context: True, discord_only=True), 26)
    assert [tool.name for tool in service._promises({"guild_id": "g"})] == ["remind"]
    assert service._promises(None) == []


# --- dedupe_calls -------------------------------------------------------------------------


def repeated_search():
    return [call("search_documents", {"query": "phụ cấp lưu trú", "top_k": 4}), call("search_documents", {"top_k": 4, "query": "phụ cấp lưu trú"}), final("300.000 đồng (quy_dinh.pdf, trang 2).")]


def test_off_an_identical_call_runs_again():
    retrieval = Retrieval()
    run(agent(Router(repeated_search()), retrieval), "Phụ cấp lưu trú bao nhiêu?")
    assert len(retrieval.queries) == 2


def test_on_an_identical_call_is_answered_with_a_note_and_not_run():
    retrieval = Retrieval()
    answer, _, steps = run(agent(Router(repeated_search()), retrieval, dedupe_calls=True), "Phụ cấp lưu trú bao nhiêu?")
    results = [step for step in steps if step["kind"] == "tool_result"]
    assert len(retrieval.queries) == 1, "key order aside, the second call is the same call"
    assert [result["error_code"] for result in results] == [None, DUPLICATE_CALL]
    assert "không chạy lại" in json.loads(results[1]["content"])["error"]
    assert answer.startswith("300.000")


def test_on_a_call_that_failed_may_be_tried_again():
    router = Router([call("calculate", {"expression": "2 +"}), call("calculate", {"expression": "2 +"}), final("Biểu thức sai.")])
    _, _, steps = run(agent(router, dedupe_calls=True), "2 + bằng mấy?")
    assert [step["error_code"] for step in steps if step["kind"] == "tool_result"] == ["BAD_ARGUMENTS", "BAD_ARGUMENTS"]


# --- focused_excerpts ---------------------------------------------------------------------


FILLER = "Phần mở đầu nói về lịch sử công ty và các quy định chung áp dụng cho mọi phòng ban trong năm. " * 6
ANSWER = "Bộ lưu điện (UPS) của phòng máy chủ có công suất 1500 VA và giữ máy chạy được 20 phút."


def test_an_answer_past_the_head_is_shown_with_an_ellipsis_on_each_cut_side():
    content = FILLER + ANSWER + " " + FILLER
    excerpt, start = focused_excerpt(content, "công suất UPS phòng máy chủ", SEARCH_EXCERPT_CHARS)
    assert "1500 VA" in excerpt and start > 0
    assert excerpt.startswith(ELLIPSIS) and excerpt.endswith(ELLIPSIS)
    assert len(excerpt) <= SEARCH_EXCERPT_CHARS
    assert excerpt[1:20] in content[start:start + 40]


def test_the_head_stays_when_no_window_matches_more_of_the_query():
    content = ANSWER + " " + FILLER * 2
    assert focused_excerpt(content, "công suất UPS", SEARCH_EXCERPT_CHARS) == (_clip(content, SEARCH_EXCERPT_CHARS), 0)


def test_a_query_of_function_words_only_or_a_short_chunk_changes_nothing():
    content = FILLER * 3
    assert focused_excerpt(content, "là gì vậy bạn", SEARCH_EXCERPT_CHARS) == (_clip(content, SEARCH_EXCERPT_CHARS), 0)
    assert focused_excerpt(ANSWER, "UPS", SEARCH_EXCERPT_CHARS) == (ANSWER, 0)


def test_on_search_documents_shows_the_focused_excerpt_and_says_so_in_its_description():
    content = FILLER + ANSWER + " " + FILLER
    router = Router([call("search_documents", {"query": "công suất UPS phòng máy chủ"}), final("1500 VA.")])
    service = agent(router, Retrieval(content), focused_excerpts=True)
    _, _, steps = run(service, "UPS phòng máy chủ công suất bao nhiêu?")
    shown = json.loads(next(step for step in steps if step["kind"] == "tool_result")["content"])
    assert "1500 VA" in shown[0]["excerpt"] and shown[0]["excerpt_from"] > 0
    assert SEARCH_DOCUMENTS_FOCUSED_SCHEMA in service._offered_schemas()
    assert SEARCH_DOCUMENTS_SCHEMA not in service._offered_schemas()
    assert service._offered_schemas() != agent()._offered_schemas()


def test_off_search_documents_shows_the_head_as_before():
    content = FILLER + ANSWER
    router = Router([call("search_documents", {"query": "công suất UPS"}), final("Không rõ.")])
    _, _, steps = run(agent(router, Retrieval(content)), "UPS bao nhiêu?")
    shown = json.loads(next(step for step in steps if step["kind"] == "tool_result")["content"])
    assert shown[0]["excerpt"] == _clip(content, SEARCH_EXCERPT_CHARS) and "excerpt_from" not in shown[0]


# --- final_keeps_tools --------------------------------------------------------------------


class FinalRouter(Router):
    """Three tool rounds, then a forced answer: `final_round` is what chat_tools returns for it."""

    def __init__(self, final_round):
        super().__init__([call("current_time", {}), call("system_status", {}), call("calculate", {"expression": "1+1"}), final_round])
        self.plain_calls = 0

    def chat(self, role, messages):
        self.plain_calls += 1
        return super().chat(role, messages)


class Status:
    def health(self):
        return {"status": "ok"}


def forced(final_round, **aids):
    router = FinalRouter(final_round)
    service = AgentService(router, Retrieval(), Status(), **aids)
    answer, _, steps = run(service, "Mấy giờ rồi và hệ thống ổn không?")
    return answer, steps, router


def test_off_the_forced_answer_is_asked_without_tools():
    answer, steps, router = forced(final("không dùng"))
    assert answer == "hết lượt" and router.plain_calls == 1 and len(router.tools) == 3
    assert steps[-1]["stop_reason"] == "max_steps"


def test_on_the_forced_answer_keeps_the_tool_list_and_the_prompt_head():
    answer, steps, router = forced(final("Bây giờ là 10:00, hệ thống ổn."), final_keeps_tools=True)
    assert answer == "Bây giờ là 10:00, hệ thống ổn." and router.plain_calls == 0
    assert router.tools[3] == router.tools[2], "the same tools as the round before"
    assert router.prompts[3][: len(router.prompts[2])] == router.prompts[2], "only appended to"
    assert steps[-1]["stop_reason"] == "max_steps"


def test_on_a_call_instead_of_an_answer_is_not_run_and_the_answer_is_asked_without_tools():
    answer, steps, router = forced(call("current_time", {}), final_keeps_tools=True)
    assert answer == "hết lượt" and router.plain_calls == 1
    assert sum(1 for step in steps if step["kind"] == "tool_result") == 3


# --- history_hints ------------------------------------------------------------------------


def test_off_a_keyword_miss_reads_as_before():
    output = json.loads(agent(history=History(found=False))._execute_tool("search_history", {"query": "bàn chuyện hôm qua"}, {"guild_id": "g"}))
    assert output == {"result": "không tìm thấy tin nhắn cũ nào khớp"}


def test_on_a_keyword_miss_says_how_to_read_the_latest_messages():
    output = json.loads(agent(history=History(found=False), history_hints=True)._execute_tool("search_history", {"query": "bàn chuyện hôm qua"}, {"guild_id": "g"}))
    assert output == {"result": HISTORY_NO_MATCH, "hint": HISTORY_NO_MATCH_HINT}
    assert "bỏ trống query" in output["hint"]
