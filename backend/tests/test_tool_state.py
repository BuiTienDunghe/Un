"""Pure continuity contracts: pairing, policy, provenance, receipts and hard bounds."""
from dataclasses import FrozenInstanceError
import json

import pytest

from app.services.tool_state import (
    STATE_KIND, ToolStateLimits, ToolStateRecorder, parse_payload,
    render_group, schema_key, scope_key,
)


def schema(name="calculate", description="test tool"):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": {}},
    }}


def observation(name="calculate", *, arguments=None, content="42", error=None,
                policy="read", resources=None):
    recorder = ToolStateRecorder()
    assert recorder.record(name, {} if arguments is None else arguments, content, error,
                           policy=policy, schema=schema(name), resources=resources)
    return recorder.payload()["groups"][0]


def test_scope_key_is_opaque_canonical_and_separates_all_authority_components():
    first = scope_key("conversation", "discord", "member", "guild")
    assert len(first) == 64 and "member" not in first
    assert first == scope_key("conversation", "discord", "member", "guild")
    assert len({
        first, scope_key("other-conversation", "discord", "member", "guild"),
        scope_key("conversation", "web", "member", "guild"),
        scope_key("conversation", "discord", "other-member", "guild"),
        scope_key("conversation", "discord", "member", "other-guild"),
    }) == 5
    assert scope_key("conversation", "web", None) != scope_key("conversation", "web", "")


def test_schema_key_tracks_semantic_json_not_object_key_order():
    assert schema_key({"b": [1, "x"], "a": True}) == schema_key({"a": True, "b": [1, "x"]})
    assert schema_key(schema()) != schema_key(schema(description="changed contract"))
    for invalid in (None, [], {"x": float("nan")}, {1: "coerced key"}, {"x": object()}):
        with pytest.raises(ValueError):
            schema_key(invalid)


def test_default_unknown_policy_never_persists_and_no_executor_is_accepted():
    recorder = ToolStateRecorder()
    assert STATE_KIND == "tool_state"
    assert not recorder.record("unknown", {}, "anything", None, schema=schema("unknown"))
    assert not recorder.record("unknown", {}, "anything", None, policy="write", schema=schema("unknown"))
    assert not recorder.record("calculate", {"callback": lambda: pytest.fail("must not execute")}, "42",
                               None, policy="read", schema=schema())
    assert recorder.payload() == {"v": 1, "groups": []}


def test_read_observation_renders_one_complete_canonical_pair_without_authority():
    group = observation(arguments={"expression": "6*7"})
    pair = render_group(group, "read", schema(), {})
    assert pair == [
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "calculate", "arguments": {"expression": "6*7"}}}
        ]},
        {"role": "tool", "tool_name": "calculate", "content": "42"},
    ]
    assert all("readable_documents" not in message for message in pair)


def test_repeated_same_tool_calls_remain_distinct_ordered_pairs():
    recorder = ToolStateRecorder()
    for expression, result in (("1+1", "2"), ("2+2", "4")):
        assert recorder.record("calculate", {"expression": expression}, result, None,
                               policy="read", schema=schema())
    groups = recorder.payload()["groups"]
    messages = [m for group in groups for m in render_group(group, "read", schema(), {})]
    assert [m["role"] for m in messages] == ["assistant", "tool", "assistant", "tool"]
    assert [m["content"] for m in messages if m["role"] == "tool"] == ["2", "4"]
    assert messages[0]["tool_calls"][0]["function"]["arguments"] == {"expression": "1+1"}
    assert messages[2]["tool_calls"][0]["function"]["arguments"] == {"expression": "2+2"}


def test_canonical_pairs_are_accepted_by_existing_anthropic_converter():
    from app.llm_clients.anthropic_client import convert_messages
    groups = [observation(arguments={"n": n}, content=str(n)) for n in (1, 2)]
    history = [{"role": "user", "content": "old request"}]
    for group in groups:
        history.extend(render_group(group, "read", schema(), {}))
    history.append({"role": "user", "content": "continue"})
    _, messages = convert_messages(history)
    calls = [block for message in messages for block in message["content"]
             if isinstance(message["content"], list) and block.get("type") == "tool_use"]
    results = [block for message in messages for block in message["content"]
               if isinstance(message["content"], list) and block.get("type") == "tool_result"]
    assert len(calls) == len(results) == 2
    assert [result["tool_use_id"] for result in results] == [call["id"] for call in calls]
    assert len({call["id"] for call in calls}) == 2


def test_changed_schema_policy_or_tool_identity_discards_the_whole_pair():
    group = observation()
    assert render_group(group, "none", schema(), {}) == []
    assert render_group(group, "receipt", schema(), {}) == []
    assert render_group(group, "read", schema(description="changed"), {}) == []
    assert render_group(group, "read", schema("different"), {}) == []


@pytest.mark.parametrize("invalid", [None, [], {}, {"function": {"name": "calculate"}},
                                     {"function": {"name": "calculate", "parameters": "bad"}}])
def test_malformed_current_tool_schema_cannot_authorize_replaying_a_group(invalid):
    recorder = ToolStateRecorder()
    assert not recorder.record("calculate", {}, "42", None, policy="read", schema=invalid)
    assert render_group(observation(), "read", invalid, {}) == []


def test_document_observations_require_matching_version_and_never_regrant_read():
    group = observation("read_document", arguments={"document_id": "doc-a"}, content="source text",
                        resources={"doc-a": "v1"})
    assert len(render_group(group, "read", schema("read_document"), {"doc-a": "v1"})) == 2
    assert render_group(group, "read", schema("read_document"), {}) == []
    assert render_group(group, "read", schema("read_document"), {"doc-a": "v2"}) == []
    assert render_group(group, "read", schema("read_document"), {"doc-a": None}) == []
    recorder = ToolStateRecorder()
    assert not recorder.record("read_document", {"document_id": "doc-a"}, "source", None,
                               policy="read", schema=schema("read_document"))
    assert not recorder.record("read_document", {"document_id": "doc-a"}, "source", None,
                               policy="read", schema=schema("read_document"), resources={"other": "v1"})


