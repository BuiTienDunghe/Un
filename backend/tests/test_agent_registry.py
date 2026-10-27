"""The agent's tools live in a registry a package can plug into (ticket 22, C4).

The core registers its own tools; app.discord registers search_history at startup. What the
model is shown, which names count as declared in the trace, and which keys the trace shapes
are all read off the running agent's registry when used, so a tool registered after the
agent was built is never missed, and the order is the one each tool asks for, not the order
of registration. No stack: the model is scripted.
"""
from __future__ import annotations

import pytest

from app.discord import agent_tools
from app.services.agent_service import AgentService, AgentTool, ToolRegistry, core_tools


def tool(name: str, properties: dict | None = None) -> AgentTool:
    schema = {"type": "function", "function": {"name": name, "description": name, "parameters": {"type": "object", "properties": properties or {}, "required": []}}}
    return AgentTool(schema, lambda service, arguments, context: (service._dump({"ok": name}), None, None))


class Router:
    def __init__(self, rounds):
        self.rounds, self.tools_seen = list(rounds), []

    def chat_tools(self, role, messages, tools):
        self.tools_seen.append([t["function"]["name"] for t in tools])
        return self.rounds.pop(0), "fake"

    def chat(self, role, messages):
        return "xong", "fake"


def test_the_order_is_the_one_asked_for_not_the_order_of_registration():
    registry = ToolRegistry()
    registry.register(tool("c"), 30)
    registry.register(tool("a"), 10)
    registry.register(tool("b"), 20)
    assert registry.names() == ("a", "b", "c")
    assert [s["function"]["name"] for s in registry.schemas()] == ["a", "b", "c"]


def test_a_name_registers_once():
    registry = core_tools()
    with pytest.raises(ValueError, match="search_documents"):
        registry.register(tool("search_documents"), 99)


def test_the_core_alone_has_no_discord_tool_and_the_package_puts_it_back_in_its_place():
    assert core_tools().names() == ("search_documents", "read_document", "system_status")
    registry = core_tools()
    agent_tools.register(registry, None)
    assert registry.names() == ("search_documents", "read_document", "search_history", "system_status")


def test_a_tool_registered_after_the_agent_was_built_is_shown_declared_and_shaped():
    router = Router([
        {"content": "", "tool_calls": [{"name": "late", "arguments": {"q": "abc"}}], "raw_tool_calls": [{"function": {"name": "late", "arguments": {"q": "abc"}}}]},
        {"content": "xong", "tool_calls": [], "raw_tool_calls": []},
    ])
    agent = AgentService(router, None, None)
    agent.registry.register(tool("late", {"q": {"type": "string"}}), 40)

    _, _, steps = agent.run([{"role": "user", "content": "thử"}])
    assert router.tools_seen[0][-1] == "late"
    called = next(s for s in steps if s["kind"] == "tool_call")
    assert called["tool_declared"] is True and called["arguments_shape"] == {"q": "str:3"}
    assert next(s for s in steps if s["kind"] == "tool_result")["error_code"] is None


def test_each_agent_has_its_own_registry_unless_one_is_shared_on_purpose():
    first, second = AgentService(None, None, None), AgentService(None, None, None)
    first.registry.register(tool("only_first"), 40)
    assert "only_first" not in second.registry.names(), "a test's tool never leaks into another agent"

    shared = core_tools()
    assert AgentService(None, None, None, registry=shared).registry is shared
