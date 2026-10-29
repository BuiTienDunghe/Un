"""Ticket 27 (a tool call Ollama cannot parse) before/after, by PREREGISTRATION.md's rule.

    python analyze.py   # writes analysis.json beside this file

Committed with the preregistration, before the first run. Every run unloads the general
model before each task (--unload-between-tasks).
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPRO = {
    "before": [HERE / "v0.7-27-repro-before-r1", HERE / "v0.7-27-repro-before-r2"],
    "after": [HERE / "v0.7-27-repro-after-r1", HERE / "v0.7-27-repro-after-r2"],
}
FULL = {"M0": HERE / "v0.7-27-main-before-full", "M1": HERE / "v0.7-27-main-after-full"}
TARGET = "doc-44"
HASHES = ("tools_sha256", "agent_guide_sha256", "system_prompt_sha256")
TOOLS_SHA = ("153209", "a75e500")
DATASET_SHA = ("d87c4155eb3e", "e56efb10")
STEP = "tool_call_error"
CODE = "TOOL_CALL_PARSE"


def load(run: Path) -> dict:
    rows = {r["task_id"]: r for r in map(json.loads, (run / "task_results.jsonl").read_text(encoding="utf-8").splitlines())}
    events: dict[str, list] = {}
    for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        events.setdefault(event["task_id"], []).append(event)
    return {"manifest": json.loads((run / "manifest.json").read_text(encoding="utf-8")), "rows": rows, "events": events}


def task(run: dict, task_id: str) -> dict:
    row, steps = run["rows"][task_id], run["events"].get(task_id, [])
    fixes = [s for s in steps if s["kind"] == STEP]
    final = next((s for s in reversed(steps) if s["kind"] == "final"), {})
    checks = (row.get("grade") or {}).get("checks") or []
    return {
        "lost_turn": bool(row.get("error")),
        "error": row.get("error"),
        "fix_steps": len(fixes),
        "fix_codes": sorted({s.get("error_code") for s in fixes}),
        "stop_reason": final.get("stop_reason"),
        "answer_empty": not (row.get("answer") or "").strip(),
        "passed": row["passed"],
        "failed_checks": [c.get("check") or c.get("name") for c in checks if not c.get("passed", True)],
        "tools": [(s.get("tool_name"), json.dumps(s.get("arguments"), ensure_ascii=False, sort_keys=True)) for s in steps if s["kind"] == "tool_call"],
        "answer": row.get("answer") or "",
    }


def same_hashes(manifests: list[dict]) -> bool:
    return all(len({m[h] for m in manifests}) == 1 for h in HASHES)


def main() -> None:
    repro = {side: [load(p) for p in paths] for side, paths in REPRO.items()}
    full = {side: load(p) for side, p in FULL.items()}
    repro_m = [r["manifest"] for runs in repro.values() for r in runs]
    full_m = [r["manifest"] for r in full.values()]
    every = repro_m + full_m
    preconditions = {
        "repro_hashes_equal": same_hashes(repro_m),
        "full_hashes_equal": same_hashes(full_m),
        "tools_sha256_as_registered": all(m["tools_sha256"].startswith(TOOLS_SHA[0]) and m["tools_sha256"].endswith(TOOLS_SHA[1]) for m in every),
        "dataset_sha256_as_registered": all(m["dataset"]["sha256"].startswith(DATASET_SHA[0]) and m["dataset"]["sha256"].endswith(DATASET_SHA[1]) for m in every),
        "unload_between_tasks": all(m.get("unload_between_tasks") is True for m in every),
        "repro_tasks_run": all(m["dataset"]["tasks_run"] == [TARGET] for m in repro_m),
        "full_runs_62": all(len(r["rows"]) == 62 for r in full.values()),
    }
    target = {side: [task(r, TARGET) for r in runs] for side, runs in repro.items()}
    ids = sorted(full["M0"]["rows"])
    m0 = {t: task(full["M0"], t) for t in ids}
    m1 = {t: task(full["M1"], t) for t in ids}
    fired_m1 = [t for t in ids if m1[t]["fix_steps"]]
    differ = [t for t in ids if (m0[t]["answer"], m0[t]["tools"]) != (m1[t]["answer"], m1[t]["tools"])]
    rule = {
        "1_preconditions": all(preconditions.values()),
        "2_reproduced_before": all(x["lost_turn"] for x in target["before"]),
        "3_fixed_after": all(not x["lost_turn"] and x["fix_steps"] and CODE in x["fix_codes"] and not x["answer_empty"] for x in target["after"]),
        "4_no_side_effect": all(t in fired_m1 for t in differ),
    }
    rule["propose_merge"] = all(rule.values())
    predictions = {
        "before_lost_both": rule["2_reproduced_before"],
        "after_fixed_both": rule["3_fixed_after"],
        "after_r1_equals_r2": target["after"][0]["answer"] == target["after"][1]["answer"],
        "main_identical_62_and_no_fix_step": not differ and not fired_m1,
    }
    result = {
        "preconditions": preconditions,
        "hashes": {side: [{h: r["manifest"][h][:12] for h in HASHES} | {"commit": r["manifest"].get("commit")} for r in runs] for side, runs in repro.items()}
        | {side: {h: r["manifest"][h][:12] for h in HASHES} | {"commit": r["manifest"].get("commit")} for side, r in full.items()},
        "target": target,
        "full_score": {side: sum(r["rows"][t]["passed"] for t in ids) for side, r in full.items()},
        "full_lost_turns": {side: sorted(t for t in ids if r["rows"][t].get("error")) for side, r in full.items()},
        "fired_on_main_after": fired_m1,
        "differ_main_before_after": differ,
        "predictions": predictions,
        "rule": rule,
    }
    (HERE / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "target"}, ensure_ascii=False, indent=1))
    print(json.dumps({side: [{k: x[k] for k in ("lost_turn", "fix_steps", "stop_reason", "answer_empty", "passed", "failed_checks")} for x in xs] for side, xs in target.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
