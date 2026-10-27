"""Ticket 10, change 2b: an empty document search on a Discord turn points at the history.

Agent Eval v0.1/v0.2 measured the model searching the documents for something the
server had discussed, getting nothing, and answering "not found" without trying
search_history (hist-07). The hint appears only on that path, after the defense's
data wrapper. No stack: the router is scripted, the backends are fakes.
"""
from app.services.agent_service import HISTORY_HINT, AgentService
from app.services.injection_defense import TOOL_RESULT_CLOSE, InjectionDefense


class Router:
    def __init__(self):
        self.turns = [
            {"content": "", "tool_calls": [{"name": "search_documents", "arguments": {"query": "bảo trì"}}],
             "raw_tool_calls": [{"function": {"name": "search_documents", "arguments": {"query": "bảo trì"}}}]},
            {"content": "Xong.", "tool_calls": [], "raw_tool_calls": []},
        ]

    def chat_tools(self, mode, messages, tools):
        return self.turns.pop(0), "qwen3.5:9b"

    def chat(self, mode, messages, options=None):
        return "Xong.", "qwen3.5:9b"


class Retrieval:
    def __init__(self, chunks):
        self.chunks = chunks

    def retrieve(self, query, top_k, document_id=None):
        return self.chunks


class History:
    def search(self, **kwargs):
        return []

    def recent(self, **kwargs):
        return []


def tool_result(chunks, tool_context, history=History()):
    agent = AgentService(Router(), Retrieval(chunks), None, defense=InjectionDefense(enabled=True), history_service=history)
    _, _, steps = agent.run([{"role": "user", "content": "Lịch bảo trì là khi nào?"}], tool_context=tool_context)
    return next(step["content"] for step in steps if step["kind"] == "tool_result")


def test_an_empty_document_search_in_a_discord_server_points_at_the_history():
    output = tool_result([], {"guild_id": "g"})
    assert output.endswith(HISTORY_HINT)
    # Outside the data wrapper: the defense tells the model to ignore instructions inside it.
    assert output.index(TOOL_RESULT_CLOSE) < output.index(HISTORY_HINT)


def test_no_hint_where_the_history_cannot_help():
    assert HISTORY_HINT not in tool_result([], None), "web chat: no guild, history unavailable"
    assert HISTORY_HINT not in tool_result([], {"guild_id": "g"}, history=None)
    found = [{"filename": "a.md", "page": None, "content": "Bảo trì thứ Bảy.", "score": 0.9}]
    assert HISTORY_HINT not in tool_result(found, {"guild_id": "g"}), "documents answered: nothing to redirect"
