"""Old tool results step aside when the prompt nears the window (ticket 44).

No database, no model, no Ollama: the router is a script that records every prompt it is sent,
and the retrieval is a fake. The properties the ticket names: the oldest result goes first, a
call always travels with its result, the note can be read back; and the one that decides
whether it may ship, that with the budget off the model is sent exactly what it was before.
"""
from __future__ import annotations

import logging

from app.services.agent_service import ANSWER_CHECK_STEP, AgentService
from app.services.context_budget import (
    KEEP_RECENT_RESULTS,
    NOTE_ARGUMENTS_CHARS,
    ContextBudget,
    ContextWindow,
    calls_have_results,
    cleared_note,
    clear_old_results,
    context_budget_from_config,
    estimate_tokens,
)
from app.services.pastes import INLINE_MAX_TOKENS

QUESTION = "Cho mình biết về nghỉ phép năm."
SYSTEM = "Bạn là trợ lý."
MARK = "đã được bỏ để nhường chỗ"


def final(text: str) -> dict:
    return {"content": text, "tool_calls": [], "raw_tool_calls": []}


def call(name: str, arguments: dict) -> dict:
    return {"content": "", "tool_calls": [{"name": name, "arguments": arguments}], "raw_tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


class Router:
    def __init__(self, rounds, reply: str = "Trả lời cuối."):
        self.rounds, self.reply = list(rounds), reply
        self.prompts: list[list[dict]] = []  # what chat_tools was sent, round by round
        self.final_prompts: list[list[dict]] = []  # what the forced answer was sent

    def chat_tools(self, role, messages, tools):
        self.prompts.append([dict(m) for m in messages])
        return self.rounds.pop(0), "fake"

    def chat(self, role, messages):
        self.final_prompts.append([dict(m) for m in messages])
        return self.reply, "fake"


class Retrieval:
    """Three chunks of ~400 characters each: a result of ~1 500 characters."""

    def retrieve(self, query, top_k, document_id=None):
        return [
            {"filename": "quy_che.pdf", "page": i + 1, "document_id": f"doc-{i}", "chunk_index": i,
             "content": f"{query} số {i}: " + "Đoạn nội dung dài về nghỉ phép năm của nhân viên. " * 12, "score": 0.9}
            for i in range(3)
        ]


class Reader:
    def read_chunks(self, document_id, from_chunk, n):
        return {"document_id": document_id, "filename": "quy_che.pdf", "total_chunks": 3, "chunks": [
            {"chunk_index": from_chunk, "page_start": 1, "page_end": 1, "content": "Mỗi nhân viên có 12 ngày phép năm."},
        ]}

    def chunks_on_page(self, document_id, page, n):
        return None


def run(rounds, *, budget=None, max_steps=4, inline=INLINE_MAX_TOKENS, reader=None):
    router = Router(rounds)
    agent = AgentService(router, Retrieval(), None, max_steps=max_steps, inline_max_tokens=inline, context_budget=budget, document_reader=reader)
    answer, _, steps = agent.run([{"role": "system", "content": SYSTEM}, {"role": "user", "content": QUESTION}])
    return router, steps, answer


def three_searches(**kwargs):
    rounds = [call("search_documents", {"query": f"hỏi {i}"}) for i in range(3)] + [final("Xong.")]
    return run(rounds, **kwargs)


def tool_contents(prompt):
    return [m["content"] for m in prompt if m["role"] == "tool"]


def squeeze() -> int:
    """A ceiling just under what the fourth prompt costs unclipped: one clearance fits it."""
    unclipped, _, _ = three_searches()
    return int(estimate_tokens(unclipped.prompts[3])) - 1


# ── off means identical ─────────────────────────────────────────────────


def test_off_the_model_is_sent_the_loops_own_list_and_nothing_is_added():
    messages = [{"role": "user", "content": "x"}]
    window = ContextWindow(None, 100)
    assert window.view(messages) is messages
    window.observe(10_000)
    assert window.view(messages) is messages and window.cleared == 0


def test_off_every_prompt_is_the_raw_conversation_even_where_the_budget_would_have_cleared():
    # The same three searches, a ceiling that forces a clearance on the last prompt.
    ceiling = squeeze()
    off, off_steps, _ = three_searches()
    # The ceiling given to an agent with no budget does nothing: inline_max_tokens is N1's alone.
    also_off, also_off_steps, _ = three_searches(inline=ceiling)
    assert also_off.prompts == off.prompts and also_off_steps == off_steps
    assert not any(MARK in text for prompt in off.prompts for text in tool_contents(prompt))
    assert all(calls_have_results(prompt) for prompt in off.prompts)
    # The shape of the old prompts, spelled out: system, guide, user, then call + result per round.
    assert [m["role"] for m in off.prompts[3]] == ["system", "system", "user", "assistant", "tool", "assistant", "tool", "assistant", "tool"]
    assert not any("context_cleared" in step for step in off_steps)


def test_on_but_under_the_ceiling_the_prompts_are_the_same_as_off():
    off, off_steps, _ = three_searches()
    on, on_steps, _ = three_searches(budget=ContextBudget(ceiling_tokens=INLINE_MAX_TOKENS))
    assert on.prompts == off.prompts and on_steps == off_steps


# ── oldest first, call with result, readable note ───────────────────────


def test_the_oldest_result_goes_first_and_only_as_many_as_needed():
    ceiling = squeeze()
    off, _, _ = three_searches()
    on, _, _ = three_searches(budget=ContextBudget(ceiling_tokens=ceiling, keep_recent=1))
    # Rounds 1-3 fit and are untouched.
    assert on.prompts[:3] == off.prompts[:3]
    first, second, third = tool_contents(off.prompts[3])
    cleared = tool_contents(on.prompts[3])
    assert MARK in cleared[0] and cleared[1:] == [second, third]
    assert len(cleared[0]) < len(first) // 4


def test_a_call_always_travels_with_its_result_nothing_removed_nothing_moved():
    ceiling = squeeze()
    off, _, _ = three_searches()
    on, _, _ = three_searches(budget=ContextBudget(ceiling_tokens=ceiling, keep_recent=1))
    for raw, cleared in zip(off.prompts, on.prompts):
        assert calls_have_results(cleared)
        assert [m["role"] for m in cleared] == [m["role"] for m in raw]
        assert [m.get("tool_calls") for m in cleared] == [m.get("tool_calls") for m in raw]
        assert [m.get("tool_name") for m in cleared] == [m.get("tool_name") for m in raw]


def test_the_newest_results_are_never_cleared_however_low_the_ceiling():
    on, _, _ = three_searches(budget=ContextBudget(ceiling_tokens=1, keep_recent=2))
    off, _, _ = three_searches()
    cleared = tool_contents(on.prompts[3])
    assert MARK in cleared[0] and cleared[1:] == tool_contents(off.prompts[3])[1:]
    # A budget that keeps more results than there are clears none.
    kept, _, _ = three_searches(budget=ContextBudget(ceiling_tokens=1, keep_recent=3))
    assert kept.prompts == off.prompts


def test_the_note_names_the_call_so_it_can_be_made_again():
    on, _, _ = three_searches(budget=ContextBudget(ceiling_tokens=squeeze(), keep_recent=1))
    note = tool_contents(on.prompts[3])[0]
    assert note == cleared_note("search_documents", {"query": "hỏi 0"})
    assert "search_documents" in note and '"query": "hỏi 0"' in note and "gọi lại" in note


def test_a_long_argument_is_cut_in_the_note():
    note = cleared_note("search_documents", {"query": "x" * 1000})
    assert len(note) < NOTE_ARGUMENTS_CHARS + 200 and "…" in note
    assert cleared_note("current_time", {}) .startswith("[Kết quả cũ của current_time đã")


def test_a_document_a_cleared_search_showed_can_still_be_read():
    # The id read_document may open is remembered for the turn, not by the result that showed it.
    rounds = [call("search_documents", {"query": "hỏi 0"}), call("search_documents", {"query": "hỏi 1"}),
              call("read_document", {"document_id": "doc-0", "from_chunk": 0, "n": 1}), final("Có 12 ngày phép.")]
    unclipped, _, _ = run(list(rounds), reader=Reader())
    ceiling = int(estimate_tokens(unclipped.prompts[3])) - 1
    router, steps, answer = run(list(rounds), reader=Reader(), budget=ContextBudget(ceiling_tokens=ceiling, keep_recent=1))
    reads = [s for s in steps if s["kind"] == "tool_result" and s["tool_name"] == "read_document"]
    assert MARK in tool_contents(router.prompts[3])[0], "the first search was cleared"
    assert "12 ngày phép" in reads[0]["content"] and "error" not in reads[0]["content"] and answer == "Có 12 ngày phép."


def test_results_no_longer_than_their_note_stay():
    messages = [
        {"role": "system", "content": "s"},
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "current_time", "arguments": {}}}]},
        {"role": "tool", "tool_name": "current_time", "content": '{"time": "09:00"}'},
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "system_status", "arguments": {}}}]},
        {"role": "tool", "tool_name": "system_status", "content": "y" * 3000},
    ]
    view, cleared = clear_old_results(messages, ContextBudget(keep_recent=1), ceiling=1)
    assert cleared == 0 and view is messages


