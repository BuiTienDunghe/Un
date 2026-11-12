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
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import monotonic, perf_counter
from typing import Any, Protocol

from app.llm_clients.deadline import ModelCallTimeoutError, call_within
from app.llm_clients.ollama_client import OllamaToolCallParseError
from app.llm_clients.usage import consume_usage, record_usage
from app.services.approvals import (
    APPROVAL_PENDING, APPROVAL_REQUIRED, APPROVAL_UNAVAILABLE, STOP_AWAITING_APPROVAL, ApprovalError, ApprovalGate, ApprovalNotice,
)
from app.services.calculator import CalculationError, calculate
from app.services.call_budget import agent_call_cap, turn_call_budget
from app.services.context_budget import ContextBudget, ContextWindow
from app.services.answer_figures import grounding_summary, retry_instruction, turn_texts, unsupported_figures
from app.services.document_reading import READ_REST_STEP, documents_left_unread, note_read, read_rest
from app.services.long_input import read_long_input
from app.services.pastes import INLINE_MAX_TOKENS, is_paste, read_paste, take_pastes
from app.services.injection_defense import InjectionDefense
from app.services.model_router import ModelRouter
from app.services.tool_state import ToolStateRecorder


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
    "thống, `current_time` xem ngày giờ hiện tại, `calculate` tính phép tính chính xác (có phép tính thì dùng công cụ này, đừng tự nhẩm). Chỉ gọi công cụ khi câu hỏi thật sự "
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
CURRENT_TIME_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "current_time",
        "description": "Đọc ngày giờ hiện tại theo giờ Việt Nam. Dùng khi câu hỏi cần biết hôm nay, bây giờ, thứ mấy, hoặc cần tính khoảng thời gian tới hiện tại.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}
CALCULATE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "calculate",
        "description": "Tính chính xác một biểu thức số học. Dùng cho mọi phép tính có từ hai bước trở lên, tiền, phần trăm, chia trung bình. Ví dụ tăng 7,5% trên 14.500.000: 14500000 * 1.075. Không dùng cho ngày tháng.",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Biểu thức chỉ gồm số, + - * / // % ** và dấu ngoặc; số viết liền, phần thập phân dùng dấu chấm: 1250000 * 0.15"},
            },
            "required": ["expression"],
        },
    },
}
# Vietnam has one offset and no daylight saving; a fixed one needs no tzdata, which Windows lacks.
VIETNAM_TIME = timezone(timedelta(hours=7))
WEEKDAYS = ("Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật")


