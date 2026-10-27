"""Recompute analysis.json: #1's two cold v0.3 runs against the v0.3 baseline (ticket 20 #1).

    python data/evaluation/results/kept/agent-eval-v0.3-read-20261028/analyze.py

Reads the runs kept next to this file and ../agent-eval-v0.3-baseline-20261028/.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASELINE = HERE.parent / "agent-eval-v0.3-baseline-20261028"
NEW = ("doc-33", "doc-34", "doc-35", "doc-36", "doc-37", "doc-38", "doc-39", "hist-11")
WINDOW = 16384


def results(run: Path) -> dict[str, dict]:
    return {row["task_id"]: row for row in map(json.loads, (run / "task_results.jsonl").open(encoding="utf-8"))}


def events(run: Path) -> list[dict]:
    return [json.loads(line) for line in (run / "events.jsonl").open(encoding="utf-8")]


def reads(run: Path) -> dict[str, dict]:
    """read_document per task: calls, and how many came back as an error code."""
    found: dict[str, dict] = {}
    for event in events(run):
        if event.get("tool_name") != "read_document":
            continue
        entry = found.setdefault(event["task_id"], {"calls": 0, "errors": Counter()})
        if event.get("kind") == "tool_call":
            entry["calls"] += 1
        elif event.get("kind") == "tool_result" and event.get("error_code"):
            entry["errors"][event["error_code"]] += 1
    return {task: {"calls": e["calls"], "errors": dict(e["errors"])} for task, e in sorted(found.items())}


def main() -> None:
    base = results(BASELINE / "v0.3-base-r1-cold")
    r1, r2 = results(HERE / "v0.3-read-r1-cold"), results(HERE / "v0.3-read-r2-cold")
    answer = lambda row: row.get("answer")  # noqa: E731
    old = [task for task in base if task not in NEW]
    flips = {
        task: {"baseline": base[task]["passed"], "after": r1[task]["passed"]}
        for task in base if base[task]["passed"] != r1[task]["passed"]
    }
    tokens = [e["tokens_in"] for e in events(HERE / "v0.3-read-r1-cold") if e.get("tokens_in")]
    analysis = {
        "passed": {
            "baseline": sum(row["passed"] for row in base.values()),
            "r1": sum(row["passed"] for row in r1.values()),
            "r2": sum(row["passed"] for row in r2.values()),
        },
        "r1_equals_r2_answers": sum(answer(r1[t]) == answer(r2[t]) for t in r1),
        "old_tasks_answer_changed_vs_baseline": sorted(t for t in old if answer(base[t]) != answer(r1[t])),
        "old_tasks_passed": {"baseline": sum(base[t]["passed"] for t in old), "r1": sum(r1[t]["passed"] for t in old)},
        "flips_vs_baseline": flips,
        "new_tasks": {t: {"baseline": base[t]["passed"], "r1": r1[t]["passed"], "r2": r2[t]["passed"]} for t in NEW},
        "read_document": reads(HERE / "v0.3-read-r1-cold"),
        "tokens_in_max": max(tokens),
        "tokens_in_max_share_of_window": round(max(tokens) / WINDOW, 3),
    }
    (HERE / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
