"""Two harness ideas taken from pi, opencode and DeepSeek Harness (23/11/2026), both off by default.
No stack: fakes and a scripted model.

- agent.validate_arguments (tool_arguments.py): a call is checked against the schema the model was
  shown before it runs; an exact conversion ("4" -> 4) is made, a required key missing or a type that
  cannot be converted is refused with the arguments received, and nothing else is judged.
- agent.context_budget.keep_edges (context_budget.py): before old tool results are cleared, they are
  cut to their first and last characters; only if that is not enough are they cleared.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
from types import SimpleNamespace

import pytest

from app.services.agent_service import BAD_ARGUMENTS, AgentService, AgentTool, ToolRegistry
from app.services.context_budget import (
    EDGE_HEAD_CHARS,
    EDGE_TAIL_CHARS,
    ContextBudget,
    ContextWindow,
    calls_have_results,
    clear_old_results,
    context_budget_from_config,
    edges_kept,
    estimate_tokens,
    shrink_old_results,
)
from app.services.tool_arguments import check_arguments, refusal
from scripts.agent_eval import context_section

SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "top_k": {"type": "integer"},
        "ratio": {"type": "number"},
        "exact": {"type": "boolean"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "ids": {"type": "array", "items": {"type": "integer"}},
        "filter": {"type": "object", "properties": {"year": {"type": "integer"}}, "required": ["year"]},
        "order": {"type": "string", "enum": ["asc", "desc"]},
        "either": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
        "maybe": {"type": ["integer", "null"]},
    },
    "required": ["query"],
}


# ── conversions: exact ones only ────────────────────────────────────────


@pytest.mark.parametrize(
    ("key", "sent", "used"),
    [
        ("top_k", "4", 4), ("top_k", " 4 ", 4), ("top_k", "4.0", 4), ("top_k", 4.0, 4), ("top_k", "+7", 7),
        ("ratio", "2.5", 2.5), ("ratio", "7", 7), ("ratio", "1e3", 1000.0),
        ("exact", "true", True), ("exact", "False", False),
        ("query", 12, "12"), ("query", 2.5, "2.5"),
        ("tags", '["a", "b"]', ["a", "b"]), ("filter", '{"year": 2025}', {"year": 2025}),
        ("order", "ASC", "asc"), ("ids", ["1", 2], [1, 2]), ("maybe", "3", 3),
    ],
)
def test_an_exact_conversion_is_made_and_named(key, sent, used):
    arguments = {"query": "q", key: sent}
    checked = check_arguments(arguments, SCHEMA)
    assert checked.problems == []
    assert checked.arguments[key] == used and type(checked.arguments[key]) is type(used)
    assert checked.coerced and checked.coerced[0].startswith(key)
    assert arguments[key] == sent  # the model's own arguments are never changed


def test_a_long_whole_number_stays_exact():
    checked = check_arguments({"query": "q", "top_k": "12345678901234567890"}, SCHEMA)
    assert checked.arguments["top_k"] == 12345678901234567890


def test_values_of_the_right_type_are_left_alone_and_nothing_is_counted():
    arguments = {"query": "q", "top_k": 4, "ratio": 1, "exact": True, "tags": ["x"], "filter": {"year": 2025}, "order": "asc", "maybe": None}
    checked = check_arguments(arguments, SCHEMA)
    assert checked.arguments == arguments and checked.problems == [] and checked.coerced == []


# ── refusals: what the tool could not run with ──────────────────────────


@pytest.mark.parametrize(
    ("arguments", "problem"),
    [
        ({}, "thiếu `query` (bắt buộc)"),
        ({"query": None}, "thiếu `query` (bắt buộc)"),
        ({"query": "q", "top_k": "năm"}, '`top_k` phải là số nguyên, nhận "năm"'),
        ({"query": "q", "top_k": "4.5"}, "`top_k` phải là số nguyên"),
        ({"query": "q", "top_k": True}, "`top_k` phải là số nguyên, nhận true"),
        ({"query": "q", "exact": "có"}, "`exact` phải là true hoặc false"),
        ({"query": "q", "ids": [1, "hai"]}, "`ids[1]` phải là số nguyên"),
        ({"query": "q", "filter": {}}, "thiếu `filter.year` (bắt buộc)"),
        ({"query": "q", "tags": "a, b"}, "`tags` phải là danh sách"),
        ({"query": "q", "ratio": "nan"}, "`ratio` phải là số"),
    ],
)
def test_what_cannot_be_converted_is_refused_by_name(arguments, problem):
    checked = check_arguments(arguments, SCHEMA)
    assert any(text.startswith(problem) for text in checked.problems), checked.problems


def test_a_missing_key_is_reported_once():
    assert check_arguments({"query": None}, SCHEMA).problems == ["thiếu `query` (bắt buộc)"]


def test_the_refusal_names_each_problem_and_what_was_received():
    sent = {"top_k": "năm", "note": "x" * 1000}
    text = refusal("search_documents", check_arguments(sent, SCHEMA), sent)
    assert text.startswith("Tham số của search_documents chưa đúng nên chưa chạy: thiếu `query` (bắt buộc); `top_k` phải là số nguyên")
    assert 'Đã nhận: {"top_k": "năm"' in text and "Gọi lại search_documents" in text
    assert len(text) < 600  # the received arguments are shown cut short


# ── let through: what this does not judge ───────────────────────────────


def test_what_the_schema_does_not_say_is_let_through():
    arguments = {"query": "q", "extra": {"x": 1}, "either": [1, 2], "order": "newest", "top_k": None}
    checked = check_arguments(arguments, SCHEMA)
    # An undeclared key, a union it does not read, an enum value not shown (an MCP list is cut short),
    # an optional key sent as null: all as they were, none refused.
    assert checked.arguments == arguments and checked.problems == [] and checked.coerced == []


@pytest.mark.parametrize("parameters", [None, {}, {"type": "object"}, {"type": "object", "properties": "x"}])
def test_a_schema_without_properties_checks_nothing(parameters):
    assert check_arguments({"a": "1"}, parameters).problems == []


def test_arguments_that_are_not_an_object_are_left_to_the_tool():
    checked = check_arguments("query=q", SCHEMA)
    assert checked.problems == [] and checked.arguments == {}


# ── in the loop ─────────────────────────────────────────────────────────


def final(text: str) -> dict:
    return {"content": text, "tool_calls": [], "raw_tool_calls": []}


def call(name: str, arguments: dict) -> dict:
    return {"content": "", "tool_calls": [{"name": name, "arguments": arguments}], "raw_tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


class Router:
    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.prompts: list[list[dict]] = []

    def chat_tools(self, role, messages, tools):
        self.prompts.append([dict(message) for message in messages])
        return self.rounds.pop(0), "fake"

    def chat(self, role, messages):
        return "hết lượt", "fake"


class Retrieval:
    def __init__(self):
        self.calls: list[tuple[str, object]] = []

    def retrieve(self, query, top_k, document_id=None):
        self.calls.append((query, top_k))
        return [{"filename": "quy_dinh.pdf", "page": 2, "content": "Phụ cấp lưu trú là 300.000 đồng.", "score": 0.9}]


def run(rounds, **kwargs):
    retrieval = Retrieval()
    agent = AgentService(Router(rounds), retrieval, None, **kwargs)
    _, _, steps = agent.run([{"role": "user", "content": "Phụ cấp lưu trú bao nhiêu?"}])
    return retrieval, steps


def first(steps, kind):
    return next(step for step in steps if step["kind"] == kind)


def test_off_a_call_runs_as_it_always_did():
    retrieval, steps = run([call("search_documents", {"query": "phụ cấp", "top_k": "năm"}), final("300.000 đồng.")])
    # The tool's own lenient reading: an unreadable top_k is its default, and nothing is refused.
    assert retrieval.calls == [("phụ cấp", 4)]
    assert first(steps, "tool_result")["error_code"] is None
    assert "_coerced" not in first(steps, "tool_call")["arguments_shape"]


def test_on_a_converted_value_runs_and_the_trace_keeps_what_the_model_wrote():
    retrieval, steps = run([call("search_documents", {"query": "phụ cấp", "top_k": "3"}), final("300.000 đồng.")], validate_arguments=True)
    assert retrieval.calls == [("phụ cấp", 3)]
    step = first(steps, "tool_call")
    assert step["arguments"] == {"query": "phụ cấp", "top_k": "3"}
    assert step["arguments_shape"]["_coerced"] == 1 and "_invalid" not in step["arguments_shape"]


def test_on_a_call_missing_its_query_is_refused_before_it_runs():
    retrieval, steps = run([call("search_documents", {"top_k": 2}), final("Không rõ.")], validate_arguments=True)
    assert retrieval.calls == []
    result = first(steps, "tool_result")
    assert result["error_code"] == BAD_ARGUMENTS
    error = json.loads(result["content"])["error"]
    assert "thiếu `query` (bắt buộc)" in error and 'Đã nhận: {"top_k": 2}' in error
    assert first(steps, "tool_call")["arguments_shape"]["_invalid"] == 1


def test_on_a_call_with_wrong_arguments_never_reaches_the_person_who_approves():
    registry = ToolRegistry()
    schema = {"type": "function", "function": {"name": "write_file", "description": "ghi tệp", "parameters": {
        "type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}}
    registry.register(AgentTool(schema, lambda *a: pytest.fail("an approval tool never runs from the loop"), requires_approval=True), 10)
    agent = AgentService(Router([call("write_file", {"path": "a.txt"}), final("Chưa ghi được.")]), Retrieval(), None,
                         registry=registry, validate_arguments=True)
    agent.approvals = SimpleNamespace(request=lambda *a: pytest.fail("a call with a missing argument was sent for approval"))
    _, _, steps = agent.run([{"role": "user", "content": "Ghi tệp a.txt"}])
    assert first(steps, "tool_result")["error_code"] == BAD_ARGUMENTS


# ── keep_edges ──────────────────────────────────────────────────────────


def conversation(sizes: list[int]) -> list[dict]:
    """A system and a user message, then one call and its result per size, each result a run of
    distinct lines so that a head and a tail can be told apart."""
    messages = [{"role": "system", "content": "Bạn là trợ lý."}, {"role": "user", "content": "Hỏi."}]
    for index, size in enumerate(sizes):
        body = f"<đầu {index}>" + "".join(f"dòng {line} " for line in range(size))[: size - 20] + f"<đuôi {index}>"
        messages.append({"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "search_documents", "arguments": {"query": f"hỏi {index}"}}}]})
        messages.append({"role": "tool", "tool_name": "search_documents", "content": body})
    return messages


def results(messages):
    return [message["content"] for message in messages if message["role"] == "tool"]


def test_edges_keep_the_head_and_the_tail_with_a_note_between():
    content = "A" * 1000 + "B" * 3000 + "C" * 500
    cut = edges_kept(content, "read_document", {"document_id": "d1"})
    assert cut.startswith("A" * EDGE_HEAD_CHARS) and cut.endswith("C" * EDGE_TAIL_CHARS)
    assert f"Đã bỏ {len(content) - EDGE_HEAD_CHARS - EDGE_TAIL_CHARS} ký tự ở giữa kết quả cũ của read_document" in cut
    assert '{"document_id": "d1"}' in cut and len(cut) < len(content)


def test_a_result_too_short_to_free_anything_is_not_cut():
    assert edges_kept("x" * (EDGE_HEAD_CHARS + EDGE_TAIL_CHARS + 100), "search_documents", {"query": "q"}) is None


def test_without_keep_edges_shrinking_is_clearing_exactly():
    messages = conversation([3000, 3000, 3000, 3000])
    for ceiling in (1, int(estimate_tokens(messages)) - 300, int(estimate_tokens(messages)) + 10):
        cleared_view, cleared = clear_old_results(messages, ContextBudget(keep_recent=1), ceiling)
        shrunk_view, shrunk, trimmed = shrink_old_results(messages, ContextBudget(keep_recent=1), ceiling)
        assert (shrunk_view, shrunk, trimmed) == (cleared_view, cleared, 0)


def test_clear_old_results_clears_only_whatever_the_budget_says():
    messages = conversation([3000, 3000, 3000])
    assert clear_old_results(messages, ContextBudget(keep_recent=1, keep_edges=True), 1) == clear_old_results(messages, ContextBudget(keep_recent=1), 1)


def test_with_keep_edges_the_oldest_result_is_cut_before_anything_is_cleared():
    messages = conversation([3000, 3000, 3000])
    original = [dict(message) for message in messages]
    once = list(messages)
    once[3] = {**once[3], "content": edges_kept(once[3]["content"], "search_documents", {"query": "hỏi 0"})}
    ceiling = math.ceil(estimate_tokens(once))
    assert estimate_tokens(messages) > ceiling
    view, cleared, trimmed = shrink_old_results(messages, ContextBudget(keep_recent=1, keep_edges=True), ceiling)
    assert (cleared, trimmed) == (0, 1)
    old, middle, newest = results(view)
    assert old.startswith("<đầu 0>") and old.endswith("<đuôi 0>") and "Đã bỏ" in old
    assert middle == results(messages)[1] and newest == results(messages)[2]
    # A view: the loop's own list is never written to.
    assert calls_have_results(view) and messages == original


def test_with_keep_edges_results_are_cleared_oldest_first_only_when_cutting_all_is_not_enough():
    messages = conversation([3000, 3000, 3000, 3000])
    view, cleared, trimmed = shrink_old_results(messages, ContextBudget(keep_recent=1, keep_edges=True), 1)
    shown = results(view)
    # A ceiling nothing reaches: every old result is cleared, the newest is untouched, nothing is left cut.
    assert (cleared, trimmed) == (3, 0)
    assert all("đã được bỏ để nhường chỗ" in text for text in shown[:3]) and shown[3] == results(messages)[3]
    # A ceiling that clearing the oldest reaches once the others are cut: one cleared, two cut.
    all_cut = list(messages)
    for index in (3, 5, 7):
        all_cut[index] = {**all_cut[index], "content": edges_kept(all_cut[index]["content"], "search_documents", {"query": "x"})}
    view, cleared, trimmed = shrink_old_results(messages, ContextBudget(keep_recent=1, keep_edges=True), math.ceil(estimate_tokens(all_cut)) - 100)
    shown = results(view)
    assert (cleared, trimmed) == (1, 2)
    assert "đã được bỏ để nhường chỗ" in shown[0] and "Đã bỏ" in shown[1] and "Đã bỏ" in shown[2]
    assert calls_have_results(view)


def test_the_window_reports_cut_results_in_the_trace_and_nothing_when_off():
    messages = conversation([3000, 3000, 3000])
    window = ContextWindow(ContextBudget(keep_recent=1, keep_edges=True), 1)
    window.view(messages)
    assert window.trace() == {"context_cleared": 2}
    once = list(messages)
    once[3] = {**once[3], "content": edges_kept(once[3]["content"], "search_documents", {"query": "hỏi 0"})}
    window = ContextWindow(ContextBudget(keep_recent=1, keep_edges=True), math.ceil(estimate_tokens(once)))
    window.view(messages)
    assert window.trace() == {"context_trimmed": 1}
    assert ContextWindow(None, 1).trace() == {}


def test_keep_edges_is_read_from_the_config_and_a_wrong_value_leaves_only_it_out(caplog):
    assert context_budget_from_config({"enabled": True}).keep_edges is False
    assert context_budget_from_config({"enabled": True, "keep_edges": True}).keep_edges is True
    with caplog.at_level(logging.WARNING):
        budget = context_budget_from_config({"enabled": True, "keep_edges": "yes"})
    assert budget is not None and budget.keep_edges is False and "keep_edges" in caplog.text


def test_the_eval_flag_turns_the_budget_and_the_edges_on():
    args = argparse.Namespace(context_budget=False, context_ceiling=None, context_keep_edges=True)
    assert context_section({"context_budget": {"enabled": False, "keep_recent": 2}}, args) == {"enabled": True, "keep_recent": 2, "keep_edges": True}
    args = argparse.Namespace(context_budget=True, context_ceiling=None, context_keep_edges=False)
    assert "keep_edges" not in context_section({}, args)
