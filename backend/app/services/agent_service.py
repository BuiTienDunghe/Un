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
from time import perf_counter
from typing import Any, Protocol

from app.services.injection_defense import InjectionDefense
from app.services.model_router import ModelRouter


class RetrievalBackend(Protocol):
    def retrieve(self, query: str, top_k: int, document_id: str | list[str] | None = None) -> list[dict[str, object]]: ...


class StatusBackend(Protocol):
    def health(self) -> dict[str, object]: ...


AGENT_GUIDE = (
    "Bạn có thể dùng công cụ khi cần dữ liệu thật: `search_documents` tìm trong "
    "tài liệu người dùng đã tải lên, `system_status` xem sức khỏe hệ thống. "
    "Chỉ gọi công cụ khi câu hỏi thật sự "
    "cần dữ liệu đó; câu chào hỏi hay kiến thức chung thì trả lời thẳng, không "
    "gọi gì. Khi dùng nội dung tài liệu, nêu tên tệp và số trang. Khi đã đủ "
    "thông tin, trả lời trọn vẹn bằng tiếng Việt."
)

AGENT_TOOLS: list[dict[str, Any]] = [
    {
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
    },
    {
        "type": "function",
        "function": {
            "name": "system_status",
            "description": "Đọc trạng thái sức khỏe hiện tại của hệ thống (PostgreSQL, Redis, Qdrant, Ollama, các worker, backup).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


class AgentService:
    def __init__(
        self,
        router: ModelRouter,
        retrieval_service: RetrievalBackend,
        operational_service: StatusBackend,
        max_steps: int = 3,
        tool_result_max_chars: int = 2400,
        defense: InjectionDefense | None = None,
    ) -> None:
        self.defense = defense or InjectionDefense(enabled=False)
        self.router = router
        self.retrieval_service = retrieval_service
        self.operational_service = operational_service
        self.max_steps = max(1, max_steps)
        self.tool_result_max_chars = max(200, tool_result_max_chars)

    def run(self, messages: list[dict[str, Any]]) -> tuple[str, str, list[dict[str, object]]]:
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
        for _ in range(self.max_steps):
            started = perf_counter()
            result, model_used = self.router.chat_tools("general", working, AGENT_TOOLS)
            round_latency = int((perf_counter() - started) * 1000)
            calls = result["tool_calls"]
            if not calls:
                steps.append({
                    "kind": "final", "tool_name": None, "arguments": None,
                    "content": _clip(result["content"], 4000), "latency_ms": round_latency,
                })
                return result["content"], model_used, steps
            # The model must see its own calls on the next round, verbatim.
            working.append({"role": "assistant", "content": result["content"], "tool_calls": result["raw_tool_calls"]})
            for call in calls:
                steps.append({
                    "kind": "tool_call", "tool_name": call["name"],
                    "arguments": call["arguments"], "content": None, "latency_ms": round_latency,
                })
                tool_started = perf_counter()
                # D5: tool output is untrusted data (document chunks, memory
                # text); the defense marks it so before the model reads it.
                output = self.defense.wrap_tool_result(self._execute_tool(call["name"], call["arguments"]))
                steps.append({
                    "kind": "tool_result", "tool_name": call["name"], "arguments": None,
                    "content": output, "latency_ms": int((perf_counter() - tool_started) * 1000),
                })
                working.append({"role": "tool", "tool_name": call["name"], "content": output})

        # Tool budget exhausted: force a plain answer from what was gathered.
        working.append({
            "role": "system",
            "content": "Đã dùng tối đa số lượt công cụ. Trả lời ngay bằng những gì đã thu thập được.",
        })
        started = perf_counter()
        answer, model_used = self.router.chat("general", working)
        steps.append({
            "kind": "final", "tool_name": None, "arguments": None,
            "content": _clip(answer, 4000), "latency_ms": int((perf_counter() - started) * 1000),
        })
        return answer, model_used, steps

    def _execute_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Dispatch one call; errors become data the model can react to —
        a broken tool must never kill the whole answer."""
        try:
            if name == "search_documents":
                query = str(arguments.get("query") or "").strip()
                if not query:
                    return self._dump({"error": "query trống"})
                try:
                    top_k = int(arguments.get("top_k", 4))
                except (TypeError, ValueError):
                    top_k = 4
                chunks = self.retrieval_service.retrieve(query, min(max(top_k, 1), 8), None)
                if not chunks:
                    return self._dump({"result": "không tìm thấy đoạn tài liệu nào phù hợp"})
                return self._dump([
                    {
                        "filename": chunk.get("filename"),
                        "page": chunk.get("page"),
                        "excerpt": _clip(str(chunk.get("content") or ""), 400),
                        "score": round(float(chunk.get("score") or 0.0), 3),
                    }
                    for chunk in chunks
                ])
            if name == "system_status":
                return self._dump(self.operational_service.health())
            return self._dump({"error": f"công cụ không tồn tại: {name}"})
        except Exception as error:
            return self._dump({"error": f"{type(error).__name__}: {error}"})

    def _dump(self, payload: object) -> str:
        return _clip(json.dumps(payload, ensure_ascii=False, default=str), self.tool_result_max_chars)
