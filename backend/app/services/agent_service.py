"""Agent loop for chat (P2-2): plan → act → observe over existing services.

The agent is not a new framework — it is one bounded loop that lets the
general model call in-house tools through Ollama's native function-calling API, then
answer: the core's own (searching and reading documents, system health) and any a package
plugs into its ToolRegistry (app.discord's search over the Discord history). The
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
from app.services.answer_figures import grounding_summary, retry_instruction, turn_texts, unsupported_figures
from app.services.pastes import read_paste, search_pastes, take_pastes
from app.services.injection_defense import InjectionDefense
from app.services.model_router import ModelRouter


class RetrievalBackend(Protocol):
    def retrieve(self, query: str, top_k: int, document_id: str | list[str] | None = None) -> list[dict[str, object]]: ...


class StatusBackend(Protocol):
    def health(self) -> dict[str, object]: ...


class DocumentReader(Protocol):
    """Consecutive chunks of a document's active version, whole (read_document, ticket 20 #1):
    {"document_id", "filename", "total_chunks", "chunks": [{"chunk_index", "page_start",
    "page_end", "content"}]}, or None when the document has no active indexed version."""

    def read_chunks(self, document_id: str, from_chunk: int, n: int) -> dict[str, object] | None: ...

    def chunks_on_page(self, document_id: str, page: int, n: int) -> dict[str, object] | None: ...


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

# A search shows the first SEARCH_EXCERPT_CHARS of each chunk; read_document returns
# chunks whole up to READ_CHUNK_MAX_CHARS each, READ_RESULT_MAX_CHARS in all (ticket 20
# #1, L2). Measured on the v0.2 lab retrieval: chunks run 1 680 characters at the median
# and 2 429 at most, so the old 400 showed about a quarter of one. At ~2.9 characters a
# token, three reads of 6 000 are ~6.2k tokens: with the prompt, half of the 16k window.
SEARCH_EXCERPT_CHARS = 400
READ_CHUNK_MAX_CHARS = 2400
READ_RESULT_MAX_CHARS = 6000
READ_MAX_CHUNKS = 3

SEARCH_DOCUMENTS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_documents",
        "description": f"Tìm các đoạn liên quan trong tài liệu đã index (PDF, DOCX, ...). Trả về tên tệp, trang, {SEARCH_EXCERPT_CHARS} ký tự đầu của mỗi đoạn (excerpt), độ dài cả đoạn (chars), và document_id + chunk_index để đọc trọn đoạn bằng read_document.",
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
READ_DOCUMENT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "read_document",
        "description": f"Đọc trọn nguyên văn các đoạn liên tiếp của một tài liệu mà search_documents vừa tìm thấy, khi {SEARCH_EXCERPT_CHARS} ký tự đầu chưa đủ để trả lời. Dùng document_id và chunk_index trong kết quả search_documents. Trả về các đoạn kèm next_from_chunk: muốn đọc tiếp thì gọi lại với from_chunk bằng số đó (null = đã hết tài liệu).",
        "parameters": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string", "description": "document_id trong kết quả search_documents"},
                "from_chunk": {"type": "integer", "description": "Đọc từ đoạn này (chunk_index trong kết quả search_documents), mặc định 0"},
                "n": {"type": "integer", "description": f"Số đoạn liên tiếp muốn đọc (1-{READ_MAX_CHUNKS}), mặc định 2"},
                "page": {"type": "integer", "description": "Tùy chọn: đọc các đoạn nằm ở trang này thay cho from_chunk (chỉ tài liệu có số trang, như PDF)"},
            },
            "required": ["document_id"],
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
# One sentence for an id that does not exist and for one this turn may not open, so
# read_document never tells the model which document ids exist.
NOT_READABLE = (
    "document_id này không có trong kết quả search_documents của lượt này. Dùng đúng "
    "document_id trong kết quả tra; chưa tra thì gọi search_documents trước."
)

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
# The answer check (ticket 20 #2, app/services/answer_figures.py). An answer whose figures
# the turn saw nowhere gets one retry, in one extra round with tools, while the final
# reserve is still free; the rejected attempt is an ANSWER_CHECK_STEP that keeps no text.
ANSWER_CHECK = True
ANSWER_CHECK_STEP = "answer_check"
UNSUPPORTED_FIGURES = "UNSUPPORTED_FIGURES"
# What a watching client is told while a turn runs (ticket 20 #4). A tool brings its own
# label (AgentTool.label); TOOL_LABEL stands in for one without, or a name never declared.
THINKING_LABEL = "Đang suy nghĩ…"
REVIEWING_LABEL = "Đang xem lại những gì đã tra…"
TOOL_LABEL = "Đang dùng công cụ…"
ANSWER_CHECK_LABEL = "Đang kiểm lại các con số trong câu trả lời…"
ANSWERING_LABEL = "Đang viết câu trả lời…"


# What a handler returns: (text for the model, error code, exception type).
ToolOutput = tuple[str, str | None, str | None]


@dataclass(frozen=True)
class AgentTool:
    """One tool in the registry: what the model is shown, what runs when it calls it, and
    what a watching client is told while it runs (ticket 20 #4: a kind of work, no content)."""

    schema: dict[str, Any]
    run: Callable[["AgentService", dict[str, Any], dict[str, Any] | None], ToolOutput]
    label: str | None = None

    @property
    def name(self) -> str:
        return str(self.schema["function"]["name"])


class ToolRegistry:
    """The tools one AgentService offers, in the order the model is shown them (ticket 22,
    C4). The core registers its own (core_tools); a package plugs its tools in with
    register(tool, order) — app.discord registers search_history at startup. Everything
    read off it (the schemas sent to the model, the names, the declared keys the trace
    shapes arguments by) is computed on each call, so a late registration is never missed."""

    def __init__(self) -> None:
        self._tools: dict[str, tuple[int, AgentTool]] = {}

    def register(self, tool: AgentTool, order: int) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} is already registered")
        self._tools[tool.name] = (order, tool)

    def get(self, name: object) -> AgentTool | None:
        entry = self._tools.get(name) if isinstance(name, str) else None
        return entry[1] if entry else None

    def tools(self) -> list[AgentTool]:
        return [tool for _, tool in sorted(self._tools.values(), key=lambda entry: (entry[0], entry[1].name))]

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema for tool in self.tools()]

    def names(self) -> tuple[str, ...]:
        return tuple(tool.name for tool in self.tools())

    def declared(self) -> dict[str, dict[str, Any]]:
        return {tool.name: tool.schema["function"]["parameters"].get("properties", {}) for tool in self.tools()}