def clock_note() -> dict[str, str]:
    """What the clock says, for a turn with no tools to ask it with. Goes just before the new
    message: the time changes every minute, and a line earlier would make Ollama read the whole
    history again each turn."""
    now = datetime.now(VIETNAM_TIME)
    return {"role": "system", "content": f"Bây giờ là {now:%H:%M}, {WEEKDAYS[now.weekday()]}, ngày {now:%d/%m/%Y}, giờ Việt Nam."}


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
# "turn_budget_exhausted" (even the final answer did not fit: the fixed reply below),
# "tool_call_error" (a tool call Ollama could not parse, again after the retry or with no
# time for one: answered from what was gathered). "awaiting_approval" (approvals.py, ticket 46)
# ends a turn on a call kept for a person: the tool has not run, the reply is the gate's.
# "asked_user" (ask_user.py, ticket 46) ends a turn on the one question the model asked for a
# missing fact: the reply is that question.
STOP_FINAL = "final"
STOP_MAX_STEPS = "max_steps"
STOP_TURN_BUDGET = "turn_budget"
STOP_TURN_BUDGET_EXHAUSTED = "turn_budget_exhausted"
STOP_TOOL_CALL_ERROR = "tool_call_error"
STOP_ASKED_USER = "asked_user"
# A tool call the model wrote and Ollama could not parse (ticket 27): one retry with a note,
# in a round of its own, while the final reserve is still free; then the answer without
# tools. Each failed round is a TOOL_CALL_ERROR_STEP that keeps no text.
TOOL_CALL_ERROR_STEP = "tool_call_error"
TOOL_CALL_PARSE = "TOOL_CALL_PARSE"
TOOL_CALL_RETRY = (
    "Lệnh gọi công cụ vừa rồi sai định dạng nên không chạy được. Gọi lại với tham số hợp lệ, "
    "hoặc trả lời thẳng nếu đã đủ thông tin. Không nhắc tới lời nhắc này."
)
# The answer check (ticket 20 #2, app/services/answer_figures.py). An answer whose figures
# the turn saw nowhere gets one retry, in one extra round with tools, while the final
# reserve is still free; the rejected attempt is an ANSWER_CHECK_STEP that keeps no text.
ANSWER_CHECK = True
ANSWER_CHECK_STEP = "answer_check"
UNSUPPORTED_FIGURES = "UNSUPPORTED_FIGURES"
# Where the bot's description of an attached image starts in a message: what follows is not
# the speaker's own writing, so a URL in it is not one the speaker asked to open (ticket 35).
IMAGE_NOTE = "\n\n[Ảnh đính kèm"
# What a watching client is told while a turn runs (ticket 20 #4). A tool brings its own
# label (AgentTool.label); TOOL_LABEL stands in for one without, or a name never declared.
# The lookup check (harness-fix round, 02/11): a turn that called nothing, with a lookup tool
# offered, whose answer says it has no information or needs to search, is sent back once to
# look. doc-25 of Agent Eval v0.8 wrote "tôi cần tìm kiếm trong các tài liệu" and searched none.
# Off unless the caller asks (agent.lookup_check); the rejected attempt is a LOOKUP_CHECK_STEP
# that keeps no text.
LOOKUP_CHECK_STEP = "lookup_check"
LOOKUP_CHECK_LABEL = "Đang tra trước khi trả lời…"
LOOKUP_TOOLS = ("search_documents", "search_history")
# First person only (H3b): the wider pattern also fired on "Bạn cần kiểm tra lại…" and on "…vì không có
# thông tin ngược lại", answers that were fine and, in doc-17, a task that forbids every tool.
LOOKUP_GAVE_UP = re.compile(
    r"\b(?:tôi|mình)\s+(?:(?:không|chưa)\s+(?:có\s+(?:thông tin|dữ liệu)|tìm thấy|tìm được|tra được|biết|rõ)|cần\s+(?:tìm kiếm|tra cứu))",
    re.IGNORECASE,
)
LOOKUP_RETRY = (
    "Bạn chưa gọi công cụ tra nào mà đã nói không có thông tin hoặc cần tìm. Nếu câu hỏi có thể nằm trong tài liệu "
    "đã tải lên hoặc tin nhắn của server thì gọi công cụ tra ngay; tra rồi mà không thấy thì nói rõ là không tìm "
    "thấy. Câu hỏi không cần dữ liệu nội bộ thì trả lời thẳng. Rồi viết câu trả lời như khi trả lời lần đầu: "
    "không xin lỗi, không nhắc tới việc kiểm tra này."
)
# The read-on check (02/11, Agent Eval v0-long.2): a turn that found the right document, saw only
# excerpts or a first few chunks, and answered that the fact is not there or asked whether to read
# on. ctx-03 wrote "Bạn có muốn tôi đọc toàn văn" with the answer two chunks away. Sent back once
# while a document it could open is unread to its end. Off unless the caller asks (agent.read_on_check).
READ_ON_CHECK_STEP = "read_on_check"
READ_ON_CHECK_LABEL = "Đang đọc tiếp tài liệu…"
READ_ON_GAVE_UP = re.compile(
    r"\b(?:chưa|không)\s+(?:thấy|tìm thấy|tìm được|nêu|ghi|chứa|đề cập|nhắc|có\s+(?:thông tin|số liệu|dữ liệu))"
    r"|\b(?:muốn|cần)\s+(?:tôi|mình)\s+đọc|\bcần\s+đọc\s+thêm",
    re.IGNORECASE,
)
READ_ON_RETRY = (
    "Bạn mới xem trích đoạn hoặc đọc một phần tài liệu mà đã nói chưa thấy. Trích đoạn chỉ là phần đầu của mỗi đoạn. "
    "Gọi read_document đọc tiếp các đoạn chưa đọc của những tài liệu liên quan, đừng hỏi người dùng có cần đọc không. "
    "Đọc hết rồi mà không thấy thì nói rõ là tài liệu không có. Rồi viết câu trả lời như khi trả lời lần đầu: "
    "không xin lỗi, không nhắc tới việc kiểm tra này."
)
DOCUMENT_TOOLS = ("search_documents", "read_document")
# The promise check (03/11, Discord): "nhắc mình uống nước 5 phút nữa" was answered "Ún sẽ nhắc lúc
# 13:53" without a remind call, so nothing was scheduled. A tool whose request the code can recognise
# carries `promised`; an answer that skipped it goes back once. On wherever such a tool is registered.
# Said with every forced answer: told only "answer now with what you gathered", the model wrote "không
# có tuyến SFO→CIA" for a route it never asked about (BFCL multi_turn_miss_func_174, 02/11), and the
# later turns believed it.
FORCED_ANSWER_HONESTY = (
    "Chỉ khẳng định điều đã thấy trong kết quả công cụ. Điều chưa tra hoặc việc chưa làm thì nói rõ là chưa tra, "
    "chưa làm; đừng nói là không có, và đừng nói là đã làm."
)
PROMISE_CHECK_STEP = "promise_check"
# What the structured call is told about `requested`, for any tool (agent_service._fill_owed).
PROMISE_REQUESTED = (
    "`requested`: false nếu tin nhắn thật ra không nhờ việc này ngay bây giờ (kể lại, trích lời người khác, hỏi "
    "nghĩa, hỏi hay phàn nàn về chuyện đã qua, cảm ơn, nói chuyện khác) hoặc còn thiếu điều bắt buộc mà người dùng "
    "chưa nói; khi đó mọi trường khác là null."
)
# _fill_owed's answer when the model says the speaker asked for nothing.
DECLINED = object()
PROMISE_CHECK_LABEL = "Đang làm đúng việc được nhờ…"


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    """What the speaker asked this turn, without the note an attached image adds."""
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "").split(IMAGE_NOTE, 1)[0].strip()
    return ""


