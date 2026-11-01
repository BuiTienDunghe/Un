"""Compare two runs of this round, task by task (see PREREGISTRATION.md). Written after the preregistration and
before the arms were read; the control runs had started by then.

    python analyze.py ae  <control_dir> <arm_dir>
    python analyze.py bfcl <control_dir> <arm_dir>

The Agent Eval dirs hold task_results.jsonl and events.jsonl; the BFCL dirs hold result/ and scores.json.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def tools(row: dict) -> list[str]:
    return [json.dumps(call, ensure_ascii=False, sort_keys=True) for call in row.get("tool_calls", [])]


def agent_eval(control: Path, arm: Path) -> None:
    a = {r["task_id"]: r for r in rows(control / "task_results.jsonl")}
    b = {r["task_id"]: r for r in rows(arm / "task_results.jsonl")}
    assert a.keys() == b.keys(), "different task sets"
    events = rows(arm / "events.jsonl")
    fired = sorted({e["task_id"] for e in events if e.get("kind") == "lookup_check"})
    same = [t for t in a if a[t]["answer"] == b[t]["answer"] and tools(a[t]) == tools(b[t])]
    print(f"passed: control {sum(r['passed'] for r in a.values())}/{len(a)}  arm {sum(r['passed'] for r in b.values())}/{len(b)}")
    print(f"identical answer + tool calls: {len(same)}/{len(a)}")
    print(f"lookup_check fired in: {fired}")
    for t in a:
        if a[t]["passed"] != b[t]["passed"]:
            print(f"  FLIP {t}: {a[t]['passed']} -> {b[t]['passed']}  tools {[c['name'] for c in a[t]['tool_calls']]} -> {[c['name'] for c in b[t]['tool_calls']]}")
    for t in a:
        if t not in same and a[t]["passed"] == b[t]["passed"]:
            print(f"  changed, same verdict {t} ({'pass' if a[t]['passed'] else 'fail'})")
    for name, run in (("control", a), ("arm", b)):
        latency = [r["latency_ms"] / 1000 for r in run.values() if r.get("latency_ms") is not None]
        print(f"  {name}: median {statistics.median(latency):.1f}s  max {max(latency):.1f}s")


def bfcl(control: Path, arm: Path) -> None:
    sa, sb = json.loads((control / "scores.json").read_text(encoding="utf-8")), json.loads((arm / "scores.json").read_text(encoding="utf-8"))
    total = lambda s: sum(v["correct"] for v in s.values())
    print(f"correct: control {total(sa)}/33  arm {total(sb)}/33")
    fa = {i for v in sa.values() for i in v["failed_ids"]}
    fb = {i for v in sb.values() for i in v["failed_ids"]}
    print(f"hurt (pass -> fail): {sorted(fb - fa)}   helped (fail -> pass): {sorted(fa - fb)}")
    summary = lambda d: json.loads((d / "run_summary.json").read_text(encoding="utf-8"))
    print("stop reasons control:", summary(control)["turn_stop_reasons"], " arm:", summary(arm)["turn_stop_reasons"])
    print("step kinds   control:", summary(control)["step_kinds"], "\n             arm:    ", summary(arm)["step_kinds"])
    identical, differing = 0, []
    for path in sorted((control / "result" / "un-harness").rglob("*_result.json")):
        other = arm / path.relative_to(control)
        for ra, rb in zip(rows(path), rows(other)):
            if ra["result"] == rb["result"]:
                identical += 1
            else:
                differing.append(ra["id"])
    print(f"identical recorded calls (and answers): {identical}/33; differing: {differing}")
    for path in sorted((arm / "result" / "un-harness").rglob("*multi_turn*_result.json")):
        for r in rows(path):
            tin = [sum(turn) for turn in r["input_token_count"]]
            print(f"  {r['id']}: tokens_in per turn {[int(x) for x in tin]}")


if __name__ == "__main__":
    kind, control, arm = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    {"ae": agent_eval, "bfcl": bfcl}[kind](control, arm)