def test_a_result_with_no_call_before_it_is_still_cleared_by_its_name():
    messages = [{"role": "tool", "tool_name": "search_documents", "content": "z" * 3000}, {"role": "tool", "tool_name": "calculate", "content": "1"}]
    view, cleared = clear_old_results(messages, ContextBudget(keep_recent=1), ceiling=1)
    assert cleared == 1 and view[0]["content"].startswith("[Kết quả cũ của search_documents đã") and view[1] is messages[1]
    assert messages[0]["content"] == "z" * 3000, "the caller's message is never written to"


def test_two_calls_in_one_round_get_their_own_notes():
    calls = [{"function": {"name": "search_documents", "arguments": {"query": "a"}}}, {"function": {"name": "calculate", "arguments": {"expression": "1+1"}}}, {"function": {"name": "x", "arguments": {}}}]
    messages = [
        {"role": "assistant", "content": "", "tool_calls": calls},
        {"role": "tool", "tool_name": "search_documents", "content": "a" * 3000},
        {"role": "tool", "tool_name": "calculate", "content": "b" * 3000},
        {"role": "tool", "tool_name": "x", "content": "c" * 3000},
    ]
    view, cleared = clear_old_results(messages, ContextBudget(keep_recent=1), ceiling=1)
    assert cleared == 2 and '"query": "a"' in view[1]["content"] and '"expression": "1+1"' in view[2]["content"] and view[3] is messages[3]
    assert calls_have_results(view)