THINKING_LABEL = "Đang suy nghĩ…"
REVIEWING_LABEL = "Đang xem lại những gì đã tra…"
TOOL_LABEL = "Đang dùng công cụ…"
ANSWER_CHECK_LABEL = "Đang kiểm lại các con số trong câu trả lời…"
TOOL_CALL_ERROR_LABEL = "Đang gọi lại công cụ…"
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
    # Ticket 46: the loop never runs this tool itself; it hands the call to AgentService.approvals,
    # which runs it only after the person it belongs to approves (app/services/approvals.py).
    requires_approval: bool = False
    # Ticket 46: a successful call ends the turn, and the text it returns is the whole reply (ask_user).
    # The turn therefore holds at most one such call; one written after it in the same round is dropped.
    ends_turn: bool = False
    # The promise check (03/11): `promised(tool_context)` says the speaker's own words asked for what only
    # this tool does. An answer that never called it gets one more try: with `promise_fill`, the model
    # is asked for the arguments alone in a structured-output call and the tool runs; without it, or when
    # that call cannot be made, the turn is sent back with `promise_retry`.
    promised: Callable[[dict[str, Any]], bool] | None = None
    promise_retry: str | None = None
    promise_fill: str | None = None
    # Opt-in durable observations. Unknown/MCP tools remain unremembered until
    # an operator-owned registration declares their policy.
    state_policy: str = "none"
    # Laptop agent (12/11/2026): `available(tool_context)` says whether this turn may see the tool at
    # all. False: not offered to the model, and a call by name is answered like an unknown tool. None
    # (every tool before local_files.py): offered everywhere, as before.
    available: Callable[[dict[str, Any]], bool] | None = None

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
        inline_max_tokens: int = INLINE_MAX_TOKENS,
        context_budget: ContextBudget | None = None,
        long_input: bool = False,
        lookup_check: bool = False,
        read_on_check: bool = False,
        read_rest: bool = False,
    ) -> None:
        self.defense = defense or InjectionDefense(enabled=False)
        self.router = router
        self.retrieval_service = retrieval_service
        self.operational_service = operational_service
        # Its own registry unless one is handed in: a tool registered into one agent (a
        # test's, the eval's) never shows up in another.
        self.registry = registry if registry is not None else core_tools()
        # Ticket 46: who keeps a call that requires approval. Set by the composition root only when
        # that is switched on; None offers no such tool to the model and runs none.
        self.approvals: ApprovalGate | None = None
        self.document_reader = document_reader
        self.max_steps = max(1, max_steps)
        self.tool_result_max_chars = max(200, tool_result_max_chars)
        self.read_result_max_chars = max(200, read_result_max_chars)
        # N1's ceiling, from the caller: pastes.inline_ceiling of general's config (ticket 28 #4).
        self.inline_max_tokens = int(inline_max_tokens)
        # Ticket 44: None (the default) sends the conversation exactly as the loop holds it.
        self.context_budget = context_budget
        # Ticket 45: a last-message paste past N1's ceiling is read in parts by the code (long_input.py).
        self.long_input = bool(long_input)
        # Harness-fix round: off by default; the lookup check above.
        self.lookup_check = bool(lookup_check)
        self.read_on_check = bool(read_on_check)
        # The code reads what the model gave up on (document_reading.py). Needs a store to read from.
        self.read_rest = bool(read_rest) and document_reader is not None
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
        """The loop below, with its model calls counted against agent_call_cap (ticket 43)."""
        with turn_call_budget("agent", agent_call_cap(self.max_steps, self.lookup_check, self.read_on_check, self.read_rest, self._promises() != [])):
            return self._run(messages, tool_context, on_step)

    def _run(
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
        working, pastes = take_pastes(list(messages), self.inline_max_tokens)
        guide = {"role": "system", "content": self.defense.agent_guide(AGENT_GUIDE)}
        insert_at = 1 if working and working[0].get("role") == "system" else 0
        working.insert(insert_at, guide)
        protected_state = set()
        for index, row in enumerate(working):
            if row.get("_tool_state_receipt"):
                protected_state.add(index)
                working[index] = {key: value for key, value in row.items() if key != "_tool_state_receipt"}
        # The turn's own copy, so the caller's dict is never written to. It carries what
        # read_document may open: a document search_documents showed in THIS turn, one the
        # caller allows outright (ticket 20 #1, A2), or a paste in this turn's messages —
        # whose text comes from those messages only, never from the caller.
        tool_context = {
            **(tool_context or {}),
            "readable_documents": set((tool_context or {}).get("readable_documents") or ()) | set(pastes),
            # What read_webpage may open: a URL the speaker wrote, and what web_search adds.
            "web_urls": {url.rstrip(".,;:!?)]}") for message in working[-1:] if message.get("role") == "user" for url in re.findall(r"https?://\S+", str(message.get("content") or "").split(IMAGE_NOTE, 1)[0])},
            "pastes": pastes,
            # Which chunks of which document this turn has shown the model, and each one's name.
            "read_state": {},
            "document_names": {},
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
        # What the model is sent each call: `working` itself, or with old tool results cleared (ticket 44).
        window = ContextWindow(self.context_budget, self.inline_max_tokens, protected_results=protected_state)
        # Ticket 45: read the long paste in parts before the first round, under the turn's own clock.
        reading = None
        if self.long_input and messages and is_paste(messages[-1]) and working[-1] is not messages[-1]:
            reading = read_long_input(
                self.router, str(messages[-1]["content"]), [m for m in working[:-1] if m is not guide], self.inline_max_tokens,
                lambda: self.turn_budget_seconds - (self.clock() - turn_started), self.final_reserve_seconds, emit, steps, self.defense,
            )
            if reading is not None and reading.read:
                working[-1] = {**working[-1], "content": reading.message(self.defense.wrap_tool_result if self.defense.enabled else None)}
        closing = reading.closing() if reading is not None else ""
        # The answer check (ticket 20 #2) may grant one more round, for its single retry;
        # `checked_out` are the messages it added, which never count as something seen.
        rounds, retried = self.max_steps, False
        checked_out: set[int] = set()
        # A tool call Ollama could not parse (ticket 27) has a retry of its own, apart from #2's.
        call_retried = False
        # And the lookup check's: one retry, for a turn that has called no tool at all.
        lookup_retried = False
        read_on_retried = False
        read_rest_tried = False
        promise_retried = promise_declined = False

        def gave_up(answer: str) -> bool:
            """Found documents, left some unread, and said the fact is not there, with time left to do something about it."""
            return bool(
                not (messages and is_paste(messages[-1]))
                and any(step["kind"] == "tool_call" and step["tool_name"] in DOCUMENT_TOOLS for step in steps)
                and READ_ON_GAVE_UP.search(answer)
                and documents_left_unread(tool_context["read_state"])
                and self.turn_budget_seconds - (self.clock() - turn_started) >= self.final_reserve_seconds
            )

        def read_the_rest(latency_ms: int) -> str | None:
            """The code reads what is left and puts the notes in `working`; returns the line for the
            answer, None when nothing could be read. The rejected attempt reached no one and is not
            kept: the model answers from the notes, not against itself."""
            # A store or model failure here costs this extra, never the turn: the answer already written stands.
            try:
                reading_rest = read_rest(
                    self.router, self.document_reader, _last_user_text(messages), tool_context["read_state"], tool_context["document_names"],
                    window.view(working), self.inline_max_tokens, lambda: self.turn_budget_seconds - (self.clock() - turn_started),
                    self.final_reserve_seconds, emit, steps, self.defense,
                    lambda name, arguments: arguments_shape(name, arguments, self.registry.declared()),
                )
            except Exception:
                consume_usage()
                return None
            if reading_rest is None:
                return None
            steps.append({
                "kind": READ_REST_STEP, "tool_name": None, "arguments": None, "content": None,
                "latency_ms": latency_ms, **last,
            })
            working.append({"role": "user", "content": reading_rest.message(self.defense.wrap_tool_result if self.defense.enabled else None)})
            return reading_rest.closing()

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
                    result, model_used = self.router.chat_tools("general", window.view(working), self._offered_schemas(tool_context))
            except ModelCallTimeoutError:
                # The round ran into the reserve's edge: answer from what is gathered.
                consume_usage()
                stop_reason = STOP_TURN_BUDGET
                break
            except OllamaToolCallParseError:
                # The same input writes the same broken call, so the retry adds a note; the
                # call never reached a tool, and its text is the server's, not kept.
                consume_usage()
                steps.append({
                    "kind": TOOL_CALL_ERROR_STEP, "tool_name": None, "arguments": None, "content": None,
                    "latency_ms": int((perf_counter() - started) * 1000), "error_code": TOOL_CALL_PARSE,
                    "tokens_in": None, "tokens_out": None,
                })
                left = self.turn_budget_seconds - (self.clock() - turn_started)
                if call_retried or left < self.final_reserve_seconds:
                    stop_reason = STOP_TOOL_CALL_ERROR
                    break
                working.append({"role": "system", "content": TOOL_CALL_RETRY})
                call_retried, rounds = True, rounds + 1
                emit(TOOL_CALL_ERROR_STEP, label=TOOL_CALL_ERROR_LABEL)
                continue
            round_latency = int((perf_counter() - started) * 1000)
            last = consume_usage()
            window.observe(last["tokens_in"])
            calls = result["tool_calls"]
            if not calls:
                answer = result["content"]
                owed = (
                    self._owed_tool(tool_context, steps)
                    if not promise_retried and self.turn_budget_seconds - (self.clock() - turn_started) >= self.final_reserve_seconds
                    else None
                )
                filled = self._fill_owed(owed, window.view(working), turn_started) if owed is not None else None
                if owed is not None and filled is DECLINED:
                    # The words matched a request, and the model, asked, said it was none ("câu đó nghĩa là sao",
                    # no hour given, a thank-you after one): the answer stands, and no "not done" line follows.
                    promise_retried = promise_declined = True
                    steps.append({
                        "kind": PROMISE_CHECK_STEP, "tool_name": None, "arguments": None, "content": None,
                        "latency_ms": round_latency, "arguments_shape": {"declined": True}, **last,
                    })
                    owed = None
                if owed is not None:
                    # The rejected attempt reached no one and is not kept: shown its own "đã hẹn", the model
                    # said it again on 2 of 10 real requests (03/11).
                    promise_retried = True
                    steps.append({
                        "kind": PROMISE_CHECK_STEP, "tool_name": None, "arguments": None, "content": None,
                        "latency_ms": round_latency, **last,
                    })
                    if filled is not None:
                        # Told again in words, the model on the Discord prompt still answered without the call
                        # (2 of 11 set, 03/11). Asked for the arguments alone, in a JSON the decoder holds to
                        # the tool's schema, it set 11 of 11. The tool runs as if the model had called it, through
                        # its own checks, and the model writes the answer from the result in the next round.
                        arguments, usage = filled
                        working.append({"role": "assistant", "content": "", "tool_calls": [{"function": {"name": owed.name, "arguments": arguments}}]})
                        steps.append({
                            "kind": "tool_call", "tool_name": owed.name, "tool_declared": True, "constrained": True,
                            "arguments": arguments, "content": None, "latency_ms": usage.pop("latency_ms"),
                            "arguments_shape": arguments_shape(owed.name, arguments, self.registry.declared()), **usage,
                        })
                        emit("tool_call", tool=owed.name, label=owed.label or TOOL_LABEL)
                        tool_started = perf_counter()
                        tool_context["_state_resources"] = {}
                        tool_context["_state_resources_unknown"] = False
                        text, error_code, error_type = self._run_tool(owed.name, arguments, tool_context)
                        output = self.defense.wrap_tool_result(text)
                        self._record_tool_state({"name": owed.name, "arguments": arguments}, output, error_code, tool_context)
                        steps.append({
                            "kind": "tool_result", "tool_name": owed.name, "tool_declared": True, "arguments": None,
                            "content": output, "latency_ms": int((perf_counter() - tool_started) * 1000),
                            "error_code": error_code, "error_type": error_type,
                        })
                        emit("tool_result", tool=owed.name, ok=error_code is None)
                        working.append({"role": "tool", "tool_name": owed.name, "content": output})
                    else:
                        checked_out.add(len(working))
                        working.append({"role": "system", "content": owed.promise_retry or f"Người dùng vừa nhờ việc cần gọi {owed.name} mà bạn chưa gọi. Gọi {owed.name} ngay; không được nói đã làm khi chưa gọi."})
                    rounds += 1
                    emit(PROMISE_CHECK_STEP, label=PROMISE_CHECK_LABEL)
                    continue
                if (
                    self.lookup_check and not lookup_retried and self._offers_lookup()
                    # "Not in the text you sent" is a true answer about a paste, not a lookup skipped.
                    and not (messages and is_paste(messages[-1]))
                    and not any(step["kind"] == "tool_call" for step in steps) and LOOKUP_GAVE_UP.search(answer)
                    and self.turn_budget_seconds - (self.clock() - turn_started) >= self.final_reserve_seconds
                ):
                    # Gave up before looking: the rejected attempt reached no one, so the trace keeps that it
                    # happened, not its text, and it never vouches for a figure (it is a checked-out message).
                    steps.append({
                        "kind": LOOKUP_CHECK_STEP, "tool_name": None, "arguments": None, "content": None,
                        "latency_ms": round_latency, **last,
                    })
                    checked_out.update((len(working), len(working) + 1))
                    working.append({"role": "assistant", "content": answer})
                    working.append({"role": "system", "content": LOOKUP_RETRY})
                    lookup_retried, rounds = True, rounds + 1
                    emit(LOOKUP_CHECK_STEP, label=LOOKUP_CHECK_LABEL)
                    continue
                gave_up_on_documents = gave_up(answer)
                if self.read_rest and not read_rest_tried and gave_up_on_documents:
                    read_rest_tried = True
                    told = read_the_rest(round_latency)
                    if told is not None:
                        closing += told
                        read_on_retried, rounds = True, rounds + 1
                        continue
                if self.read_on_check and not read_on_retried and gave_up_on_documents:
                    # As the lookup check: the rejected attempt reached no one and vouches for nothing.
                    steps.append({
                        "kind": READ_ON_CHECK_STEP, "tool_name": None, "arguments": None, "content": None,
                        "latency_ms": round_latency, **last,
                    })
                    checked_out.update((len(working), len(working) + 1))
                    working.append({"role": "assistant", "content": answer})
                    working.append({"role": "system", "content": READ_ON_RETRY})
                    read_on_retried, rounds = True, rounds + 1
                    emit(READ_ON_CHECK_STEP, label=READ_ON_CHECK_LABEL)
                    continue
                check = self._check_answer(answer, working, checked_out)
                left = self.turn_budget_seconds - (self.clock() - turn_started)
                if check["unsupported"] and not retried and left >= self.final_reserve_seconds:
                    # Figures the turn saw nowhere (ticket 20 #2, T1): one retry, with tools,
                    # in a round of its own. The rejected answer reached no one, so the trace
                    # keeps not its text but the figures it was rejected for (ticket 28 #1):
                    # in `arguments`, which is content (deleted with the conversation, read by
                    # forget_member), while arguments_shape, the summary's, keeps their count.
                    steps.append({
                        "kind": ANSWER_CHECK_STEP, "tool_name": None,
                        "arguments": {"unsupported_figures": list(check["unsupported"])}, "content": None,
                        "latency_ms": round_latency, "error_code": UNSUPPORTED_FIGURES,
                        "arguments_shape": {"unsupported_figures": len(check["unsupported"])}, **last,
                    })
                    checked_out.update((len(working), len(working) + 1))
                    working.append({"role": "assistant", "content": answer})
                    working.append({"role": "system", "content": retry_instruction(check["unsupported"])})
                    retried, rounds = True, rounds + 1
                    emit("answer_check", label=ANSWER_CHECK_LABEL)
                    continue
                # Ticket 45: what the reading pass could not read is told to the user by the code, not left to the model.
                answer += closing + self._unkept(promise_retried and not promise_declined, tool_context, steps)
                steps.append({
                    "kind": "final", "tool_name": None, "arguments": None,
                    "content": _clip(answer, 4000), "latency_ms": round_latency,
                    "stop_reason": STOP_FINAL, **check["trace"], **last, **({"context_cleared": window.cleared} if window.cleared else {}),
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
                if tool is not None and not self._available(tool, tool_context):
                    # A tool this turn may not see is treated as one that does not exist: no label, no
                    # name in the trace, no approval, and _run_tool answers UNKNOWN_TOOL.
                    tool = None
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
                tool_context["_state_resources"] = {}
                tool_context["_state_resources_unknown"] = False
                if tool is not None and tool.requires_approval:
                    # Ticket 46: kept for a person, not run. Kept: the turn ends here with the gate's reply.
                    held = self._hold_for_approval(call["name"], call["arguments"], tool_context)
                    if isinstance(held, ApprovalNotice):
                        self._record_tool_state(call, None, APPROVAL_PENDING, tool_context)
                        steps.append({
                            "kind": "tool_result", "tool_name": call["name"], "tool_declared": True, "arguments": None,
                            "content": None, "latency_ms": int((perf_counter() - tool_started) * 1000),
                            "error_code": APPROVAL_PENDING, "error_type": None,
                        })
                        steps.append({
                            "kind": "final", "tool_name": None, "arguments": None, "content": _clip(held.reply, 4000),
                            "latency_ms": 0, "stop_reason": STOP_AWAITING_APPROVAL, "tokens_in": None, "tokens_out": None,
                            # The web chat draws its approve/deny card from this (local_file_writes.py). Only for
                            # a tool gated by AgentTool.available, so a Discord turn's step is as before.
                            **({"approval_id": held.approval_id} if tool.available is not None else {}),
                        })
                        record_usage(last["tokens_in"], last["tokens_out"])
                        emit("final", stop_reason=STOP_AWAITING_APPROVAL)
                        return held.reply, model_used, steps
                    text, error_code, error_type = held
                else:
                    text, error_code, error_type = self._run_tool(call["name"], call["arguments"], tool_context)
                    if tool is not None and tool.ends_turn and error_code is None:
                        self._record_tool_state(call, text, None, tool_context)
                        steps.append({
                            "kind": "tool_result", "tool_name": call["name"], "tool_declared": True, "arguments": None,
                            "content": None, "latency_ms": int((perf_counter() - tool_started) * 1000),
                            "error_code": None, "error_type": None,
                        })
                        steps.append({
                            "kind": "final", "tool_name": None, "arguments": None, "content": _clip(text, 4000),
                            "latency_ms": 0, "stop_reason": STOP_ASKED_USER, "tokens_in": None, "tokens_out": None,
                        })
                        record_usage(last["tokens_in"], last["tokens_out"])
                        emit("final", stop_reason=STOP_ASKED_USER)
                        return text, model_used, steps
                # D5: tool output is untrusted data (document chunks, memory
                # text); the defense marks it so before the model reads it.
                output = self.defense.wrap_tool_result(text)
                self._record_tool_state(call, output, error_code, tool_context)
                steps.append({
                    "kind": "tool_result", "tool_name": call["name"], "tool_declared": declared, "arguments": None,
                    "content": output, "latency_ms": int((perf_counter() - tool_started) * 1000),
                    "error_code": error_code, "error_type": error_type,
                })
                emit("tool_result", tool=call["name"] if declared else None, ok=error_code is None)
                working.append({"role": "tool", "tool_name": call["name"], "content": output})

        # Out of tool rounds, out of time, or a tool call that will not parse: force a plain
        # answer from what was gathered — the structured stop that keeps the work done, not
        # an exception that throws it away (the Claude SDK / smolagents / Inspect family).
        working.append({
            "role": "system",
            "content": (
                "Đã dùng tối đa số lượt công cụ. Trả lời ngay bằng những gì đã thu thập được."
                if stop_reason == STOP_MAX_STEPS
                else "Không gọi được công cụ nữa. Trả lời ngay bằng những gì đã thu thập được."
                if stop_reason == STOP_TOOL_CALL_ERROR
                else "Hết thời gian dùng công cụ. Trả lời ngay bằng những gì đã thu thập được."
            ) + " " + FORCED_ANSWER_HONESTY,
        })
        emit("answering", label=ANSWERING_LABEL)
        started = perf_counter()
        left = self.turn_budget_seconds - (self.clock() - turn_started)
        usage: dict[str, int | None] = {"tokens_in": None, "tokens_out": None}
        try:
            if left <= 0:
                raise ModelCallTimeoutError("no time left for the final answer")
            with call_within(left):
                answer, model_used = self.router.chat("general", window.view(working))
            usage = last = consume_usage()
        except ModelCallTimeoutError:
            # Only running out of time ends here: an unreachable or broken model still
            # raises as before, because "not in time" would then be a false reply.
            consume_usage()
            answer, stop_reason = self._out_of_time_reply(), STOP_TURN_BUDGET_EXHAUSTED
        # Out of rounds with documents half read is the same giving up: ctx-05..07 spent their
        # rounds on two reads and were told to answer from them. If the second answer runs out of
        # time, the first still stands.
        if self.read_rest and not read_rest_tried and stop_reason == STOP_MAX_STEPS and gave_up(answer):
            read_rest_tried = True
            told = read_the_rest(int((perf_counter() - started) * 1000))
            if told is not None:
                try:
                    with call_within(self.turn_budget_seconds - (self.clock() - turn_started)):
                        answer, model_used = self.router.chat("general", window.view(working))
                    usage = last = consume_usage()
                    closing += told
                except Exception:  # out of time, or the model down: the first answer stands (review 06/11)
                    consume_usage()
        # Out of rounds or time, there is no retry left: the check only marks the trace.
        # The fixed out-of-time reply is ours, not the model's, and is not checked.
        check = self._check_answer(answer, working, checked_out) if stop_reason != STOP_TURN_BUDGET_EXHAUSTED else {"trace": {}}
        answer += closing + (self._unkept(promise_retried and not promise_declined, tool_context, steps) if stop_reason != STOP_TURN_BUDGET_EXHAUSTED else "")
        steps.append({
            "kind": "final", "tool_name": None, "arguments": None,
            "content": _clip(answer, 4000), "latency_ms": int((perf_counter() - started) * 1000),
            "stop_reason": stop_reason, **check["trace"], **usage, **({"context_cleared": window.cleared} if window.cleared else {}),
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

    def _promises(self) -> list[AgentTool]:
        """The offered tools that carry a promise check."""
        offered = {id(schema) for schema in self._offered_schemas()}
        return [tool for tool in self.registry.tools() if tool.promised is not None and id(tool.schema) in offered]

    def _owed_tool(self, tool_context: dict[str, Any], steps: list[dict[str, object]]) -> AgentTool | None:
        """A tool the speaker asked for that this turn has not called. A gate that fails says nothing is owed."""
        # A call the tool refused (remind(at="15:00") -> BAD_ARGUMENTS) kept nothing: only a result without an error counts.
        called = {step["tool_name"] for step in steps if step["kind"] == "tool_result" and not step.get("error_code")}
        for tool in self._promises():
            if tool.name in called:
                continue
            try:
                if tool.promised(tool_context):
                    return tool
            except Exception:
                pass
        return None

    def _fill_owed(self, tool: AgentTool, view: list[dict[str, Any]], turn_started: float) -> tuple[dict[str, Any], dict[str, Any]] | object | None:
        """The owed tool's arguments from one structured-output call: (arguments, the step's usage
        and latency); DECLINED when the model says the speaker asked for no such thing; or None when the
        tool asks for none, the provider cannot (not Ollama), time is short or the reply is not an
        object. None falls back to the retry in words.

        The gate is a word pattern, so it fires on "Sếp bảo: nhắc tôi họp lúc 3 giờ. Câu đó nghĩa là
        sao?" or "nhắc mình mua 2 hộp sữa" (a number, no hour) (review 06/11). Holding the decoder to the
        tool's schema alone would then force a reminder nobody asked for, so the model first says, in
        `requested`, whether this message asks for it now."""
        left = self.turn_budget_seconds - (self.clock() - turn_started) - self.final_reserve_seconds
        if not tool.promise_fill or tool.requires_approval or tool.ends_turn or left <= 0 or not hasattr(self.router, "chat_structured"):
            return None
        parameters = tool.schema["function"]["parameters"]
        properties = parameters.get("properties", {})
        # Every key present and each optional one nullable: the decoder then cannot leave out a key the
        # tool needs, and "not given" is a null the code drops, not a value the model had to invent.
        schema = {
            "type": "object",
            "properties": {
                "requested": {"type": "boolean", "description": f"tin nhắn này có thật sự nhờ {tool.name} ngay bây giờ không"},
                **{
                    key: spec if key in parameters.get("required", []) else {**spec, "type": [spec.get("type", "string"), "null"]}
                    for key, spec in properties.items()
                },
            },
            "required": ["requested", *properties],
        }
        now = datetime.now(VIETNAM_TIME)
        calendar = "; ".join(
            f"{WEEKDAYS[day.weekday()]} {day:%d/%m/%Y}" + (" (hôm nay)" if offset == 0 else " (ngày mai)" if offset == 1 else "")
            for offset in range(8) for day in [now + timedelta(days=offset)]
        )
        ask = {"role": "system", "content": (
            f"{tool.promise_fill}\n{PROMISE_REQUESTED}\nBây giờ là {now:%H:%M} {WEEKDAYS[now.weekday()]} {now:%d/%m/%Y} (giờ Việt Nam). Lịch: {calendar}.\n"
            f"Trả về đúng một JSON theo lược đồ: {json.dumps(schema, ensure_ascii=False)}"
        )}
        started = perf_counter()
        try:
            with call_within(left):
                reply, _ = self.router.chat_structured("general", [*view, ask], schema)
            usage = consume_usage()
            arguments = json.loads(reply)
        except Exception:
            consume_usage()
            return None
        if not isinstance(arguments, dict):
            return None
        if arguments.pop("requested", True) is False:
            return DECLINED
        return {key: value for key, value in arguments.items() if value is not None}, {**usage, "latency_ms": int((perf_counter() - started) * 1000)}

    def _unkept(self, retried: bool, tool_context: dict[str, Any], steps: list[dict[str, object]]) -> str:
        """After the promise check's one retry, a request still not carried out is said by the code,
        so an answer that claims it was done does not stand alone."""
        owed = self._owed_tool(tool_context, steps) if retried else None
        return f"\n\n(Lưu ý: lượt này chưa thực hiện được việc bạn nhờ ({owed.name}). Bạn dặn lại giúp mình nhé.)" if owed else ""

    def _offers_lookup(self) -> bool:
        """Whether the registry holds a tool to look something up with (BFCL's holds only the task's own functions)."""
        return any(self.registry.get(name) is not None for name in LOOKUP_TOOLS)

    def _offered_schemas(self, tool_context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """What the model is shown: every tool, except one that requires approval while nothing can approve it,
        and one this turn may not see (AgentTool.available)."""
        return [
            tool.schema for tool in self.registry.tools()
            if (self.approvals is not None or not tool.requires_approval) and self._available(tool, tool_context)
        ]

    @staticmethod
    def _available(tool: AgentTool, tool_context: dict[str, Any] | None) -> bool:
        return tool.available is None or bool(tool.available(tool_context or {}))

    def _hold_for_approval(self, name: str, arguments: dict[str, Any], tool_context: dict[str, Any] | None) -> ApprovalNotice | ToolOutput:
        """The gate keeps the call (ApprovalNotice), or the reason it could not is a tool error for the model."""
        if self.approvals is None:
            return self._error(APPROVAL_UNAVAILABLE, f"{name} cần người dùng duyệt nhưng ở đây chưa duyệt được nên chưa làm. Nói thật với người dùng là chưa làm được.")
        try:
            return self.approvals.request(name, arguments, tool_context)
        except ApprovalError as error:
            return self._error(error.code, error.message)
        except Exception as error:
            return self._error(
                TOOL_FAILED, f"{name} đang lỗi nên chưa gửi đi xin duyệt được. Đừng gọi lại trong lượt này; nói với người dùng là chưa làm.", type(error).__name__,
            )

    def run_approved(self, name: str, arguments: dict[str, Any], tool_context: dict[str, Any] | None = None) -> ToolOutput:
        """Run a call a person approved (ticket 46): the only way a tool that requires approval runs. Called
        by the gate, never by the loop; a tool that no longer exists or no longer requires approval is not run."""
        tool = self.registry.get(name)
        if tool is None or not tool.requires_approval:
            return self._error(UNKNOWN_TOOL, f"{name} không còn là công cụ cần duyệt nên không chạy.")
        return self._run_tool(name, arguments, tool_context, approved=True)

    def _run_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        tool_context: dict[str, Any] | None = None,
        *,
        approved: bool = False,
    ) -> ToolOutput:
        """Dispatch one call -> (text for the model, error code, exception type).

        Errors become data the model can react to — a broken tool must never
        kill the whole answer. The exception's class goes to the trace only: the
        model gets a sentence saying what to do next, not "TypeError: ..."."""
        try:
            tool = self.registry.get(name)
            if tool is None or not self._available(tool, tool_context):
                # A tool this turn may not see is answered like one that does not exist, and the list
                # names only what it may see.
                names = [item.name for item in self.registry.tools() if self._available(item, tool_context)]
                return self._error(UNKNOWN_TOOL, f"Không có công cụ {name}. Chỉ có {', '.join(names)}.")
            if tool.requires_approval and not approved:
                # Whatever calls this, a tool that waits for a person does not run without one (ticket 46).
                return self._error(APPROVAL_REQUIRED, f"{name} cần người dùng duyệt trước nên chưa chạy.")
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
        chunks = self.retrieval_service.retrieve(query, min(max(top_k, 1), 8), None)
        if (tool_context or {}).get("_tool_recorder") is not None:
            tool_context["_state_resources"] = {str(chunk["document_id"]): str(chunk["version_id"]) for chunk in chunks if chunk.get("document_id") and chunk.get("version_id")}
            tool_context["_state_resources_unknown"] = any(not chunk.get("document_id") or not chunk.get("version_id") for chunk in chunks)
        if not chunks:
            return self._dump({"result": "không tìm thấy đoạn tài liệu nào phù hợp"}), None, None
        readable = (tool_context or {}).get("readable_documents")
        items = []
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
                if tool_context and "read_state" in tool_context:
                    tool_context["read_state"].setdefault(item["document_id"], {"seen": set(), "total": None})
                    tool_context["document_names"].setdefault(item["document_id"], str(chunk.get("filename") or item["document_id"]))
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
        if (tool_context or {}).get("_tool_recorder") is not None:
            if document_id in pastes or not found.get("version_id"):
                tool_context["_state_resources_unknown"] = True
            else:
                tool_context["_state_resources"] = {document_id: str(found["version_id"])}
        total = int(found.get("total_chunks") or 0)
        if not found.get("chunks"):
            if page:
                return self._dump({
                    "result": f"không có đoạn nào ở trang {page} (tài liệu ngắn hơn, hoặc không chia trang); đọc theo from_chunk",
                    "total_chunks": total,
                }), None, None
            return self._dump({"result": "đã hết tài liệu", "total_chunks": total}), None, None
        fitted = self._fit_chunks(found, total)
        if document_id not in pastes and tool_context and "read_state" in tool_context:
            note_read(tool_context["read_state"], document_id, [chunk["chunk_index"] for chunk in json.loads(fitted)["chunks"]], total)
        return fitted, None, None

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

    def _record_tool_state(self, call, output, error_code, context):
        recorder = (context or {}).get("_tool_recorder")
        tool = self.registry.get(call["name"])
        if isinstance(recorder, ToolStateRecorder) and tool is not None and not context.get("_state_resources_unknown"):
            recorder.record(call["name"], call["arguments"], output, error_code,
                            policy=tool.state_policy, schema=tool.schema,
                            resources=context.get("_state_resources") or {})

    def _system_status(self, arguments: dict[str, Any], tool_context: dict[str, Any] | None) -> ToolOutput:
        return self._dump(self.operational_service.health()), None, None

    def _current_time(self, arguments: dict[str, Any], tool_context: dict[str, Any] | None) -> ToolOutput:
        now = datetime.now(VIETNAM_TIME)
        return self._dump({
            "iso": now.isoformat(timespec="seconds"),
            "weekday": WEEKDAYS[now.weekday()],
            "date": now.strftime("%d/%m/%Y"),
            "time": now.strftime("%H:%M"),
            "timezone": "Asia/Ho_Chi_Minh (UTC+7)",
        }), None, None

    def _calculate(self, arguments: dict[str, Any], tool_context: dict[str, Any] | None) -> ToolOutput:
        expression = arguments.get("expression")
        if not isinstance(expression, str):
            return self._error(BAD_ARGUMENTS, "Cần expression là một chuỗi, ví dụ 1250000 * 0.15.")
        try:
            return self._dump({"expression": expression, "result": calculate(expression)}), None, None
        except CalculationError as error:
            return self._error(BAD_ARGUMENTS, str(error))

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
SEARCH_DOCUMENTS_ORDER, READ_DOCUMENT_ORDER, SYSTEM_STATUS_ORDER, CURRENT_TIME_ORDER, CALCULATE_ORDER = 10, 15, 30, 40, 50


def core_tools() -> ToolRegistry:
    """A fresh registry holding the core's own tools (ticket 20, option b; ticket 22, C4):
    each tool is a schema and the handler that runs it, so none can be declared without a
    handler, nor run without being declared."""
    registry = ToolRegistry()
    registry.register(AgentTool(SEARCH_DOCUMENTS_SCHEMA, AgentService._search_documents, "Đang tra tài liệu…", state_policy="read"), SEARCH_DOCUMENTS_ORDER)
    registry.register(AgentTool(READ_DOCUMENT_SCHEMA, AgentService._read_document, "Đang đọc tài liệu…", state_policy="read"), READ_DOCUMENT_ORDER)
    registry.register(AgentTool(SYSTEM_STATUS_SCHEMA, AgentService._system_status, "Đang xem trạng thái hệ thống…"), SYSTEM_STATUS_ORDER)
    registry.register(AgentTool(CURRENT_TIME_SCHEMA, AgentService._current_time, "Đang xem giờ…"), CURRENT_TIME_ORDER)
    registry.register(AgentTool(CALCULATE_SCHEMA, AgentService._calculate, "Đang tính…", state_policy="read"), CALCULATE_ORDER)
    return registry
