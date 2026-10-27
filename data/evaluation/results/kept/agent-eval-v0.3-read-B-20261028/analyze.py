"""Recompute analysis.json: A (v0.3 baseline), #1 and #1-B on v0.3 (ticket 20 #1, option B).

    python data/evaluation/results/kept/agent-eval-v0.3-read-B-20261028/analyze.py

Reads the #1-B runs next to this file, ../agent-eval-v0.3-read-20261028/ (#1) and
../agent-eval-v0.3-baseline-20261028/ (A). The decision rule is the one registered in
PREREGISTRATION.md, applied to r1 (or to the worse run if r1 and r2 differ).
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEPT = HERE.parent
RUNS = {
    "A": KEPT / "agent-eval-v0.3-baseline-20261028" / "v0.3-base-r1-cold",
    "#1": KEPT / "agent-eval-v0.3-read-20261028" / "v0.3-read-r1-cold",
    "#1-B": HERE / "v0.3-read-B-r1-cold",
}
B_R2 = HERE / "v0.3-read-B-r2-cold"
LONG = ("doc-33", "doc-34", "doc-35", "doc-36", "doc-37")
NEW = (*LONG, "doc-38", "doc-39", "hist-11")
WINDOW = 16384


def results(run: Path) -> dict[str, dict]:
    return {row["task_id"]: row for row in map(json.loads, (run / "task_results.jsonl").open(encoding="utf-8"))}


def events(run: Path) -> list[dict]:
    return [json.loads(line) for line in (run / "events.jsonl").open(encoding="utf-8")]


def reads(run: Path) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for event in events(run):
        if event.get("tool_name") != "read_document":
            continue
        entry = found.setdefault(event["task_id"], {"calls": [], "errors": Counter()})
        if event.get("kind") == "tool_call":
            arguments = event.get("arguments") or {}
            entry["calls"].append({key: arguments.get(key) for key in ("from_chunk", "n", "page") if key in arguments})
        elif event.get("kind") == "tool_result" and event.get("error_code"):
            entry["errors"][event["error_code"]] += 1
    return {task: {"calls": e["calls"], "errors": dict(e["errors"])} for task, e in sorted(found.items())}


def score(rows: dict[str, dict]) -> dict[str, int]:
    old = [task for task in rows if task not in NEW]
    return {
        "total": sum(row["passed"] for row in rows.values()),
        "old_40": sum(rows[task]["passed"] for task in old),
        "long_5": sum(rows[task]["passed"] for task in LONG),
    }


def main() -> None:
    sides = {name: results(run) for name, run in RUNS.items()}
    b2 = results(B_R2)
    scores = {name: score(rows) for name, rows in sides.items()}
    b_worse = min(scores["#1-B"], score(b2), key=lambda s: (s["long_5"] >= 4 and s["old_40"] >= 33, s["total"]))
    a, b = sides["A"], sides["#1-B"]
    old = [task for task in a if task not in NEW]
    tokens = [e["tokens_in"] for e in events(RUNS["#1-B"]) if e.get("tokens_in")]
    analysis = {
        "scores": scores,
        "b_r2": score(b2),
        "b_r1_equals_r2_answers": sum(b[t].get("answer") == b2[t].get("answer") for t in b),
        "decision_rule": "ship #1-B if long_5 >= 4 and old_40 >= 33 (on r1, or the worse run if r1 != r2); else (C)",
        "decision": "propose ship #1-B" if b_worse["long_5"] >= 4 and b_worse["old_40"] >= 33 else "do (C)",
        "old_tasks_answer_identical_to_A": sum(a[t].get("answer") == b[t].get("answer") for t in old),
        "flips_vs_A": {t: {"A": a[t]["passed"], "#1-B": b[t]["passed"]} for t in a if a[t]["passed"] != b[t]["passed"]},
        "flips_vs_#1": {
            t: {"#1": sides["#1"][t]["passed"], "#1-B": b[t]["passed"]}
            for t in a if sides["#1"][t]["passed"] != b[t]["passed"]
        },
        "read_document": reads(RUNS["#1-B"]),
        "tokens_in_max": max(tokens),
        "tokens_in_max_share_of_window": round(max(tokens) / WINDOW, 3),
    }
    (HERE / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
