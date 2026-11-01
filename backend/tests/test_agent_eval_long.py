"""The v0-long dataset of Agent Eval (tickets 44 and 45): that it loads, that the geometry the tasks
promise is the geometry they have, and that the grader passes the sample answer and fails the
near-miss one. No model, no GPU, no database: the router is scripted at the ModelRouter seam.

The pastes (end-NN) are read with the real chunker and the real read_document; the conversations
(ctx-NN) are run through the real AgentService with and without a context budget to see that the
ideal path overflows the window, which is what makes them tasks for ticket 44.
"""
from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pytest

from app.services.agent_service import READ_MAX_CHUNKS, READ_RESULT_MAX_CHARS
from app.services.context_budget import ContextBudget, estimate_tokens
from app.services.long_input import part_chars, split_parts
from app.services.pastes import INLINE_MAX_TOKENS, PASTE_MAX, SLIP_EDGE_CHARS, _chunks, paste_id, prompt_tokens
from scripts import agent_eval_build_long as builder
from scripts.agent_eval import DATASET_DIR, SYSTEM_PROMPT_PATH, build_messages, load_dataset, run_eval
from scripts.agent_eval_grader import _matches
from app.services.injection_defense import InjectionDefense
from tests.test_agent_eval import ScriptedRouter, _jsonl, final

LONG_DIR = DATASET_DIR.parent / "v0-long"
DATASET = load_dataset(LONG_DIR)
TASKS = {task["id"]: task for task in DATASET.tasks}
PASTE_IDS = [spec["id"] for spec in builder.PASTES]
SINGLE_IDS = [spec["id"] for spec in builder.SINGLES]
QUOTE_IDS = [spec["id"] for spec in builder.QUOTES]
CTX_IDS = SINGLE_IDS + QUOTE_IDS


def multi(*calls: tuple[str, dict]) -> dict:
    """One model turn that makes several tool calls at once."""
    return {
        "content": "",
        "tool_calls": [{"name": name, "arguments": arguments} for name, arguments in calls],
        "raw_tool_calls": [{"function": {"name": name, "arguments": arguments}} for name, arguments in calls],
    }


def run_one(tmp_path: Path, task: dict, router, **agent_config):
    out_dir = tmp_path / "run"
    run_eval(
        dataclasses.replace(DATASET, tasks=[task]),
        router,
        out_dir=out_dir,
        agent_config={"max_steps": 3, "tool_result_max_chars": 2400, **agent_config},
        defense=InjectionDefense(enabled=True),
        system_prompt=SYSTEM_PROMPT_PATH.read_text(encoding="utf-8"),
        run_meta={"run_id": "t", "seed": "không seed", "temperature": 0.0},
        progress=lambda line: None,
    )
    [result] = _jsonl(out_dir / "task_results.jsonl")
    return out_dir, result


# --- the files -----------------------------------------------------------------------------

def test_the_files_on_disk_are_what_the_builder_writes():
    for name, text in builder.build().items():
        assert (LONG_DIR / name).read_bytes().replace(b"\r\n", b"\n") == text.encode("utf-8"), name


def test_it_is_a_dataset_of_its_own_and_v0_is_untouched():
    old = load_dataset(DATASET_DIR)
    assert DATASET.version == "agent-eval-v0-long.1" != old.version
    assert len(DATASET.tasks) == 14 and set(TASKS) == set(CTX_IDS + PASTE_IDS)
    assert len(old.tasks) == 66 and not set(TASKS) & {task["id"] for task in old.tasks}
    assert DATASET.sha256 != old.sha256
    assert len(PASTE_IDS) in range(6, 9) and len(CTX_IDS) in range(6, 15)


# --- ticket 45: the answer is at the end of a very long paste --------------------------------

@pytest.mark.parametrize("task_id", PASTE_IDS)
def test_a_paste_is_past_what_n1_reads_whole_and_its_answer_is_in_the_last_part_beyond_the_slip(task_id):
    task = TASKS[task_id]
    text, question = task["input"], next(s for s in builder.PASTES if s["id"] == task_id)["question"]
    assert 40_000 <= len(text) < PASTE_MAX
    assert prompt_tokens(build_messages(task, SYSTEM_PROMPT_PATH.read_text(encoding="utf-8"))) > INLINE_MAX_TOKENS + 1_000, "the window cannot take it whole"
    spans = split_parts(text, part_chars(INLINE_MAX_TOKENS))
    assert len(spans) >= 2
    shown = text[:SLIP_EDGE_CHARS] + "\n" + text[-SLIP_EDGE_CHARS:]
    for pattern in task["expect"]["must_mention"]:
        found = [m for m in re.finditer(pattern, text, re.IGNORECASE)]
        assert len(found) == 1, f"{pattern!r} matches {len(found)} times"
        assert not re.search(pattern, question, re.IGNORECASE) and not re.search(pattern, shown, re.IGNORECASE), "not in the question, not in the slip"
        at = found[0].start()
        assert at >= 0.85 * len(text) and at <= len(text) - 1_200, f"{at / len(text):.2f} of the text"
        assert spans[-1][0] <= at, "in the last part the reading pass cuts"
    assert text.count(question) == 1