def test_a_stale_dependency_discards_even_a_multi_document_observation():
    group = observation("search_documents", content="both sources",
                        resources={"doc-a": "v1", "doc-b": "v2"})
    assert render_group(group, "read", schema("search_documents"), {"doc-a": "v1"}) == []
    assert render_group(group, "read", schema("search_documents"), {"doc-a": "v1", "doc-b": "v3"}) == []
    assert len(render_group(group, "read", schema("search_documents"), {"doc-a": "v1", "doc-b": "v2"})) == 2


@pytest.mark.parametrize("name,error,expected_status,expected_executed", [
    ("remind", None, "succeeded", True),
    ("remind", "APPROVAL_PENDING", "pending", False),
    ("remind", "TOOL_FAILED", "failed", None),
    ("ask_user", None, "asked", False),
])
def test_receipts_encode_execution_outcome_as_data_never_a_retry_instruction(
    name, error, expected_status, expected_executed,
):
    group = observation(name, content="recorded output", error=error, policy="receipt")
    pair = render_group(group, "receipt", schema(name), {})
    receipt = json.loads(pair[1]["content"])
    assert receipt["receipt"] is True
    assert receipt["status"] == expected_status
    assert receipt["executed"] is expected_executed
    assert receipt["error_code"] == error
    assert receipt["result"] == "recorded output"
    assert "retry" not in receipt


def test_missing_read_content_is_rejected_but_pending_receipt_can_have_no_result():
    recorder = ToolStateRecorder()
    assert not recorder.record("calculate", {}, None, None, policy="read", schema=schema())
    assert recorder.record("remind", {}, None, "APPROVAL_PENDING", policy="receipt", schema=schema("remind"))
    pair = render_group(recorder.payload()["groups"][0], "receipt", schema("remind"), {})
    assert json.loads(pair[1]["content"])["executed"] is False


def test_recorder_has_no_shared_state_and_defends_against_caller_mutation():
    arguments = {"expression": "6*7", "nested": ["original"]}
    recorder = ToolStateRecorder()
    assert recorder.record("calculate", arguments, "42", None, policy="read", schema=schema())
    arguments["nested"].append("later")
    payload = recorder.payload()
    assert payload["groups"][0]["arguments"]["nested"] == ["original"]
    payload["groups"].clear()
    assert len(recorder.payload()["groups"]) == 1
    assert ToolStateRecorder().payload()["groups"] == []


def test_count_limit_keeps_recent_whole_groups_in_order():
    recorder = ToolStateRecorder(ToolStateLimits(max_groups=2))
    for n in range(4):
        assert recorder.record("calculate", {"n": n}, str(n), None, policy="read", schema=schema())
    groups = recorder.payload()["groups"]
    assert [group["arguments"]["n"] for group in groups] == [2, 3]
    assert all(len(render_group(group, "read", schema(), {})) == 2 for group in groups)


def test_char_limit_drops_whole_old_groups_and_oversized_new_result_preserves_old_state():
    limits = ToolStateLimits(max_chars=700)
    recorder = ToolStateRecorder(limits)
    for n in range(5):
        assert recorder.record("calculate", {"n": n}, "X" * 120, None, policy="read", schema=schema())
    payload = recorder.payload()
    assert len(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))) <= limits.max_chars
    assert payload["groups"][-1]["arguments"]["n"] == 4
    assert all(group["content"] == "X" * 120 for group in payload["groups"])
    assert len(payload["groups"]) < 5
    assert not recorder.record("calculate", {}, "X" * 800, None, policy="read", schema=schema())
    assert recorder.payload() == payload


@pytest.mark.parametrize("change", [
    {"arguments": []}, {"arguments": {"bad": float("inf")}}, {"content": {}},
    {"schema_hash": "bogus"}, {"status": "succeeded", "error_code": "TOOL_FAILED"},
    {"resources": {"doc": None}}, {"policy": "none"}, {"name": ""},
])
def test_corrupt_persisted_group_fails_closed(change):
    group = observation()
    group.update(change)
    assert render_group(group, "read", schema(), {}) == []
    assert parse_payload({"v": 1, "groups": [group]}) == []


@pytest.mark.parametrize("value", [
    "", "{broken", "[]", {"v": True, "groups": []}, {"v": 2, "groups": []},
    {"v": 1, "groups": {}}, {"v": 1, "groups": [], "extra": "unknown"},
])
def test_invalid_or_unknown_envelopes_do_not_reach_history(value):
    assert parse_payload(value) == []


def test_payload_parse_round_trip_and_envelope_limits():
    recorder = ToolStateRecorder()
    recorder.record("calculate", {"n": 1}, "42", None, policy="read", schema=schema())
    payload = recorder.payload()
    assert parse_payload(json.dumps(payload)) == payload["groups"]
    assert parse_payload(payload, ToolStateLimits(max_chars=20)) == []
    duplicate = {"v": 1, "groups": payload["groups"] * 2}
    assert parse_payload(duplicate, ToolStateLimits(max_groups=1)) == []


def test_limits_are_immutable_and_reject_invalid_configuration():
    limits = ToolStateLimits()
    with pytest.raises(FrozenInstanceError):
        limits.max_groups = 99
    for kwargs in ({"max_chars": 0}, {"max_groups": -1}, {"max_envelopes": True}, {"max_age_seconds": 1.5}):
        with pytest.raises(ValueError):
            ToolStateLimits(**kwargs)