# ── the loop around it ──────────────────────────────────────────────────


def test_the_trace_keeps_the_whole_result_and_says_how_many_were_cleared():
    off, off_steps, _ = three_searches()
    on, on_steps, _ = three_searches(budget=ContextBudget(ceiling_tokens=squeeze(), keep_recent=1))
    results = lambda steps: [s["content"] for s in steps if s["kind"] == "tool_result"]
    assert results(on_steps) == results(off_steps) and not any(MARK in text for text in results(on_steps))
    assert on_steps[-1]["context_cleared"] == 1 and on_steps[-1]["kind"] == "final"


def test_a_figure_read_in_a_cleared_result_is_not_a_reason_for_a_retry():
    # The check reads the loop's own list, not the model's view: clearing must not turn what the
    # model saw into "figures seen nowhere" and cost a round.
    rounds = [call("search_documents", {"query": "hỏi 0"}), call("search_documents", {"query": "hỏi 1"}),
              call("search_documents", {"query": "hỏi 2"}), final("Kết quả số 1 nằm ở trang 2.")]
    router, steps, answer = run(rounds, budget=ContextBudget(ceiling_tokens=1, keep_recent=1))
    assert MARK in tool_contents(router.prompts[3])[0]
    assert not any(step["kind"] == ANSWER_CHECK_STEP for step in steps) and answer == "Kết quả số 1 nằm ở trang 2."


