"""Real ChatService/AgentService across turns with no model, network or database."""
import copy
import json
from types import SimpleNamespace

import pytest

from app.services.agent_service import AgentService, AgentTool, ToolRegistry, core_tools
from app.services.chat_service import ChatService
from app.services.context_budget import ContextBudget, ContextWindow
from app.services.tool_state import ToolStateRecorder, scope_key
from app.services.tool_state_bridge import restore_history


SCHEMA = {"type": "function", "function": {"name": "lookup", "description": "Fixture lookup", "parameters": {"type": "object", "properties": {"key": {"type": "string"}}}}}


class Store:
    def __init__(self):
        self.messages = {}
        self.states = []
        self.versions = {}
        self.next_id = 1

    def create_conversation(self, key, *args):
        self.messages[key] = []

    def conversation_exists(self, key):
        return key in self.messages

    def delete_conversation(self, key):
        self.messages.pop(key, None)

    def get_messages(self, key, limit):
        return [{"role": r["role"], "content": r["content"]} for r in self.messages[key][-limit:]]

    def get_agent_history(self, key, limit):
        return copy.deepcopy(self.messages[key][-limit:])

    def add_message(self, key, role, content, *args):
        ident = self.next_id
        self.next_id += 1
        self.messages[key].append({"message_id": ident, "role": role, "content": content})
        return ident

    def add_agent_traces(self, *args, **kwargs):
        pass

    def save_tool_state(self, key, ident, scope, payload, origin=None):
        self.states.append({"conversation_id": key, "scope": scope, "message_id": ident, "origin": origin, "payload": copy.deepcopy(payload)})

    def load_tool_states(self, key, scope, *, message_ids=None, origins=None):
        return [row for row in reversed(self.states) if row["conversation_id"] == key and row["scope"] == scope and (row["message_id"] in (message_ids or []) or row["origin"] in (origins or []))]

    def state_document_versions(self, ids):
        return {key: self.versions[key] for key in ids if key in self.versions}


class Router:
    models = {"general": {"name": "fake", "context": 16384}}

    def __init__(self, replies):
        self.replies = list(replies)
        self.inputs = []

    def chat_tools(self, mode, messages, tools):
        self.inputs.append(copy.deepcopy(messages))
        reply = self.replies.pop(0)
        if isinstance(reply, tuple):
            name, args = reply
            raw = [{"function": {"name": name, "arguments": args}}]
            return {"content": "", "tool_calls": [{"name": name, "arguments": args}], "raw_tool_calls": raw}, "fake"
        return {"content": reply, "tool_calls": [], "raw_tool_calls": []}, "fake"

    def chat(self, mode, messages, **kwargs):
        self.inputs.append(copy.deepcopy(messages))
        return "done", "fake"


def service(store, replies, calls, *, enabled=True, policy="read", resources=None, name="lookup"):
    router = Router(replies)
    registry = ToolRegistry()
    schema = copy.deepcopy(SCHEMA)
    schema["function"]["name"] = name
    def run(agent, args, context):
        calls.append(copy.deepcopy(args))
        if resources is not None:
            context["_state_resources"] = dict(resources)
        return json.dumps({"receipt_id": "stable-result", "value": 7}), None, None
    registry.register(AgentTool(schema, run, state_policy=policy), 1)
    chat = ChatService(store, router, SimpleNamespace(log_request=lambda *a, **k: None), 20, tool_state_enabled=enabled)
    chat.agent_service = AgentService(router, None, None, registry=registry)
    return chat, router


def test_web_state_survives_service_restart_without_reexecuting_tools(monkeypatch):
    monkeypatch.setattr("app.services.chat_service.clock_note", lambda: {"role": "system", "content": "fixed clock"})
    store, calls = Store(), []
    first, router = service(store, [("lookup", {"key": "A"}), "remembered"], calls)
    _, _, key, _, _ = first.respond("look up A", None, use_tools=True, user_id="alice")
    second, router = service(store, ["answer from prior result"], calls)
    second.respond("what was its value?", key, use_tools=True, user_id="alice")
    history = router.inputs[0]
    assert any(row.get("role") == "tool" and "stable-result" in row["content"] for row in history)
    assert len(calls) == 1
    assert first.agent_service.max_steps == second.agent_service.max_steps == 3
    assert len(store.states) == 1  # no empty envelope for a direct answer


def test_flag_off_and_empty_state_do_not_change_model_messages(monkeypatch):
    monkeypatch.setattr("app.services.chat_service.clock_note", lambda: {"role": "system", "content": "fixed"})
    inputs = []
    for enabled in (False, True):
        store, calls = Store(), []
        chat, router = service(store, [("lookup", {"key": "A"}), "done"], calls, enabled=enabled)
        chat.respond("look up", None, use_tools=True, user_id="alice")
        inputs.append(router.inputs)
    assert inputs[0] == inputs[1]


def test_other_actor_does_not_receive_tool_result():
    store, calls = Store(), []
    first, _ = service(store, [("lookup", {}), "done"], calls)
    _, _, key, _, _ = first.respond("look up", None, use_tools=True, user_id="alice")
    second, router = service(store, ["done"], calls)
    second.respond("follow up", key, use_tools=True, user_id="bob")
    assert not any(row.get("role") == "tool" for row in router.inputs[0])


