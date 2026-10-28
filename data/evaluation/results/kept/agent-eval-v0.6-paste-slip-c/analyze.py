"""Ticket 20 #3-C (second paste slip) before/after, by PREREGISTRATION.md's rule.

    python analyze.py   # writes analysis.json beside this file

Committed with the preregistration, before the first run. "Worse run" (r1 and r2 differ)
is read against the proposal: a task passes BEFORE if any before run passes it, and passes
AFTER only if every after run does.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEPT = HERE.parent
SIDES = {
    "before": [HERE / "v0.6-3c-before-r1-cold", HERE / "v0.6-3c-before-r2-cold"],
    "after": [HERE / "v0.6-3c-after-r1-cold", HERE / "v0.6-3c-after-r2-cold"],
}
PASTE_TASKS = tuple(f"doc-{n}" for n in range(39, 48))
SEEN_MIDDLE = ("doc-39", "doc-40", "doc-41", "doc-43")
NEW_MIDDLE = ("doc-44", "doc-46", "doc-47")
VISIBLE = ("doc-42", "doc-45")  # the answer is in the slip's edges
READ_ON = ("doc-40", "doc-41", "doc-43", "doc-44", "doc-46", "doc-47")  # one read cannot reach the answer
HASHES = ("tools_sha256", "agent_guide_sha256", "system_prompt_sha256")
TOOLS_SHA = ("153209", "a75e500")  # prefix, suffix as registered
DATASET_SHA = ("cd38e4d19a09", "306ed")  # agent-eval-v0.6 on main 8b91199
READ_MAX_CHUNKS = 3
PRIOR_BEFORE = KEPT / "agent-eval-v0.5-paste-slip-b" / "v0.5-3b-before-r1-cold"
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

    def within_cap(read: dict) -> bool:
        n = read.get("n")
        return n is None or (isinstance(n, int) and 1 <= n <= READ_MAX_CHUNKS)

    final = next((s for s in reversed(steps) if s["kind"] == "final"), {})
    checks = (row.get("grade") or {}).get("checks") or []
    return {
        "passed": row["passed"],
        "failed_checks": [c.get("check") or c.get("name") for c in checks if not c.get("passed", True)],
        "opens": bool(paste_reads),
        "reads": reads,
        "read_count": len(paste_reads),
        "first_read": {k: paste_reads[0].get(k) for k in ("from_chunk", "n")} if paste_reads else None,
        "first_n_within_cap": within_cap(paste_reads[0]) if paste_reads else None,
        "later_n": [r.get("n") for r in paste_reads[1:]],
        "later_n_within_cap": [within_cap(r) for r in paste_reads[1:]],
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
    every = [run["manifest"] for side_runs in runs.values() for run in side_runs]
    preconditions = {
        **{h: len({m[h] for m in every}) == 1 for h in HASHES},
        "tools_sha256_as_registered": every[0]["tools_sha256"].startswith(TOOLS_SHA[0]) and every[0]["tools_sha256"].endswith(TOOLS_SHA[1]),
        "dataset_sha256": len({m["dataset"]["sha256"] for m in every}) == 1,
        "dataset_sha256_as_registered": every[0]["dataset"]["sha256"].startswith(DATASET_SHA[0]) and every[0]["dataset"]["sha256"].endswith(DATASET_SHA[1]),
        "dataset_version": {m["dataset"]["version"] for m in every} == {"agent-eval-v0.6"},
        "tasks_run": all(tuple(m["dataset"]["tasks_run"]) == PASTE_TASKS for m in every),
    }

    def before_pass(t: str) -> bool:
        return any(run[t]["passed"] for run in per["before"])

    def after_pass(t: str) -> bool:
        return all(run[t]["passed"] for run in per["after"])

    def all_after(t: str, key: str) -> bool:
        return all(run[t][key] for run in per["after"])

    def fail_to_pass(group: tuple[str, ...]) -> list[str]:
        return [t for t in group if not before_pass(t) and after_pass(t)]

    prior = load(PRIOR_BEFORE)["rows"]
    after_reads = [(t, run[t]) for run in per["after"] for t in PASTE_TASKS if run[t]["opens"]]
    predictions = {
        "before_seen_equal_3b_before": all(run[t]["answer"] == prior[t]["answer"] for run in per["before"] for t in PASTE_TASKS[:5]),
        "before_new_middle_fail": not any(before_pass(t) for t in NEW_MIDDLE),
        "before_doc45_passes_no_read": all(run["doc-45"]["passed"] and not run["doc-45"]["opens"] for run in per["before"]),
        "after_first_n_within_cap": all(v["first_n_within_cap"] for _, v in after_reads),
        "after_doc39_opens_and_passes": all_after("doc-39", "opens") and after_pass("doc-39"),
        "after_doc43_opens": all_after("doc-43", "opens"),
        "after_visible_no_read_and_pass": all(not run[t]["opens"] for run in per["after"] for t in VISIBLE) and all(after_pass(t) for t in VISIBLE),
        "after_new_middle_open": all(all_after(t, "opens") for t in NEW_MIDDLE),
        **{f"{side}_r1_equals_r2": all(r1[t]["answer"] == r2[t]["answer"] for t in PASTE_TASKS) for side, (r1, r2) in per.items()},
    }
    rule = {
        "1_preconditions": all(preconditions.values()),
        "2_no_pass_turns_fail": not [t for t in PASTE_TASKS if before_pass(t) and not after_pass(t)],
        "3_new_middle_fail_to_pass_at_least_2_of_3": len(fail_to_pass(NEW_MIDDLE)) >= 2,
        "4_doc45_passes_after": after_pass("doc-45"),
        "5_seen_middle_fail_to_pass_at_least_2_of_4": len(fail_to_pass(SEEN_MIDDLE)) >= 2,
    }
    rule["propose_merge"] = all(rule.values())

    def per_side(fn):
        return {side: [fn(run) for run in side_runs] for side, side_runs in per.items()}

    result = {
        "preconditions": preconditions,
        "hashes": {side: [{h: run["manifest"][h][:12] for h in HASHES} | {"dataset": run["manifest"]["dataset"]["sha256"][:12], "commit": run["manifest"].get("commit")} for run in side_runs] for side, side_runs in runs.items()},
        "score": per_side(lambda run: sum(run[t]["passed"] for t in PASTE_TASKS)),
        "opens": per_side(lambda run: sorted(t for t in PASTE_TASKS if run[t]["opens"])),
        "read_on_correct": per_side(lambda run: sorted(t for t in READ_ON if run[t]["read_on_correct"])),
        "first_n_within_cap": per_side(lambda run: [sum(bool(run[t]["first_n_within_cap"]) for t in PASTE_TASKS), sum(run[t]["opens"] for t in PASTE_TASKS)]),
        "later_n_within_cap": per_side(lambda run: [sum(sum(run[t]["later_n_within_cap"]) for t in PASTE_TASKS), sum(len(run[t]["later_n_within_cap"]) for t in PASTE_TASKS)]),
        "visible_read_counts": per_side(lambda run: {t: run[t]["read_count"] for t in VISIBLE}),
        "opens_after_answer_check_retry": per_side(lambda run: sorted(t for t in PASTE_TASKS if run[t]["answer_check_before_first_open"])),
        "fail_to_pass": {"seen_middle": fail_to_pass(SEEN_MIDDLE), "new_middle": fail_to_pass(NEW_MIDDLE), "visible": fail_to_pass(VISIBLE)},
        "pass_to_fail": [t for t in PASTE_TASKS if before_pass(t) and not after_pass(t)],
        "predictions": predictions,
        "rule": rule,
        "tasks": per,
    }
    (HERE / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "tasks"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