def test_the_forced_final_answer_gets_the_same_view():
    rounds = [call("search_documents", {"query": "hỏi 0"}), call("search_documents", {"query": "hỏi 1"})]
    unclipped, _, _ = run(list(rounds), max_steps=2)
    router, steps, _ = run(list(rounds), max_steps=2, budget=ContextBudget(ceiling_tokens=1, keep_recent=1))
    [prompt] = router.final_prompts
    first, second = tool_contents(prompt)
    assert MARK in first and second == tool_contents(unclipped.final_prompts[0])[1]
    assert calls_have_results(prompt[:-1]), "all but the closing instruction"
    assert steps[-1]["context_cleared"] == 1


def test_a_budget_without_a_ceiling_takes_the_agents_own():
    # inline_max_tokens (window less the reserve) is the default ceiling.
    router, _, _ = three_searches(budget=ContextBudget(keep_recent=1), inline=1)
    assert MARK in tool_contents(router.prompts[3])[0]
    router, _, _ = three_searches(budget=ContextBudget(keep_recent=1))
    assert not any(MARK in text for prompt in router.prompts for text in tool_contents(prompt))


def test_one_agent_serves_two_turns_without_one_leaking_into_the_other():
    router = Router([call("search_documents", {"query": "hỏi 0"}), final("Một."), call("search_documents", {"query": "hỏi 0"}), final("Hai.")])
    agent = AgentService(router, Retrieval(), None, context_budget=ContextBudget(ceiling_tokens=1, keep_recent=1))
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": QUESTION}]
    agent.run(messages)
    agent.run(messages)
    assert router.prompts[0] == router.prompts[2] and router.prompts[1] == router.prompts[3]
    assert messages == [{"role": "system", "content": SYSTEM}, {"role": "user", "content": QUESTION}]


# ── the estimate ─────────────────────────────────────────────────────────


def test_the_estimate_counts_the_calls_an_assistant_message_carries():
    bare = [{"role": "assistant", "content": ""}]
    with_call = [{"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "search_documents", "arguments": {"query": "q" * 300}}}]}]
    assert estimate_tokens(with_call) - estimate_tokens(bare) > 90


def test_a_measured_reading_above_the_estimate_tightens_it_and_one_below_changes_nothing():
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "search_documents", "arguments": {"query": "a"}}}]},
        {"role": "tool", "tool_name": "search_documents", "content": "a" * 3000},
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "search_documents", "arguments": {"query": "b"}}}]},
        {"role": "tool", "tool_name": "search_documents", "content": "b" * 3000},
    ]
    estimated = estimate_tokens(messages)
    budget = ContextBudget(ceiling_tokens=int(estimated) + 10, keep_recent=1)

    window = ContextWindow(budget, 0)
    assert window.view(messages) is messages
    window.observe(int(estimated * 1.5))  # the model read more than we thought
    assert window.view(messages) is not messages and window.cleared == 1

    cached = ContextWindow(budget, 0)
    cached.view(messages)
    cached.observe(50)  # a prefix served from cache reads low: it proves nothing
    cached.observe(None)
    assert cached.view(messages) is messages and cached.cleared == 0


def test_the_estimate_cannot_be_inflated_without_limit():
    window = ContextWindow(ContextBudget(ceiling_tokens=100_000), 0)
    window.view([{"role": "user", "content": "x"}])
    window.observe(10_000_000)
    assert window._scale == 2.0


# ── the setting ──────────────────────────────────────────────────────────


def test_the_setting_is_off_unless_it_says_true():
    for section in (None, {}, {"enabled": False}, {"keep_recent": 2}, "yes", ["enabled"]):
        assert context_budget_from_config(section) is None
    assert context_budget_from_config({"enabled": True}) == ContextBudget(None, KEEP_RECENT_RESULTS)
    assert context_budget_from_config({"enabled": True, "ceiling_tokens": 9000, "keep_recent": 3}) == ContextBudget(9000, 3)