def arguments_shape(tool_name: object, arguments: object, declared_by_tool: dict[str, dict[str, Any]]) -> dict[str, object] | None:
    """A tool call's arguments with the content taken out, for the trace that outlives
    the conversation (ticket 16, option b): a declared string becomes "str:<length>", a
    declared integer stays a number, anything else its type name. Keys the tool does not
    declare are only counted — a model can invent a key, and a key can carry words.
    `declared_by_tool` is the running agent's ToolRegistry.declared()."""
    if not isinstance(arguments, dict):
        return None
    declared = declared_by_tool.get(str(tool_name), {})
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


def _bounded(value: object, default: int, low: int, high: int | None = None) -> int:
    """A model-supplied whole number, clamped; anything unreadable is the default."""
    try:
        number = default if value is None else int(value)
    except (TypeError, ValueError):
        number = default
    number = max(number, low)
    return number if high is None else min(number, high)


class AgentService:
    def __init__(
        self,
        router: ModelRouter,
        retrieval_service: RetrievalBackend,
        operational_service: StatusBackend,
        max_steps: int = 3,
        tool_result_max_chars: int = 2400,
        defense: InjectionDefense | None = None,
        turn_budget_seconds: float = TURN_BUDGET_SECONDS,
        final_reserve_seconds: float = FINAL_RESERVE_SECONDS,
        clock: Callable[[], float] = monotonic,
        document_reader: DocumentReader | None = None,
        read_result_max_chars: int = READ_RESULT_MAX_CHARS,
        registry: ToolRegistry | None = None,
    ) -> None:
        self.defense = defense or InjectionDefense(enabled=False)
        self.router = router
        self.retrieval_service = retrieval_service
        self.operational_service = operational_service
        # Its own registry unless one is handed in: a tool registered into one agent (a
        # test's, the eval's) never shows up in another.
        self.registry = registry if registry is not None else core_tools()
        self.document_reader = document_reader
        self.max_steps = max(1, max_steps)
        self.tool_result_max_chars = max(200, tool_result_max_chars)
        self.read_result_max_chars = max(200, read_result_max_chars)
        self.turn_budget_seconds = max(1.0, float(turn_budget_seconds))
        self.final_reserve_seconds = min(max(0.0, float(final_reserve_seconds)), self.turn_budget_seconds)
        self.clock = clock

    def _out_of_time_reply(self) -> str:
        return f"Mình chưa trả lời kịp trong {round(self.turn_budget_seconds)} giây. Bạn hỏi lại, hoặc hỏi hẹp hơn nhé."

    def run(
        self,
        messages: list[dict[str, Any]],
        tool_context: dict[str, Any] | None = None,
        on_step: Callable[[dict[str, object]], None] | None = None,
    ) -> tuple[str, str, list[dict[str, object]]]:
        """Run the loop on caller-built messages; returns (answer, model, steps).

        `messages` arrives exactly as the plain-chat path would send it
        (persona system prompt, optional context blocks, history, user turn);
        the agent only adds its tool guidance and the tool traffic.

        `on_step`, when given, hears what the turn is doing while it runs (ticket 20 #4):
        {"kind", "round", "label", ...} with a kind of work and counts, never an argument,
        a result or an answer. It is called on the turn's own thread, and a listener that
        raises is ignored: showing progress must never cost the answer.
        """
        round_index = 0

        def emit(kind: str, **fields: object) -> None:
            if on_step is None:
                return
            try:
                on_step({"kind": kind, "round": round_index, **fields})
            except Exception:
                pass

        # A paste longer than PASTE_THRESHOLD reaches the model as a slip, and is read
        # through read_document from this turn's own pastes (ticket 20 #3).
        working, pastes = take_pastes(list(messages))
        guide = {"role": "system", "content": self.defense.agent_guide(AGENT_GUIDE)}
        insert_at = 1 if working and working[0].get("role") == "system" else 0
        working.insert(insert_at, guide)
        # The turn's own copy, so the caller's dict is never written to. It carries what
        # read_document may open: a document search_documents showed in THIS turn, one the
        # caller allows outright (ticket 20 #1, A2), or a paste in this turn's messages —
        # whose text comes from those messages only, never from the caller.
        tool_context = {
            **(tool_context or {}),
            "readable_documents": set((tool_context or {}).get("readable_documents") or ()) | set(pastes),
            "pastes": pastes,
        }

        steps: list[dict[str, object]] = []
        model_used = ""
        turn_started = self.clock()
        stop_reason = STOP_MAX_STEPS
        # Token counts per model call, for the trace: the usage ContextVar keeps only the
        # last call, so it is read after every one. `last` is put back at the end, so the
        # caller's request log keeps reading the last call as it always has (ticket 16, k2).
        consume_usage()
        last: dict[str, int | None] = {"tokens_in": None, "tokens_out": None}
        # The answer check (ticket 20 #2) may grant one more round, for its single retry;
        # `checked_out` are the messages it added, which never count as something seen.
        rounds, retried = self.max_steps, False
        checked_out: set[int] = set()
        while round_index < rounds:
            round_index += 1
            left = self.turn_budget_seconds - (self.clock() - turn_started)
            # A tool round must leave the final answer its reserve: started any later,
            # it would spend the time the answer needs.
            if left < self.final_reserve_seconds or left <= 0:
                stop_reason = STOP_TURN_BUDGET
                break
            emit("thinking", label=THINKING_LABEL if round_index == 1 else REVIEWING_LABEL)
            started = perf_counter()
            try:
                with call_within(left - self.final_reserve_seconds):
                    result, model_used = self.router.chat_tools("general", working, self.registry.schemas())
            except ModelCallTimeoutError:
                # The round ran into the reserve's edge: answer from what is gathered.
                consume_usage()
                stop_reason = STOP_TURN_BUDGET
                break
            round_latency = int((perf_counter() - started) * 1000)
            last = consume_usage()
            calls = result["tool_calls"]
            if not calls:
                answer = result["content"]
                check = self._check_answer(answer, working, checked_out)
                left = self.turn_budget_seconds - (self.clock() - turn_started)
                if check["unsupported"] and not retried and left >= self.final_reserve_seconds:
                    # Figures the turn saw nowhere (ticket 20 #2, T1): one retry, with tools,
                    # in a round of its own. The rejected answer reached no one, so the trace
                    # keeps only how many figures it had, not its text.
                    steps.append({
                        "kind": ANSWER_CHECK_STEP, "tool_name": None, "arguments": None, "content": None,
                        "latency_ms": round_latency, "error_code": UNSUPPORTED_FIGURES,
                        "arguments_shape": {"unsupported_figures": len(check["unsupported"])}, **last,
                    })
                    checked_out.update((len(working), len(working) + 1))
                    working.append({"role": "assistant", "content": answer})
                    working.append({"role": "system", "content": retry_instruction(check["unsupported"])})
                    retried, rounds = True, rounds + 1
                    emit("answer_check", label=ANSWER_CHECK_LABEL)
                    continue
                steps.append({
                    "kind": "final", "tool_name": None, "arguments": None,
                    "content": _clip(answer, 4000), "latency_ms": round_latency,
                    "stop_reason": STOP_FINAL, **check["trace"], **last,
                })
                record_usage(last["tokens_in"], last["tokens_out"])
                emit("final", stop_reason=STOP_FINAL)
                return answer, model_used, steps
            # The model must see its own calls on the next round, verbatim.
            working.append({"role": "assistant", "content": result["content"], "tool_calls": result["raw_tool_calls"]})
            for index, call in enumerate(calls):
                # A name the model invented can carry the user's words: the content-free
                # trace keeps a tool's name only when the step says it is a declared one.
                tool = self.registry.get(call["name"])
                declared = tool is not None
                steps.append({
                    "kind": "tool_call", "tool_name": call["name"], "tool_declared": declared,
                    "arguments": call["arguments"], "content": None, "latency_ms": round_latency,
                    "arguments_shape": arguments_shape(call["name"], call["arguments"], self.registry.declared()),
                    # One model round, however many calls it made: counted once.
                    **(last if index == 0 else {"tokens_in": None, "tokens_out": None}),
                })
                # An invented tool name can carry the user's words: progress names a tool
                # only when it is a declared one, like the trace.
                emit("tool_call", tool=call["name"] if declared else None, label=(tool.label if tool and tool.label else TOOL_LABEL))
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
                emit("tool_result", tool=call["name"] if declared else None, ok=error_code is None)
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
        emit("answering", label=ANSWERING_LABEL)
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
        # Out of rounds or time, there is no retry left: the check only marks the trace.
        # The fixed out-of-time reply is ours, not the model's, and is not checked.
        check = self._check_answer(answer, working, checked_out) if stop_reason != STOP_TURN_BUDGET_EXHAUSTED else {"trace": {}}
        steps.append({
            "kind": "final", "tool_name": None, "arguments": None,
            "content": _clip(answer, 4000), "latency_ms": int((perf_counter() - started) * 1000),
            "stop_reason": stop_reason, **check["trace"], **usage,
        })
        record_usage(last["tokens_in"], last["tokens_out"])
        emit("final", stop_reason=stop_reason)
        return answer, model_used, steps

    @staticmethod
    def _check_answer(answer: str, working: list[dict[str, Any]], checked_out: set[int]) -> dict[str, Any]:
        """The answer check (ticket 20 #2): its figures against what the turn saw (K3, the
        gate), and answer_grounding's verdict on the tool results (K1, recorded only). The
        trace gets labels and counts, never text, in the final step's arguments_shape."""
        if not ANSWER_CHECK:
            return {"unsupported": [], "trace": {}}
        shown, tool_results = turn_texts(working, checked_out)
        unsupported = unsupported_figures(answer, shown)
        shape: dict[str, object] = {"unsupported_figures": len(unsupported), **(grounding_summary(answer, tool_results) or {})}
        trace: dict[str, object] = {"arguments_shape": shape}
        if unsupported:
            trace["error_code"] = UNSUPPORTED_FIGURES
        return {"unsupported": unsupported, "trace": trace}

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
            tool = self.registry.get(name)
            if tool is None:
                return self._error(UNKNOWN_TOOL, f"Không có công cụ {name}. Chỉ có {', '.join(self.registry.names())}.")
            return tool.run(self, arguments, tool_context)
        except Exception as error:
            return self._error(
                TOOL_FAILED,
                f"{name} đang lỗi nên chưa tra được. Đừng gọi lại trong lượt này; nói với người dùng là chưa tra được.",
                type(error).__name__,
            )

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
        size = min(max(top_k, 1), 8)
        # This turn's pastes first, then the library (ticket 20 #3-D, 3'): merged here, so no
        # RetrievalBackend (the eval's ReplayRetrieval included) learns about pastes. A paste
        # is already readable (run() adds every paste id), has no pages, and gets no score:
        # BM25's is not on the scale of the library's.
        in_pastes = search_pastes((tool_context or {}).get("pastes") or {}, query, size)
        chunks = self.retrieval_service.retrieve(query, size, None)
        if not chunks and not in_pastes:
            return self._dump({"result": "không tìm thấy đoạn tài liệu nào phù hợp"}), None, None
        items: list[dict[str, object]] = []
        for chunk in in_pastes:
            content = str(chunk["content"])
            items.append({
                "filename": chunk["filename"],
                "document_id": chunk["document_id"],
                "chunk_index": chunk["chunk_index"],
                "excerpt": _clip(content, SEARCH_EXCERPT_CHARS),
                "chars": len(content),
                "read": f'đọc trọn đoạn này bằng read_document(document_id="{chunk["document_id"]}", from_chunk={chunk["chunk_index"]}, n={READ_MAX_CHUNKS})',
            })
        readable = (tool_context or {}).get("readable_documents")
        for chunk in chunks:
            content = str(chunk.get("content") or "")
            item: dict[str, object] = {"filename": chunk.get("filename"), "page": chunk.get("page")}
            # The handle read_document takes (ticket 20 #1, H1). A chunk without a document
            # behind it (a hand-written eval fixture) gets none: it cannot be read further.
            if chunk.get("document_id"):
                item["document_id"] = str(chunk["document_id"])
                item["chunk_index"] = chunk.get("chunk_index")
                if isinstance(readable, set):
                    readable.add(item["document_id"])
            item["excerpt"] = _clip(content, SEARCH_EXCERPT_CHARS)
            # How long the whole chunk is, so the model knows the excerpt stopped short.
            item["chars"] = len(content)
            item["score"] = round(float(chunk.get("score") or 0.0), 3)
            items.append(item)
        return self._dump(items), None, None

    def _read_document(self, arguments: dict[str, Any], tool_context: dict[str, Any] | None) -> ToolOutput:
        document_id = str(arguments.get("document_id") or "").strip()
        pastes = (tool_context or {}).get("pastes") or {}
        if document_id not in pastes and self.document_reader is None:
            return self._error(
                TOOL_UNAVAILABLE_HERE,
                "read_document chưa dùng được ở đây; trả lời bằng các trích đoạn search_documents đã cho.",
            )
        if not document_id or document_id not in (tool_context or {}).get("readable_documents", ()):
            return self._error(BAD_ARGUMENTS, NOT_READABLE)
        n = _bounded(arguments.get("n"), 2, 1, READ_MAX_CHUNKS)
        page = _bounded(arguments.get("page"), 0, 0)
        if document_id in pastes:
            # This turn's paste (ticket 20 #3): its text is in the turn's own context, so
            # the document store is never asked about an id it could not have.
            found = read_paste(document_id, pastes[document_id], _bounded(arguments.get("from_chunk"), 0, 0), n, page)
        elif page:
            # A page, when given, wins over from_chunk: a model that sends both by habit
            # should not lose a round to an error.
            found = self.document_reader.chunks_on_page(document_id, page, n)
        else:
            found = self.document_reader.read_chunks(document_id, _bounded(arguments.get("from_chunk"), 0, 0), n)
        if found is None:
            return self._error(BAD_ARGUMENTS, NOT_READABLE)
        total = int(found.get("total_chunks") or 0)
        if not found.get("chunks"):
            if page:
                return self._dump({
                    "result": f"không có đoạn nào ở trang {page} (tài liệu ngắn hơn, hoặc không chia trang); đọc theo from_chunk",
                    "total_chunks": total,
                }), None, None
            return self._dump({"result": "đã hết tài liệu", "total_chunks": total}), None, None
        return self._fit_chunks(found, total), None, None

    def _fit_chunks(self, found: dict[str, object], total: int) -> str:
        """As many whole chunks as fit read_result_max_chars, with next_from_chunk at the
        first one left out. Fitted here, where each chunk's length is known: _dump drops
        items only from a list, and could not say where the reading goes on."""
        shown = [
            {
                "chunk_index": chunk.get("chunk_index"),
                "page_start": chunk.get("page_start"),
                "page_end": chunk.get("page_end"),
                "content": _clip(str(chunk.get("content") or ""), READ_CHUNK_MAX_CHARS),
            }
            for chunk in found["chunks"]  # type: ignore[union-attr]
        ]

        def text(count: int) -> str:
            last = shown[count - 1]["chunk_index"]
            following = last + 1 if isinstance(last, int) and last + 1 < total else None
            return json.dumps({
                "document_id": found.get("document_id"),
                "filename": found.get("filename"),
                "total_chunks": total,
                "chunks": shown[:count],
                "next_from_chunk": following,
            }, ensure_ascii=False, default=str)

        limit = self.read_result_max_chars
        count = len(shown)
        while count > 1 and len(text(count)) > limit:
            count -= 1
        # One chunk alone over a cap set below a chunk's size: shorten it rather than
        # cut the JSON, so the model still reads valid JSON and a next_from_chunk.
        while len(text(1)) > limit and len(shown[0]["content"]) > 1 and count == 1:
            excess = len(text(1)) - limit
            shown[0]["content"] = _clip(shown[0]["content"], max(1, len(shown[0]["content"]) - excess))
        return self._dump(json.loads(text(count)), limit=limit)

    def _system_status(self, arguments: dict[str, Any], tool_context: dict[str, Any] | None) -> ToolOutput:
        return self._dump(self.operational_service.health()), None, None

    def _dump(self, payload: object, *, drop: str = "last", limit: int | None = None) -> str:
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
        limit = self.tool_result_max_chars if limit is None else limit
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


# Where the core's tools stand (ticket 22, C4). The gap at 20 is app.discord's
# search_history (app/discord/agent_tools.py ORDER): with it registered, the model is
# shown the same four tools in the same order as before the move.
SEARCH_DOCUMENTS_ORDER, READ_DOCUMENT_ORDER, SYSTEM_STATUS_ORDER = 10, 15, 30


def core_tools() -> ToolRegistry:
    """A fresh registry holding the core's own tools (ticket 20, option b; ticket 22, C4):
    each tool is a schema and the handler that runs it, so none can be declared without a
    handler, nor run without being declared."""
    registry = ToolRegistry()
    registry.register(AgentTool(SEARCH_DOCUMENTS_SCHEMA, AgentService._search_documents, "Đang tra tài liệu…"), SEARCH_DOCUMENTS_ORDER)
    registry.register(AgentTool(READ_DOCUMENT_SCHEMA, AgentService._read_document, "Đang đọc tài liệu…"), READ_DOCUMENT_ORDER)
    registry.register(AgentTool(SYSTEM_STATUS_SCHEMA, AgentService._system_status, "Đang xem trạng thái hệ thống…"), SYSTEM_STATUS_ORDER)
    return registry
