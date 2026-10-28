"""Ticket 20 #2 (answer check) against #1-B, by PREREGISTRATION.md's rule.

    python analyze.py   # writes analysis.json beside this file
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEPT = HERE.parent
BASE = KEPT / "agent-eval-v0.3-read-B-20261028" / "v0.3-read-B-r1-cold"
RUNS = [HERE / "v0.3-check-r1-cold", HERE / "v0.3-check-r2-cold"]
# The same sets as ../agent-eval-v0.3-read-B-20261028/analyze.py.
LONG = ("doc-33", "doc-34", "doc-35", "doc-36", "doc-37")
NEW = (*LONG, "doc-38", "doc-39", "hist-11")
HASHES = ("tools_sha256", "agent_guide_sha256", "system_prompt_sha256")


def load(run: Path) -> dict:
    rows = {r["task_id"]: r for r in map(json.loads, (run / "task_results.jsonl").read_text(encoding="utf-8").splitlines())}
    events: dict[str, list] = {}
    for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        events.setdefault(event["task_id"], []).append(event)
    return {"manifest": json.loads((run / "manifest.json").read_text(encoding="utf-8")), "rows": rows, "events": events}


def score(run: dict) -> dict:
    passed = {t for t, r in run["rows"].items() if r["passed"]}
    old = {t for t in run["rows"] if t not in NEW}
    return {"total": len(passed), "old_40": len(passed & old), "long_5": len(passed & set(LONG))}


def checks(run: dict, task: str) -> list[dict]:
    return [
        {"unsupported_figures": (e.get("arguments_shape") or {}).get("unsupported_figures"), "latency_ms": e.get("latency_ms")}
        for e in run["events"].get(task, []) if e["kind"] == "answer_check"
    ]


def final_shape(run: dict, task: str) -> dict | None:
    finals = [e for e in run["events"].get(task, []) if e["kind"] == "final"]
    return finals[-1].get("arguments_shape") if finals else None


def main() -> None:
    base = load(BASE)
    r1, r2 = (load(run) for run in RUNS)
    differ = sorted(t for t in base["rows"] if base["rows"][t]["answer"] != r1["rows"][t]["answer"])
    flips_down = sorted(t for t in base["rows"] if base["rows"][t]["passed"] and not r1["rows"][t]["passed"])
    flips_up = sorted(t for t in base["rows"] if not base["rows"][t]["passed"] and r1["rows"][t]["passed"])
    with_check = {t: checks(r1, t) for t in r1["rows"] if checks(r1, t)}
    retry_tools = {
        t: [e["tool_name"] for e in r1["events"][t] if e["kind"] == "tool_call" and e["step_index"] > next(
            x["step_index"] for x in r1["events"][t] if x["kind"] == "answer_check")]
        for t in with_check
    }
    doc10_final = final_shape(r1, "doc-10") or {}
    grounding = {}
    for t in r1["rows"]:
        shape = final_shape(r1, t) or {}
        if r1["rows"][t]["tool_calls"] and "grounding" in shape:
            grounding[shape["grounding"]] = grounding.get(shape["grounding"], 0) + 1
    result = {
        "hashes_equal_to_1B": {h: r1["manifest"][h] == base["manifest"][h] for h in HASHES},
        "score": {"1B": score(base), "r1": score(r1), "r2": score(r2)},
        "answers_differ_from_1B": differ,
        "passed_to_failed": flips_down,
        "failed_to_passed": flips_up,
        "answer_check_steps": with_check,
        "tools_after_retry": retry_tools,
        "doc10_final_shape": doc10_final,
        "doc22_final_shape": final_shape(r1, "doc-22"),
        "grounding_on_finals_with_tools": grounding,
        "r1_equals_r2": all(r1["rows"][t]["answer"] == r2["rows"][t]["answer"] for t in r1["rows"]),
        "latency_ms": {t: [base["rows"][t]["latency_ms"], r1["rows"][t]["latency_ms"]] for t in with_check},
    }
    result["prediction_46_identical"] = differ == ["doc-10", "doc-22"]
    result["rule"] = {
        "no_pass_to_fail": not flips_down,
        "doc10_final_no_unsupported": doc10_final.get("unsupported_figures") == 0,
    }
    result["rule"]["propose_ship"] = all(result["rule"].values())
    (HERE / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
