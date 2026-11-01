"""The agent's ask_user tool (ticket 46): one question to the person, when a fact the task needs is missing.

Asking is the model's decision, so the code bounds it: the call ends the turn and its text is the whole
reply (AgentTool.ends_turn), which makes it at most one question per turn; a turn cannot ask, get nothing
and ask again. It is not offered unless AGENT_ASK_USER_ENABLED, and then the model is told to look first
(documents, time, the speaker's own message) and to ask only for what no tool can find.
"""
from __future__ import annotations

from typing import Any

from app.services.agent_service import BAD_ARGUMENTS, AgentTool, ToolOutput, ToolRegistry

ORDER = 55
QUESTION_MAX_CHARS = 500

ASK_USER_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "ask_user",
        "description": (
            "Hỏi lại người đang nói MỘT câu khi thiếu một dữ kiện bắt buộc để làm đúng việc họ nhờ, và không công cụ nào tìm được "
            "(đã tra tài liệu, xem giờ, đọc kỹ tin của họ mà vẫn thiếu). Gọi xong là lượt này kết thúc bằng đúng câu hỏi đó, "
            "bạn không trả lời thêm. KHÔNG gọi khi có thể tự tra, khi có mặc định hợp lý, hoặc khi chỉ muốn chắc chắn thêm."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": f"Một câu hỏi ngắn, cụ thể, nói rõ thiếu gì; tối đa {QUESTION_MAX_CHARS} ký tự"},
            },
            "required": ["question"],
        },
    },
}


def _ask_user(agent: Any, arguments: dict[str, Any], tool_context: dict[str, Any] | None) -> ToolOutput:
    question = str(arguments.get("question") or "").strip()
    if not question or len(question) > QUESTION_MAX_CHARS:
        return agent._error(BAD_ARGUMENTS, f"question phải là một câu hỏi từ 1 đến {QUESTION_MAX_CHARS} ký tự.")
    # The model's words become the reply: an "@" in them must not read as a ping when the bot posts it.
    return question.replace("@", "@​"), None, None


def register(registry: ToolRegistry) -> None:
    registry.register(AgentTool(ASK_USER_SCHEMA, _ask_user, "Đang chuẩn bị câu hỏi…", ends_turn=True), ORDER)
