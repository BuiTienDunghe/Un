"""Ticket 20 #3-B (reworded paste slip) before/after, by PREREGISTRATION.md's rule.

    python analyze.py   # writes analysis.json beside this file

"Worse run" (r1 and r2 differ) is read against the proposal: a task passes BEFORE if any
before run passes it, and passes AFTER only if every after run does; it opens AFTER only
if every after run opens it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEPT = HERE.parent
SIDES = {
    "before": [HERE / "v0.5-3b-before-r1-cold", HERE / "v0.5-3b-before-r2-cold"],
    "after": [HERE / "v0.5-3b-after-r1-cold", HERE / "v0.5-3b-after-r2-cold"],
}
PASTE_TASKS = ("doc-39", "doc-40", "doc-41", "doc-42", "doc-43")
FAR = ("doc-40", "doc-41", "doc-43")  # answers past the first read: "read on" is measurable
NEEDS_MIDDLE = ("doc-39", "doc-40", "doc-41", "doc-43")
HASHES = ("tools_sha256", "agent_guide_sha256", "system_prompt_sha256")
TOOLS_SHA = ("153209", "a75e500")  # prefix, suffix as registered
OLD_DOC39 = KEPT / "agent-eval-v0.3-pastes" / "v0.3-paste-r1-cold"
NEXT = re.compile(r'"next_from_chunk":\s*(null|\d+)')


def load(run: Path) -> dict:
    rows = {r["task_id"]: r for r in map(json.loads, (run / "task_results.jsonl").read_text(encoding="utf-8").splitlines())}
    events: dict[str, list] = {}
    for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        events.setdefault(event["task_id"], []).append(event)
    return {"manifest": json.loads((run / "manifest.json").read_text(encoding="utf-8")), "rows": rows, "events": events}


def task(run: dict, task_id: str) -> dict:
    row, steps = run["rows"][task_id], run["events"].get(task_id, [])
    reads, first_open_at, check_at = [], None, None
    for index, step in enumerate(steps):
        if step["kind"] == "answer_check" and check_at is None:
            check_at = index
        if step["kind"] == "tool_call" and step.get("tool_name") == "read_document":
            args = step.get("arguments") or {}
            reads.append({key: args.get(key) for key in ("document_id", "from_chunk", "n", "page")} | {"next_from_chunk": "?"})
            if str(args.get("document_id") or "").startswith("paste_") and first_open_at is None:
                first_open_at = index
        if step["kind"] == "tool_result" and step.get("tool_name") == "read_document" and reads:
            found = NEXT.search(step.get("content") or "")
            reads[-1]["next_from_chunk"] = None if not found or found.group(1) == "null" else int(found.group(1))
            reads[-1]["error_code"] = step.get("error_code")
    paste_reads = [r for r in reads if str(r.get("document_id") or "").startswith("paste_")]
    read_on = any(
        isinstance(prev["next_from_chunk"], int) and cur.get("from_chunk") == prev["next_from_chunk"]
        for prev, cur in zip(paste_reads, paste_reads[1:])
    )
    final = next((s for s in reversed(steps) if s["kind"] == "final"), {})
    checks = (row.get("grade") or {}).get("checks") or []
    return {
        "passed": row["passed"],
        "failed_checks": [c.get("name") or c.get("check") for c in checks if not c.get("passed", True)],
        "opens": bool(paste_reads),
        "reads": reads,
        "first_read": {k: paste_reads[0].get(k) for k in ("from_chunk", "n")} if paste_reads else None,
        "read_on_correct": read_on,
        "answer_check_before_first_open": check_at is not None and first_open_at is not None and check_at < first_open_at,
        "answer_check": check_at is not None,
        "tools": [s.get("tool_name") for s in steps if s["kind"] == "tool_call"],
        "stop_reason": final.get("stop_reason"),
        "tokens_in": row["tokens_in"],
        "latency_ms": row["latency_ms"],
        "error": row["error"],
        "answer": row["answer"],
    }


def main() -> None:
    runs = {side: [load(path) for path in paths] for side, paths in SIDES.items()}
    per = {side: [{t: task(run, t) for t in PASTE_TASKS} for run in side_runs] for side, side_runs in runs.items()}
    manifests = {side: [run["manifest"] for run in side_runs] for side, side_runs in runs.items()}
    every = [m for side in manifests.values() for m in side]
    preconditions = {
        **{h: len({m[h] for m in every}) == 1 for h in HASHES},
        "tools_sha256_as_registered": every[0]["tools_sha256"].startswith(TOOLS_SHA[0]) and every[0]["tools_sha256"].endswith(TOOLS_SHA[1]),
        "dataset_sha256": len({m["dataset"]["sha256"] for m in every}) == 1,
        "tasks_run": all(tuple(m["dataset"]["tasks_run"]) == PASTE_TASKS for m in every),
    }

    def before_pass(t: str) -> bool:
        return any(run[t]["passed"] for run in per["before"])

    def after_pass(t: str) -> bool:
        return all(run[t]["passed"] for run in per["after"])

    def after_opens(t: str) -> bool:
        return all(run[t]["opens"] for run in per["after"])

    old39 = load(OLD_DOC39)["rows"]["doc-39"]["answer"]
    predictions = {
        "before_doc39_equals_#3": all(run["doc-39"]["answer"] == old39 for run in per["before"]),
        "before_far_do_not_open": all(not run[t]["opens"] for run in per["before"] for t in FAR),
        "after_doc39_opens_and_passes": after_opens("doc-39") and after_pass("doc-39"),
        "after_far_open_at_least_2": sum(after_opens(t) for t in FAR) >= 2,
        "after_doc42_no_open_and_passes": all(not run["doc-42"]["opens"] for run in per["after"]) and after_pass("doc-42"),
        **{
            f"{side}_r1_equals_r2": all(r1[t]["answer"] == r2[t]["answer"] for t in PASTE_TASKS)
            for side, (r1, r2) in per.items()
        },
    }
    rule = {
        "1_preconditions": all(preconditions.values()),
        "2_doc39_opens": after_opens("doc-39"),
        "3_far_open_at_least_2_of_3": sum(after_opens(t) for t in FAR) >= 2,
        "4_no_pass_turns_fail": not [t for t in PASTE_TASKS if before_pass(t) and not after_pass(t)],
        "5_some_fail_turns_pass": bool([t for t in NEEDS_MIDDLE if not before_pass(t) and after_pass(t)]),
    }
    rule["propose_merge"] = all(rule.values())
    result = {
        "preconditions": preconditions,
        "hashes": {side: [{h: m[h][:12] for h in HASHES} | {"dataset": m["dataset"]["sha256"][:12], "commit": m.get("commit")} for m in ms] for side, ms in manifests.items()},
        "score": {side: [sum(run[t]["passed"] for t in PASTE_TASKS) for run in side_runs] for side, side_runs in per.items()},
        "opens": {side: [sorted(t for t in PASTE_TASKS if run[t]["opens"]) for run in side_runs] for side, side_runs in per.items()},
        "read_on_correct_far": {side: [sorted(t for t in FAR if run[t]["read_on_correct"]) for run in side_runs] for side, side_runs in per.items()},
        "opens_after_answer_check_retry": {side: [sorted(t for t in PASTE_TASKS if run[t]["answer_check_before_first_open"]) for run in side_runs] for side, side_runs in per.items()},
        "fail_to_pass": [t for t in NEEDS_MIDDLE if not before_pass(t) and after_pass(t)],
        "pass_to_fail": [t for t in PASTE_TASKS if before_pass(t) and not after_pass(t)],
        "predictions": predictions,
        "rule": rule,
        "tasks": per,
    }
    (HERE / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "tasks"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