def test_a_bad_setting_leaves_the_budget_off_and_says_so_instead_of_stopping_start_up(caplog):
    with caplog.at_level(logging.WARNING, logger="app.services.context_budget"):
        for section in (
            {"enabled": "false"}, {"enabled": "yes"}, {"enabled": 1},
            {"enabled": True, "ceiling_tokens": "abc"}, {"enabled": True, "ceiling_tokens": 0},
            {"enabled": True, "ceiling_tokens": True}, {"enabled": True, "keep_recent": -1}, {"enabled": True, "keep_recent": 1.5},
        ):
            assert context_budget_from_config(section) is None, section
    assert len(caplog.records) == 8 and all("stays off" in record.getMessage() for record in caplog.records)


# ── review of d148f26 ────────────────────────────────────────────────────


def test_a_low_reading_after_a_high_one_does_not_undo_the_correction():
    # A prefix served from Ollama's cache reads low on round 2 after reading full on round 1:
    # the correction must stay, or round 3 would show again what round 2 had cleared.
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "search_documents", "arguments": {"query": "a"}}}]},
        {"role": "tool", "tool_name": "search_documents", "content": "a" * 3000},
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "search_documents", "arguments": {"query": "b"}}}]},
        {"role": "tool", "tool_name": "search_documents", "content": "b" * 3000},
    ]
    estimated = estimate_tokens(messages)
    window = ContextWindow(ContextBudget(ceiling_tokens=int(estimated) + 10, keep_recent=1), 0)
    window.view(messages)
    window.observe(int(estimated * 1.5))
    assert window.view(messages) is not messages
    window.observe(100)
    window.observe(None)
    sent = window.view(messages)
    assert sent is not messages and MARK in sent[1]["content"]
    window.observe(10_000_000)
    assert window._scale == 2.0


def anthropic_round(blocks, results):
    """An assistant message as the Anthropic client's raw_tool_calls leaves it (the whole response
    content: thinking and text blocks among the tool_use ones) and the results that answer it."""
    return [{"role": "assistant", "content": "", "tool_calls": blocks}] + [{"role": "tool", "tool_name": name, "content": text} for name, text in results]


def test_the_note_carries_the_arguments_of_an_anthropic_tool_use_block():
    blocks = [
        {"type": "thinking", "thinking": "đọc tiếp", "signature": "s"},
        {"type": "text", "text": "Để mình đọc."},
        {"type": "tool_use", "id": "toolu_1", "name": "read_document", "input": {"document_id": "doc-0", "from_chunk": 2}},
        {"type": "tool_use", "id": "toolu_2", "name": "calculate", "input": {"expression": "1+1"}},
    ]
    messages = anthropic_round(blocks, [("read_document", "r" * 3000), ("calculate", "c" * 3000)]) + [{"role": "tool", "tool_name": "x", "content": "n" * 3000}]
    view, cleared = clear_old_results(messages, ContextBudget(keep_recent=1), ceiling=1)
    assert cleared == 2
    assert view[1]["content"] == cleared_note("read_document", {"document_id": "doc-0", "from_chunk": 2})
    assert view[2]["content"] == cleared_note("calculate", {"expression": "1+1"})
    assert '"document_id": "doc-0"' in view[1]["content"]


def test_thinking_and_text_blocks_are_not_calls_waiting_for_a_result():
    blocks = [{"type": "thinking", "thinking": "…", "signature": "s"}, {"type": "text", "text": "Mình tra."},
              {"type": "tool_use", "id": "toolu_1", "name": "calculate", "input": {"expression": "2*3"}}]
    messages = anthropic_round(blocks, [("calculate", "6")])
    assert calls_have_results(messages)
    assert not calls_have_results(messages[:1]), "a tool_use with no result is still caught"
