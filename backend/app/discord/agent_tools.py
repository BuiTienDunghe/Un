"""The agent's Discord tool, plugged into the core's tool registry (ticket 22, C4).

search_history reads the guild's raw ledger (sổ gốc) through DiscordHistoryService. The
core declares no Discord tool of its own: register_services() registers this one into the
running AgentService's registry at startup, and agent_eval registers it with its fixture
guild. ORDER puts it exactly where it stood before the move, between read_document and
system_status, so the tool list the model is shown, and its hash, do not change.
"""
from __future__ import annotations

from typing import Any, Protocol

from app.discord.history_service import history_hit_payload
from app.services.agent_service import TOOL_UNAVAILABLE_HERE, AgentTool, ToolOutput, ToolRegistry, _clip

ORDER = 20

# A Discord message may run to 2000 characters (4000 with Nitro). Capped the way a
# document excerpt is capped at 400, so the whole-item truncation in _dump always
# has an item that fits instead of falling back to cutting the JSON mid-string.
# The search_history description states the cap, so the model does not quote a
# clipped message as if it were the whole of it.
HISTORY_MESSAGE_MAX_CHARS = 800


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


def _history_item(hit: object) -> dict[str, object]:
    payload = history_hit_payload(hit)
    payload["message"] = _clip(str(payload["message"]), HISTORY_MESSAGE_MAX_CHARS)
    return payload


class SearchHistory:
    """search_history's handler: a callable that holds the guild history backend, so the
    core's AgentService carries no Discord attribute. With no backend (the history service
    is not built) or no guild (a web turn) it says plainly that there is no history here."""

    def __init__(self, history_service: HistoryBackend | None) -> None:
        self.history_service = history_service

    def __call__(self, service: Any, arguments: dict[str, Any], tool_context: dict[str, Any] | None) -> ToolOutput:
        # The guild comes from the CALLER (the turn service knows the
        # session's guild), never from the model — the same isolation
        # lesson as the ledger read (memory_design.md §3.1).
        guild_id = str((tool_context or {}).get("guild_id") or "")
        if self.history_service is None or not guild_id:
            # Asked on the web, the model used to ask back "which server?"
            # (Agent Eval hist-10): say plainly there is no history here.
            return service._error(
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
                return service._dump(
                    {"result": "sổ gốc chưa có tin nhắn nào của server này"}
                ), None, None
            # Chronological, so an overflow must give up the OLDEST
            # messages: they are the ones a "latest N" read cares least about.
            return service._dump([_history_item(hit) for hit in hits], drop="first"), None, None
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
            return service._dump(
                {"result": "không tìm thấy tin nhắn cũ nào khớp"}
            ), None, None
        return service._dump([_history_item(hit) for hit in hits]), None, None


def register(registry: ToolRegistry, history_service: HistoryBackend | None) -> None:
    """Plug search_history into an agent's registry, reading `history_service`."""
    registry.register(AgentTool(SEARCH_HISTORY_SCHEMA, SearchHistory(history_service)), ORDER)