@pytest.mark.parametrize("version", [None, "v2"])
def test_missing_or_changed_document_invalidates_whole_observation(version):
    store, calls = Store(), []
    store.versions = {"doc": "v1"}
    first, _ = service(store, [("lookup", {}), "done"], calls, resources={"doc": "v1"})
    _, _, key, _, _ = first.respond("look up", None, use_tools=True, user_id="alice")
    store.versions = {} if version is None else {"doc": version}
    second, router = service(store, ["done"], calls, resources={"doc": "v1"})
    second.respond("follow up", key, use_tools=True, user_id="alice")
    assert not any(row.get("role") == "tool" for row in router.inputs[0])


def test_state_read_or_write_failure_does_not_lose_answer():
    store, calls = Store(), []
    chat, _ = service(store, [("lookup", {}), "saved"], calls)
    store.load_tool_states = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("unavailable"))
    store.save_tool_state = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("unavailable"))
    answer, _, key, _, _ = chat.respond("look up", None, use_tools=True, user_id="alice")
    assert answer == "saved" and store.messages[key][-1]["content"] == "saved"
    assert len(calls) == 1


def test_loading_action_receipt_does_not_dispatch_and_explicit_new_call_still_can_run():
    store, calls = Store(), []
    chat, _ = service(store, [("lookup", {"key": "A"}), "done"], calls, policy="receipt")
    _, _, key, _, _ = chat.respond("do A", None, use_tools=True, user_id="alice")
    again, router = service(store, ["status only"], calls, policy="receipt")
    again.respond("was it done?", key, use_tools=True, user_id="alice")
    receipts = [row for row in router.inputs[0] if row.get("role") == "tool"]
    assert json.loads(receipts[0]["content"])["status"] == "succeeded"
    assert "_tool_state_receipt" not in receipts[0]
    assert len(calls) == 1
    explicit, _ = service(store, [("lookup", {"key": "A"}), "done again"], calls, policy="receipt")
    explicit.respond("do A again", key, use_tools=True, user_id="alice")
    assert len(calls) == 2


def test_historical_document_observation_does_not_authorize_a_new_read():
    router = Router([("read_document", {"document_id": "doc", "from_chunk": 0}), "done"])
    reader = SimpleNamespace(read_chunks=lambda *a: pytest.fail("history must not grant document access"))
    agent = AgentService(router, None, None, document_reader=reader, registry=core_tools())
    historic = [
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "read_document", "arguments": {"document_id": "doc"}}}]},
        {"role": "tool", "tool_name": "read_document", "content": "old allowed observation"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "read more"},
    ]
    _, _, steps = agent.run(historic)
    assert any(step.get("error_code") == "BAD_ARGUMENTS" for step in steps)
    assert not hasattr(reader, "called")


def test_context_clearing_never_turns_receipt_into_retry_instruction():
    receipt = {"role": "tool", "tool_name": "write", "content": "historical receipt " * 100}
    rows = [
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "write", "arguments": {}}}]},
        receipt,
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "read", "arguments": {}}}]},
        {"role": "tool", "content": "read " * 500},
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "read", "arguments": {}}}]},
        {"role": "tool", "content": "latest"},
    ]
    view = ContextWindow(ContextBudget(ceiling_tokens=100, keep_recent=1), 100, protected_results={1}).view(rows)
    assert view[1] == receipt
    assert "gọi lại" not in view[1]["content"]


@pytest.mark.parametrize("actor,anchors,expected", [
    ("alice", [{"origin": "turn-1", "index": 1}], True),
    ("bob", [{"origin": "turn-1", "index": 1}], False),
    ("alice", [], False),
    ("alice", [{"origin": "different-turn", "index": 1}], False),
])
def test_discord_real_chat_restores_only_exact_trusted_actor_and_turn(actor, anchors, expected):
    store, calls = Store(), []
    store.create_conversation("discord-conversation")
    first, _ = service(store, [("lookup", {"key": "A"}), "same answer"], calls)
    first.respond_with_context("look up", "discord-conversation", model_history=[],
        current_model_message={"role": "user", "content": "look up"}, context_system_prompt="Discord",
        use_tools=True, tool_context={"guild_id": "guild", "actor_id": "alice", "turn_id": "turn-1"})
    second, router = service(store, ["follow up"], calls)
    second.respond_with_context("follow up", "discord-conversation",
        model_history=[{"role": "user", "content": "look up"}, {"role": "assistant", "content": "same answer"}],
        current_model_message={"role": "user", "content": "follow up"}, context_system_prompt="Discord",
        use_tools=True, tool_context={"guild_id": "guild", "actor_id": actor, "turn_id": "turn-2", "_state_anchors": anchors})
    assert any(row.get("role") == "tool" for row in router.inputs[0]) is expected
    assert len(calls) == 1


def test_promise_completion_records_the_actual_receipt():
    calls = []
    router = Router(["claim", "done"])
    router.chat_structured = lambda *args: ('{"requested":true,"key":"A"}', "fake")
    registry = ToolRegistry()
    def run(agent, arguments, context):
        calls.append(arguments)
        return "scheduled:receipt-123", None, None
    registry.register(AgentTool(SCHEMA, run, promised=lambda context: True,
        promise_fill="Extract the requested key", state_policy="receipt"), 1)
    agent = AgentService(router, None, None, registry=registry)
    recorder = ToolStateRecorder()
    agent.run([{"role": "user", "content": "do A"}], tool_context={"_tool_recorder": recorder})
    assert calls == [{"key": "A"}]
    assert recorder.payload()["groups"][0]["content"] == "scheduled:receipt-123"
    assert recorder.payload()["groups"][0]["status"] == "succeeded"