@pytest.mark.parametrize("task_id", PASTE_IDS)
def test_reading_on_from_chunk_0_three_rounds_never_arrives_but_a_direct_read_does(task_id):
    task = TASKS[task_id]
    text = task["input"]
    chunks = _chunks(text)
    first = [i for i, chunk in enumerate(chunks) if any(re.search(p, chunk, re.IGNORECASE) for p in task["expect"]["must_mention"])]
    assert first and all(i >= 3 * 3 for i in first), f"answer chunks {first} of {len(chunks)}: nine chunks of sequential reading do not reach them"


@pytest.mark.parametrize("task_id", PASTE_IDS)
def test_the_sample_answer_passes_and_the_near_miss_fails_after_the_direct_reads(tmp_path, task_id):
    spec = next(s for s in builder.PASTES if s["id"] == task_id)
    task = TASKS[task_id]
    chunks = _chunks(task["input"])
    wanted = sorted({i for i, chunk in enumerate(chunks) if any(re.search(p, chunk, re.IGNORECASE) for p in task["expect"]["must_mention"])})
    reads = [("read_document", {"document_id": paste_id(task["input"]), "from_chunk": max(0, i - 1), "n": READ_MAX_CHUNKS}) for i in wanted]
    outcome = {}
    for name, answer in {"good": spec["good"], "bad": spec["bad"]}.items():
        out_dir, outcome[name] = run_one(tmp_path / name, task, ScriptedRouter([multi(*reads), final(answer)]))
    assert outcome["good"]["passed"] is True, outcome["good"]["grade"]
    assert outcome["bad"]["passed"] is False
    # The read result is what carried the answer: it holds every pattern.
    reads_text = " ".join(e["content"] for e in _jsonl(tmp_path / "good" / "run" / "events.jsonl") if e["kind"] == "tool_result")
    assert all(re.search(p, reads_text, re.IGNORECASE) for p in task["expect"]["must_mention"])


# --- ticket 44: the tool results of one turn do not fit the window --------------------------

def docs_of(task_id: str) -> list[dict]:
    return [d for d in DATASET.documents.values() if d["document_id"].startswith(f"long-{task_id}")]


@pytest.mark.parametrize("task_id", CTX_IDS)
def test_documents_have_chunks_of_the_promised_size_and_every_read_fits_the_read_cap(task_id):
    for doc in docs_of(task_id):
        sizes = [len(chunk["content"]) for chunk in doc["chunks"]]
        assert all(builder.CHUNK_MIN <= size <= builder.CHUNK_MAX for size in sizes), sizes
        assert all(sum(sizes[i : i + READ_MAX_CHUNKS]) <= READ_RESULT_MAX_CHARS for i in range(len(sizes))), "a read of three chunks is not cut"


@pytest.mark.parametrize("task_id", CTX_IDS)
def test_each_answer_pattern_is_in_one_chunk_past_the_preview_and_not_in_the_question_or_history(task_id):
    task = TASKS[task_id]
    chunks = [(doc["document_id"], chunk) for doc in docs_of(task_id) for chunk in doc["chunks"]]
    assert task["history"] and all(m["role"] in ("user", "assistant") for m in task["history"])
    for pattern in task["expect"]["must_mention"]:
        hits = [(doc, chunk) for doc, chunk in chunks if re.search(pattern, chunk["content"], re.IGNORECASE)]
        # A supplier's name stands in both of its two facts; every figure and every other name in one place.
        assert len(hits) == (2 if task_id in QUOTE_IDS and not re.search(r"\d", pattern) else 1), f"{pattern!r}: {len(hits)} chunks"
        assert all(re.search(pattern, chunk["content"], re.IGNORECASE).start() >= 500 for _, chunk in hits), "beyond the 400-character preview"
        assert not re.search(pattern, task["input"], re.IGNORECASE)
        assert not any(re.search(pattern, m["content"], re.IGNORECASE) for m in task["history"]), "the history does not hold the answer"


