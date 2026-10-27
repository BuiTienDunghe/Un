"""Agent loop for chat (P2-2): plan → act → observe over existing services.

The agent is not a new framework — it is one bounded loop that lets the
general model call three in-house tools (document retrieval, long-term memory,
system health) through Ollama's native function-calling API, then answer. The
caller persists every step as an ``agent_traces`` row, honouring the plan
invariant that autonomous behaviour must leave an inspectable trail.

No database transaction is ever open across the model calls in here: the loop
works on in-memory messages and returns; persistence belongs to the caller.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic, perf_counter
from typing import Any, Protocol

from app.llm_clients.deadline import ModelCallTimeoutError, call_within
from app.llm_clients.usage import consume_usage, record_usage
from app.services.discord_history_service import history_hit_payload
from app.services.injection_defense import InjectionDefense
from app.services.model_router import ModelRouter


class RetrievalBackend(Protocol):
    def retrieve(self, query: str, top_k: int, document_id: str | list[str] | None = None) -> list[dict[str, object]]: ...


class StatusBackend(Protocol):
    def health(self) -> dict[str, object]: ...


class HistoryBackend(Protocol):
    def search(
        self,
        *,
        guild_id: str,
        query: str,
        author_id: str | None = None,
        days: int | None = None,
        limit: int = 5,
    ) -> list[object]: ...

    def recent(
        self,
        *,
        guild_id: str,
        limit: int = 20,
        author_id: str | None = None,
    ) -> list[object]: ...


AGENT_GUIDE = (
    "Bạn có thể dùng công cụ khi cần dữ liệu thật: `search_documents` tìm trong "
    "tài liệu người dùng đã tải lên, `search_history` đọc tin nhắn cũ của "
    "server (có query = tìm từ khóa; bỏ trống query = N tin mới nhất, dùng "
    "khi cần tóm tắt gần đây), `system_status` xem sức khỏe hệ "
    "thống. Chỉ gọi công cụ khi câu hỏi thật sự "
    "cần dữ liệu đó; câu chào hỏi hay kiến thức chung thì trả lời thẳng, không "
    "gọi gì. Khi dùng nội dung tài liệu, nêu tên tệp và số trang. Khi dùng "
    "tin nhắn cũ, nêu ai nói và lúc nào. Khi đã đủ "
    "thông tin, trả lời trọn vẹn bằng tiếng Việt."
)

# A Discord message may run to 2000 characters (4000 with Nitro). Capped the way a
# document excerpt is capped at 400, so the whole-item truncation in _dump always
# has an item that fits instead of falling back to cutting the JSON mid-string.
# The search_history description states the cap, so the model does not quote a
# clipped message as if it were the whole of it.
HISTORY_MESSAGE_MAX_CHARS = 800

SEARCH_DOCUMENTS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_documents",
        "description": "Tìm các đoạn liên quan trong tài liệu đã index (PDF, DOCX, ...). Trả về tên tệp, trang và trích đoạn.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Câu truy vấn, viết thành câu độc lập đủ ngữ cảnh"},
                "top_k": {"type": "integer", "description": "Số đoạn muốn lấy (1-8), mặc định 4"},
            },
            "required": ["query"],
        },
    },
}
SEARCH_HISTORY_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_history",
        "description": f"Đọc lịch sử tin nhắn của server Discord hiện tại (sổ gốc). Có query: tìm theo từ khóa, xếp theo độ khớp. KHÔNG có query: trả về các tin MỚI NHẤT theo thời gian (dùng khi cần tóm tắt N tin gần đây). Trả về đúng câu chữ (mỗi tin tối đa {HISTORY_MESSAGE_MAX_CHARS} ký tự), ai nói, lúc nào và link tới tin nhắn.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Từ khóa cần tìm. BỎ TRỐNG để lấy các tin mới nhất theo thời gian"},
                "author_id": {"type": "string", "description": "Chỉ lấy tin của một người nói (author_id Discord, có trong nhãn ngữ cảnh)"},
                "days": {"type": "integer", "description": "Chỉ tìm trong N ngày gần nhất (tùy chọn, chỉ áp dụng khi có query)"},
                "limit": {"type": "integer", "description": "Số tin muốn lấy (tìm kiếm: 1-10, mặc định 5; tin mới nhất: 1-25, mặc định 20)"},
            },
            "required": [],
        },
    },
}
SYSTEM_STATUS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "system_status",
        "description": "Đọc trạng thái sức khỏe hiện tại của hệ thống (PostgreSQL, Redis, Qdrant, Ollama, các worker, backup).",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}


# A failed tool call reaches the model as {"error": <what to do next>, "code": <CODE>}:
# the sentence is for the model (actionable, per Anthropic's "Writing tools for
# agents"), the code for the trace (a low-cardinality error.type, per OTel GenAI).
# An empty result is a result, not an error. TOOL_TIMEOUT is reserved: tools run
# synchronously and are bounded by their own clients' timeouts (ticket 16, t1).
TOOL_UNAVAILABLE_HERE = "TOOL_UNAVAILABLE_HERE"
BAD_ARGUMENTS = "BAD_ARGUMENTS"
UNKNOWN_TOOL = "UNKNOWN_TOOL"
TOOL_FAILED = "TOOL_FAILED"
TOOL_TIMEOUT = "TOOL_TIMEOUT"

# The whole turn's wall clock (ticket 16). Agent Eval v0.2 measured 3.2-3.6 s median and
# 9.2 s at worst per answer, warm or cold; the Discord bot waits 180 s for a turn. 90 s is
# ~10x the worst and half the bot's wait, so the backend answers before the bot gives up.
# A tool round may start only while the reserve for the final answer is still free.
TURN_BUDGET_SECONDS = 90.0
FINAL_RESERVE_SECONDS = 20.0
# Why the loop ended, on the final step: "final" (the model answered), "max_steps" (tool
# rounds used up), "turn_budget" (time ran short, answered from what was gathered),
# "turn_budget_exhausted" (even the final answer did not fit: the fixed reply below).
STOP_FINAL = "final"
STOP_MAX_STEPS = "max_steps"
STOP_TURN_BUDGET = "turn_budget"
STOP_TURN_BUDGET_EXHAUSTED = "turn_budget_exhausted"


# What a handler returns: (text for the model, error code, exception type).
ToolOutput = tuple[str, str | None, str | None]


@dataclass(frozen=True)
class AgentTool:
    """One tool in the registry: what the model is shown and what runs when it calls it."""

    schema: dict[str, Any]
    run: Callable[["AgentService", dict[str, Any], dict[str, Any] | None], ToolOutput]

    @property
    def name(self) -> str:
        return str(self.schema["function"]["name"])


def arguments_shape(tool_name: object, arguments: object) -> dict[str, object] | None:
    """A tool call's arguments with the content taken out, for the trace that outlives
    the conversation (ticket 16, option b): a declared string becomes "str:<length>", a
    declared integer stays a number, anything else its type name. Keys the tool does not
    declare are only counted — a model can invent a key, and a key can carry words."""
    if not isinstance(arguments, dict):
        return None
    declared = _DECLARED.get(str(tool_name), {})
    shape: dict[str, object] = {}
    undeclared = 0
    for key, value in arguments.items():
        if key not in declared:
            undeclared += 1
        elif declared[key].get("type") == "integer" and isinstance(value, int) and not isinstance(value, bool):
            shape[key] = value
        elif isinstance(value, str):
            shape[key] = f"str:{len(value)}"
        else:
            shape[key] = type(value).__name__
    if undeclared:
        shape["_undeclared"] = undeclared
    return shape


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _history_item(hit: object) -> dict[str, object]:
    payload = history_hit_payload(hit)
    payload["message"] = _clip(str(payload["message"]), HISTORY_MESSAGE_MAX_CHARS)
    return payload


class AgentService:
    def __init__(
        self,
        router: ModelRouter,
        retrieval_service: RetrievalBackend,
        operational_service: StatusBackend,
        max_steps: int = 3,
        tool_result_max_chars: int = 2400,
        defense: InjectionDefense | None = None,
        history_service: HistoryBackend | None = None,
        turn_budget_seconds: float = TURN_BUDGET_SECONDS,
        final_reserve_seconds: float = FINAL_RESERVE_SECONDS,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.defense = defense or InjectionDefense(enabled=False)
        self.router = router
        self.retrieval_service = retrieval_service
        self.operational_service = operational_service
        self.history_service = history_service
        self.max_steps = max(1, max_steps)
        self.tool_result_max_chars = max(200, tool_result_max_chars)
        self.turn_budget_seconds = max(1.0, float(turn_budget_seconds))
        self.final_reserve_seconds = min(max(0.0, float(final_reserve_seconds)), self.turn_budget_seconds)
        self.clock = clock

    def _out_of_time_reply(self) -> str:
        return f"Mình chưa trả lời kịp trong {round(self.turn_budget_seconds)} giây. Bạn hỏi lại, hoặc hỏi hẹp hơn nhé."

    def run(
        self,
        messages: list[dict[str, Any]],
        tool_context: dict[str, Any] | None = None,
    ) -> tuple[str, str, list[dict[str, object]]]:
        """Run the loop on caller-built messages; returns (answer, model, steps).

        `messages` arrives exactly as the plain-chat path would send it
        (persona system prompt, optional context blocks, history, user turn);
        the agent only adds its tool guidance and the tool traffic.
        """
        working: list[dict[str, Any]] = list(messages)
        guide = {"role": "system", "content": self.defense.agent_guide(AGENT_GUIDE)}
        insert_at = 1 if working and working[0].get("role") == "system" else 0
        working.insert(insert_at, guide)

        steps: list[dict[str, object]] = []
        model_used = ""
        turn_started = self.clock()
        stop_reason = STOP_MAX_STEPS
        # Token counts per model call, for the trace: the usage ContextVar keeps only the
        # last call, so it is read after every one. `last` is put back at the end, so the
        # caller's request log keeps reading the last call as it always has (ticket 16, k2).
        consume_usage()
        last: dict[str, int | None] = {"tokens_in": None, "tokens_out": None}
        for _ in range(self.max_steps):
            left = self.turn_budget_seconds - (self.clock() - turn_started)
            # A tool round must leave the final answer its reserve: started any later,
            # it would spend the time the answer needs.
            if left < self.final_reserve_seconds or left <= 0:
                stop_reason = STOP_TURN_BUDGET
                break
            started = perf_counter()
            try:
                with call_within(left - self.final_reserve_seconds):
                    result, model_used = self.router.chat_tools("general", working, AGENT_TOOLS)
            except ModelCallTimeoutError:
                # The round ran into the reserve's edge: answer from what is gathered.
                consume_usage()
                stop_reason = STOP_TURN_BUDGET
                break
            round_latency = int((perf_counter() - started) * 1000)
            last = consume_usage()
            calls = result["tool_calls"]
            if not calls:
                steps.append({
                    "kind": "final", "tool_name": None, "arguments": None,
                    "content": _clip(result["content"], 4000), "latency_ms": round_latency,
                    "stop_reason": STOP_FINAL, **last,
                })
                record_usage(last["tokens_in"], last["tokens_out"])
                return result["content"], model_used, steps
            # The model must see its own calls on the next round, verbatim.
            working.append({"role": "assistant", "content": result["content"], "tool_calls": result["raw_tool_calls"]})
            for index, call in enumerate(calls):
                # A name the model invented can carry the user's words: the content-free
                # trace keeps a tool's name only when the step says it is a declared one.
                declared = call["name"] in TOOL_NAMES
                steps.append({
                    "kind": "tool_call", "tool_name": call["name"], "tool_declared": declared,
                    "arguments": call["arguments"], "content": None, "latency_ms": round_latency,
                    "arguments_shape": arguments_shape(call["name"], call["arguments"]),
                    # One model round, however many calls it made: counted once.
                    **(last if index == 0 else {"tokens_in": None, "tokens_out": None}),
                })
                tool_started = perf_counter()
                text, error_code, error_type = self._run_tool(call["name"], call["arguments"], tool_context)
                # D5: tool output is untrusted data (document chunks, memory
                # text); the defense marks it so before the model reads it.
                output = self.defense.wrap_tool_result(text)
                steps.append({
                    "kind": "tool_result", "tool_name": call["name"], "tool_declared": declared, "arguments": None,
                    "content": output, "latency_ms": int((perf_counter() - tool_started) * 1000),
                    "error_code": error_code, "error_type": error_type,
                })
                working.append({"role": "tool", "tool_name": call["name"], "content": output})

        # Out of tool rounds or out of time: force a plain answer from what was
        # gathered — the structured stop that keeps the work done, not an exception
        # that throws it away (the Claude SDK / smolagents / Inspect family).
        working.append({
            "role": "system",
            "content": (
                "Đã dùng tối đa số lượt công cụ. Trả lời ngay bằng những gì đã thu thập được."
                if stop_reason == STOP_MAX_STEPS
                else "Hết thời gian dùng công cụ. Trả lời ngay bằng những gì đã thu thập được."
            ),
        })
        started = perf_counter()
        left = self.turn_budget_seconds - (self.clock() - turn_started)
        usage: dict[str, int | None] = {"tokens_in": None, "tokens_out": None}
        try:
            if left <= 0:
                raise ModelCallTimeoutError("no time left for the final answer")
            with call_within(left):
                answer, model_used = self.router.chat("general", working)
            usage = last = consume_usage()
        except ModelCallTimeoutError:
            # Only running out of time ends here: an unreachable or broken model still
            # raises as before, because "not in time" would then be a false reply.
            consume_usage()
            answer, stop_reason = self._out_of_time_reply(), STOP_TURN_BUDGET_EXHAUSTED
        steps.append({
            "kind": "final", "tool_name": None, "arguments": None,
            "content": _clip(answer, 4000), "latency_ms": int((perf_counter() - started) * 1000),
            "stop_reason": stop_reason, **usage,
        })
        record_usage(last["tokens_in"], last["tokens_out"])
        return answer, model_used, steps

    def _execute_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        tool_context: dict[str, Any] | None = None,
    ) -> str:
        """The text the model reads for one call (see _run_tool)."""
        return self._run_tool(name, arguments, tool_context)[0]

    def _error(self, code: str, message: str, error_type: str | None = None) -> tuple[str, str, str | None]:
        return self._dump({"error": message, "code": code}), code, error_type

    def _run_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        tool_context: dict[str, Any] | None = None,
    ) -> ToolOutput:
        """Dispatch one call -> (text for the model, error code, exception type).

        Errors become data the model can react to — a broken tool must never
        kill the whole answer. The exception's class goes to the trace only: the
        model gets a sentence saying what to do next, not "TypeError: ..."."""
        try:
            tool = REGISTRY.get(name) if isinstance(name, str) else None
            if tool is None:
                return self._error(UNKNOWN_TOOL, f"Không có công cụ {name}. Chỉ có {', '.join(TOOL_NAMES)}.")
            return tool.run(self, arguments, tool_context)
        except Exception as error:
            return self._error(
                TOOL_FAILED,
                f"{name} đang lỗi nên chưa tra được. Đừng gọi lại trong lượt này; nói với người dùng là chưa tra được.",
                type(error).__name__,
            )

    def _search_history(self, arguments: dict[str, Any], tool_context: dict[str, Any] | None) -> ToolOutput:
        # The guild comes from the CALLER (the turn service knows the
        # session's guild), never from the model — the same isolation
        # lesson as the ledger read (memory_design.md §3.1).
        guild_id = str((tool_context or {}).get("guild_id") or "")
        if self.history_service is None or not guild_id:
            # Asked on the web, the model used to ask back "which server?"
            # (Agent Eval hist-10): say plainly there is no history here.
            return self._error(
                TOOL_UNAVAILABLE_HERE,
                "search_history chỉ đọc được lịch sử của server Discord đang trò chuyện; "
                "cuộc trò chuyện này không ở Discord. Đừng hỏi người dùng server nào: nói rõ "
                "ở đây không xem được tin nhắn Discord, rồi trả lời phần còn lại.",
            )
        query = str(arguments.get("query") or "").strip()
        author_id = str(arguments.get("author_id") or "").strip() or None
        if not query:
            # No query = the latest messages in time order — the
            # "tóm tắt N tin gần nhất" read over the raw ledger.
            try:
                limit = int(arguments.get("limit", 20))
            except (TypeError, ValueError):
                limit = 20
            hits = self.history_service.recent(
                guild_id=guild_id,
                limit=min(max(limit, 1), 25),
                author_id=author_id,
            )
            if not hits:
                return self._dump(
                    {"result": "sổ gốc chưa có tin nhắn nào của server này"}
                ), None, None
            # Chronological, so an overflow must give up the OLDEST
            # messages: they are the ones a "latest N" read cares least about.
            return self._dump([_history_item(hit) for hit in hits], drop="first"), None, None
        try:
            limit = int(arguments.get("limit", 5))
        except (TypeError, ValueError):
            limit = 5
        days = arguments.get("days")
        try:
            days = min(int(days), 3650) if days is not None else None
        except (TypeError, ValueError):
            days = None
        hits = self.history_service.search(
            guild_id=guild_id,
            query=query,
            author_id=author_id,
            days=days,
            limit=min(max(limit, 1), 10),
        )
        if not hits:
            return self._dump(
                {"result": "không tìm thấy tin nhắn cũ nào khớp"}
            ), None, None
        return self._dump([_history_item(hit) for hit in hits]), None, None

    def _search_documents(self, arguments: dict[str, Any], tool_context: dict[str, Any] | None) -> ToolOutput:
        query = str(arguments.get("query") or "").strip()
        if not query:
            return self._error(
                BAD_ARGUMENTS,
                "search_documents cần `query` là một câu không rỗng. Gọi lại một lần, "
                "viết câu hỏi thành câu độc lập.",
            )
        try:
            top_k = int(arguments.get("top_k", 4))
        except (TypeError, ValueError):
            top_k = 4
        chunks = self.retrieval_service.retrieve(query, min(max(top_k, 1), 8), None)
        if not chunks:
            return self._dump({"result": "không tìm thấy đoạn tài liệu nào phù hợp"}), None, None
        return self._dump([
            {
                "filename": chunk.get("filename"),
                "page": chunk.get("page"),
                "excerpt": _clip(str(chunk.get("content") or ""), 400),
                "score": round(float(chunk.get("score") or 0.0), 3),
            }
            for chunk in chunks
        ]), None, None

    def _system_status(self, arguments: dict[str, Any], tool_context: dict[str, Any] | None) -> ToolOutput:
        return self._dump(self.operational_service.health()), None, None

    def _dump(self, payload: object, *, drop: str = "last") -> str:
        """JSON for the model, at most tool_result_max_chars.

        A list that does not fit loses WHOLE items and says how many, never
        half of one. A plain character cut left broken JSON on every top_k=5
        search, and on the chronological "latest N" history read it cut exactly
        the newest messages (Agent Eval baseline v0.1, hist-05: 8 of 18 gone).
        `drop="last"` gives up the end of a ranked list; `drop="first"` the
        front of a chronological one. Anything else, or a list whose single
        item is already too long, falls back to the character cut.

        Only an overflow changes the shape, to {"omitted", "note", "items"}:
        a note placed INSIDE the list could be counted as one more message
        when the model is asked to summarise N of them (review 27/10)."""
        text = json.dumps(payload, ensure_ascii=False, default=str)
        limit = self.tool_result_max_chars
        if len(text) <= limit or not isinstance(payload, list):
            return _clip(text, limit)
        items = list(payload)
        while len(items) > 1:
            items = items[1:] if drop == "first" else items[:-1]
            omitted = len(payload) - len(items)
            fitted = json.dumps(
                {
                    "omitted": omitted,
                    "note": f"đã bỏ {omitted} mục {'cũ nhất' if drop == 'first' else 'xếp cuối'} để vừa giới hạn kết quả công cụ",
                    "items": items,
                },
                ensure_ascii=False,
                default=str,
            )
            if len(fitted) <= limit:
                return fitted
        return _clip(text, limit)


# The registry (ticket 20, option b): one entry per tool, in the order the model is shown
# them. AGENT_TOOLS, TOOL_NAMES and _DECLARED are read off it, so a tool cannot be declared
# without a handler, nor run without being declared.
REGISTRY: dict[str, AgentTool] = {tool.name: tool for tool in (
    AgentTool(SEARCH_DOCUMENTS_SCHEMA, AgentService._search_documents),
    AgentTool(SEARCH_HISTORY_SCHEMA, AgentService._search_history),
    AgentTool(SYSTEM_STATUS_SCHEMA, AgentService._system_status),
)}
AGENT_TOOLS: list[dict[str, Any]] = [tool.schema for tool in REGISTRY.values()]
TOOL_NAMES = tuple(REGISTRY)
_DECLARED = {tool.name: tool.schema["function"]["parameters"].get("properties", {}) for tool in REGISTRY.values()}
