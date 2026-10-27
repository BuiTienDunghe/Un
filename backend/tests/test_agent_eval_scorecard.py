"""Agent Eval scorecard (ticket 23): every metric on small hand-built runs, one
written the way the harness recorded turns before ticket 16 and one after."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.agent_eval_scorecard import (
    Incomparable,
    append_history,
    compare,
    condition,
    scorecard,
)

PASS_CITED = {"check": "citation", "passed": True, "detail": "", "verbatim": True}
FAIL_NOT_FOUND = {"check": "not_found", "passed": False, "detail": ""}


def result(task_id: str, passed: bool, *, calls: int = 1, rounds: int = 2, latency: int = 1000, checks=(), error=None, category="documents", answer=None):
    return {
        "task_id": task_id, "category": category, "surface": "web", "passed": passed, "answer": answer or f"đáp án {task_id}",
        "model": "qwen3.5:9b", "error": error, "tool_calls": [{"name": "search_documents", "arguments": {"query": "q"}}] * calls,
        "model_rounds": rounds, "budget_exhausted": False, "tokens_in": 1000 * rounds if rounds else None,
        "tokens_out": 100 * rounds if rounds else None, "latency_ms": latency, "retrieval_source": None,
        "grade": {"passed": passed, "checks": [{"check": "completed", "passed": error is None, "detail": ""}, *checks]},
    }


def turn(task_id: str, *, after_16: bool, error_code=None, omitted=False):
    """One tool round then the answer, as events.jsonl records it."""
    call = {"task_id": task_id, "kind": "tool_call", "tool_name": "search_documents", "arguments": {"query": "q"}, "content": None, "latency_ms": 900}
    content = '{"omitted": 2, "items": []}' if omitted else ('{"error": "x", "code": "%s"}' % error_code if error_code else '{"items": []}')
    reply = {"task_id": task_id, "kind": "tool_result", "tool_name": "search_documents", "arguments": None, "content": content, "latency_ms": 5}
    final = {"task_id": task_id, "kind": "final", "tool_name": None, "arguments": None, "content": "đáp án", "latency_ms": 800}
    if after_16:
        call |= {"tool_declared": True, "arguments_shape": {"query": "str:1"}}
        reply |= {"tool_declared": True, "error_code": error_code, "error_type": None}
        final |= {"stop_reason": "final"}
    rounds = [{"task_id": task_id, "kind": "model_round", "round_index": i, "call": "chat_tools", "tokens_in": 1000, "tokens_out": 100, "latency_ms": 900} for i in range(2)]
    return [call, reply, final, *rounds]


def write_run(directory: Path, results, events, **manifest) -> Path:
    directory.mkdir(parents=True)
    meta = {"run_id": directory.name, "commit": "abc1234", "worktree_dirty": False, "model": "qwen3.5:9b", "temperature": 0.0, "seed": 42,
            "grader_version": "agent-eval-grader-v0.3", "dataset": {"version": "agent-eval-v0.3", "sha256": "d" * 64}, "started_at": "2026-10-28T00:00:00", **manifest}
    (directory / "manifest.json").write_text(json.dumps(meta), encoding="utf-8")
    (directory / "task_results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in results), encoding="utf-8")
    if events is not None:
        (directory / "events.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8")
    return directory


def after_16_run(tmp_path, name="after", **manifest):
    results = [
        result("doc-1", True, latency=900, checks=[PASS_CITED]),
        result("doc-2", False, calls=2, latency=3000, checks=[FAIL_NOT_FOUND]),
        result("hist-1", True, latency=1500, category="history"),
        # Refused before the agent ran, as the API refuses an over-long message.
        result("doc-3", False, calls=0, rounds=0, latency=0, error="INPUT_TOO_LONG: 10164 > 10000"),
    ]
    events = (turn("doc-1", after_16=True) + turn("doc-2", after_16=True, error_code="BAD_ARGUMENTS")
              + turn("doc-2", after_16=True, omitted=True)[:2] + turn("hist-1", after_16=True, error_code="TOOL_UNAVAILABLE_HERE"))
    return write_run(tmp_path / name, results, events, **manifest)


def test_correctness_counts_fabrication_only_where_a_negative_criterion_exists(tmp_path):
    card = scorecard(after_16_run(tmp_path))
    c = card["correctness"]
    assert (c["passed"], c["tasks"], c["pass_rate"]) == (2, 4, 0.5)
    assert c["by_category"]["history"] == {"passed": 1, "tasks": 1, "pass_rate": 1.0}
    assert c["fabricated_tasks"] == ["doc-2"]
    assert (c["citation_passed"], c["citation_tasks"], c["citation_verbatim"]) == (1, 1, 1)


def test_efficiency_leaves_out_the_refused_turn_and_prices_calls_per_solved_task(tmp_path):
    e = scorecard(after_16_run(tmp_path))["efficiency"]
    assert e["tasks_ran"] == 3, "the INPUT_TOO_LONG task never reached the model"
    assert (e["tokens_in_mean"], e["model_rounds_mean"]) == (2000, 2.0)
    # 4 calls over every task, 2 tasks solved: 2 calls per success; the solved ones alone made 1 each.
    assert (e["tool_calls"], e["tool_calls_per_solved"], e["tool_calls_mean_of_solved"]) == (4, 2.0, 1.0)
    # Nearest rank over 900, 1500, 3000.
    assert (e["latency_p50_ms"], e["latency_p95_ms"], e["latency_max_ms"]) == (1500, 3000, 3000)


def test_robustness_reads_codes_after_ticket_16_and_counts_uncoded_errors_before(tmp_path):
    r = scorecard(after_16_run(tmp_path))["robustness"]
    assert r["stop_reasons"] == {"final": 3, "max_steps": 0, "turn_budget": 0, "turn_budget_exhausted": 0}
    assert r["max_steps_matches_budget_exhausted"] is True
    assert r["tool_error_codes"] == {"BAD_ARGUMENTS": 1, "TOOL_UNAVAILABLE_HERE": 1} and r["tool_errors_uncoded"] is None
    assert r["bad_arguments_rate"] == 0.25 and r["results_trimmed_by_item"] == 1
    assert r["task_errors"] == {"INPUT_TOO_LONG": 1}

    before = write_run(tmp_path / "before", [result("doc-1", True)], turn("doc-1", after_16=False, error_code="X"))
    old = scorecard(before)["robustness"]
    assert old["stop_reasons"] is None and "trước ticket 16" in old["stop_reasons_unavailable"]
    assert old["tool_error_codes"] is None and old["tool_errors_uncoded"] == 1 and old["bad_arguments_rate"] is None


def test_traceability_is_complete_only_with_every_field_and_says_why_per_part(tmp_path):
    t = scorecard(after_16_run(tmp_path))["traceability"]
    assert (t["turns"], t["complete"], t["complete_rate"]) == (3, 3, 1.0)

    before = write_run(tmp_path / "before", [result("doc-1", True)], turn("doc-1", after_16=False))
    old = scorecard(before)["traceability"]
    assert old["complete"] == 0
    assert old["parts"] == {"rounds_timed_and_counted": 1, "calls_named_and_shaped": 0, "calls_answered": 1, "final_has_stop_reason": 0}

    no_events = write_run(tmp_path / "no-events", [result("doc-1", True)], None)
    assert scorecard(no_events)["traceability"] == {"unavailable": "không có events.jsonl"}
    assert scorecard(no_events)["robustness"]["unavailable"] == "không có events.jsonl"


def test_cold_comes_from_the_loaded_models_and_gpu_sharing_only_from_a_declaration():
    manifest = {"model": "qwen3.5:9b", "ollama_loaded_at_start": ["qwen3-embedding:0.6b"], "gpu_shared": False}
    assert condition(manifest)["cold"] is True and condition(manifest)["gpu_shared"] is False
    assert condition({**manifest, "ollama_loaded_at_start": ["qwen3.5:9b"]})["cold"] is False
    recorded = {"loaded_at_start": None, "cold": True, "source": "REPORT v0.1", "gpu_shared": True}
    old = condition({"model": "qwen3.5:9b"}, recorded)
    assert (old["cold"], old["source"], old["gpu_shared"]) == (True, "REPORT v0.1", True)
    assert condition({"model": "qwen3.5:9b"})["cold"] is None, "never guessed"


def test_compare_refuses_two_datasets_and_marks_flips_after_the_first_divergence(tmp_path):
    a = after_16_run(tmp_path, "a", gpu_shared=False)
    other = after_16_run(tmp_path, "other", dataset={"version": "agent-eval-v0.2", "sha256": "e" * 64})
    with pytest.raises(Incomparable, match="chỉ so khi cùng dataset"):
        compare(a, other)

    results = [json.loads(line) for line in (a / "task_results.jsonl").read_text(encoding="utf-8").splitlines()]
    results[0]["answer"] = "khác"  # doc-1 diverges first
    results[2]["passed"] = False   # hist-1 flips after it
    b = write_run(tmp_path / "b", results, None, gpu_shared=True)
    text = compare(a, b)
    assert "Câu trả lời khác nhau đầu tiên: doc-1." in text
    assert "- hist-1: đạt → trượt (sau chỗ khác đầu tiên: chỉ tham khảo)" in text
    assert "không so: GPU dùng chung False / True" in text, "latency of a shared card is not compared"


def test_history_keeps_one_line_per_run_and_commit(tmp_path):
    run = after_16_run(tmp_path)
    history = tmp_path / "history.jsonl"
    append_history(scorecard(run), run, history)
    append_history(scorecard(run), run, history)
    lines = [json.loads(line) for line in history.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 1 and lines[0]["run_id"] == "after" and lines[0]["correctness.pass_rate"] == 0.5
    assert lines[0]["dataset_sha256"] == "d" * 64 and lines[0]["grader_version"] == "agent-eval-grader-v0.3"


def test_the_scorecard_imports_nothing_from_the_app():
    # Like the grader: it must run on artifacts older than the code that wrote them.
    source = (Path(__file__).resolve().parents[1] / "scripts" / "agent_eval_scorecard.py").read_text(encoding="utf-8")
    assert "from app" not in source and "import app" not in source