def test_the_single_document_facts_are_three_or_more_chunks_apart_and_the_quotes_need_six_reads():
    for spec in builder.SINGLES:
        at = sorted(spec["plants"])
        assert len(at) == 3 and all(b - a >= READ_MAX_CHUNKS for a, b in zip(at, at[1:])), "no read of three chunks holds two facts"
    for spec in builder.QUOTES:
        price, delivery = spec.get("price_chunk", 1), spec.get("delivery_chunk", 6)
        assert delivery - price >= READ_MAX_CHUNKS and len(spec["suppliers"]) == 3


def ideal_path(task_id: str, answer: str) -> list[dict]:
    """The shortest correct turn: one search, every needed read in one round, then the answer."""
    docs = docs_of(task_id)
    if task_id in SINGLE_IDS:
        spec = next(s for s in builder.SINGLES if s["id"] == task_id)
        reads = [("read_document", {"document_id": docs[0]["document_id"], "from_chunk": max(0, i - 1), "n": READ_MAX_CHUNKS}) for i in sorted(spec["plants"])]
    else:
        spec = next(s for s in builder.QUOTES if s["id"] == task_id)
        reads = [
            ("read_document", {"document_id": doc["document_id"], "from_chunk": max(0, at - 1), "n": READ_MAX_CHUNKS})
            for doc in docs
            for at in (spec.get("price_chunk", 1), spec.get("delivery_chunk", 6))
        ]
    return [multi(("search_documents", {"query": TASKS[task_id]["input"]})), multi(*reads), final(answer)]


def sample_answers(task_id: str) -> tuple[str, str]:
    if task_id in SINGLE_IDS:
        spec = next(s for s in builder.SINGLES if s["id"] == task_id)
        return spec["good"], spec["bad"]
    spec = next(s for s in builder.QUOTES if s["id"] == task_id)
    cheap, fast = spec["suppliers"][spec["cheapest"]], spec["suppliers"][spec["fastest"]]
    good = f"{cheap[0]} rẻ nhất, {cheap[2]} đồng một cái. {fast[0]} giao nhanh nhất, {fast[3]} ngày làm việc."
    other = next(s for s in spec["suppliers"] if s not in (cheap, fast))
    bad = f"{other[0]} rẻ nhất, {other[2]} đồng một cái, và giao nhanh nhất, {other[3]} ngày làm việc."
    return good, bad


class Watching(ScriptedRouter):
    """Records the estimate of every prompt it is shown."""

    def __init__(self, turns):
        super().__init__(turns)
        self.estimates: list[float] = []
        self.sent: list[list[dict]] = []

    def chat_tools(self, mode, messages, tools):
        self.estimates.append(estimate_tokens(messages))
        self.sent.append([dict(m) for m in messages])
        return super().chat_tools(mode, messages, tools)


@pytest.mark.parametrize("task_id", CTX_IDS)
def test_the_ideal_path_passes_with_no_budget_and_its_last_prompt_is_over_the_ceiling(tmp_path, task_id):
    good, bad = sample_answers(task_id)
    router = Watching(ideal_path(task_id, good))
    _, result = run_one(tmp_path / "good", TASKS[task_id], router)
    assert result["passed"] is True, result["grade"]
    assert len(router.estimates) == 3 and router.estimates[-1] > INLINE_MAX_TOKENS, router.estimates
    assert router.estimates[0] < INLINE_MAX_TOKENS < router.estimates[-1], "the history alone fits; the tool results are what overflow it"
    _, near_miss = run_one(tmp_path / "bad", TASKS[task_id], Watching(ideal_path(task_id, bad)))
    assert near_miss["passed"] is False


@pytest.mark.parametrize("task_id", CTX_IDS)
def test_with_a_budget_the_oldest_results_are_cleared_before_the_last_round(tmp_path, task_id):
    good, _ = sample_answers(task_id)
    router = Watching(ideal_path(task_id, good))
    out_dir, _ = run_one(tmp_path, TASKS[task_id], router, context_budget=ContextBudget())
    cleared = [m for m in router.sent[-1] if m.get("role") == "tool" and str(m["content"]).startswith("[Kết quả cũ của")]
    assert cleared, "something was cleared"
    final_step = next(e for e in _jsonl(out_dir / "events.jsonl") if e["kind"] == "final")
    assert final_step.get("context_cleared", 0) >= 1
