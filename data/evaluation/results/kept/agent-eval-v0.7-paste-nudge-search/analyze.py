"""Ticket 20 #3-D (step 1 nudge, 3' paste search) on three arms, by PREREGISTRATION.md's rule.

    python analyze.py   # writes analysis.json beside this file

Committed with the preregistration, before the first run. "Worse run" (r1 and r2 differ)
is read against the proposal: a task passes on the arm compared against if any of its runs
passes it, and on the proposed arm only if every run does.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEPT = HERE.parent
ARMS = {
    "base": [HERE / "v0.7-3d-base-r1-cold", HERE / "v0.7-3d-base-r2-cold"],
    "nudge": [HERE / "v0.7-3d-nudge-r1-cold", HERE / "v0.7-3d-nudge-r2-cold"],
    "both": [HERE / "v0.7-3d-both-r1-cold", HERE / "v0.7-3d-both-r2-cold"],
}
FULL = {"base": HERE / "v0.7-3d-base-full-cold", "both": HERE / "v0.7-3d-both-full-cold"}
PASTE_TASKS = tuple(f"doc-{n}" for n in range(39, 54))
SEEN = tuple(f"doc-{n}" for n in range(39, 48))
NEW_REACHABLE = ("doc-48", "doc-51", "doc-53")
NEW_PAST_CEILING = ("doc-49", "doc-50")
UNCHANGED_BY_NUDGE = ("doc-39", "doc-41", "doc-42", "doc-43", "doc-45", "doc-46")
NUDGE_EXPECTED = ("doc-40", "doc-44", "doc-47")
# Where each answer lies (chunk_index from 0), as the task notes say and tests recompute.
ANSWER_CHUNKS = {
    "doc-39": (2,), "doc-40": (3,), "doc-41": (6,), "doc-43": (1, 5), "doc-44": (4,), "doc-46": (7,),
    "doc-47": (2, 5), "doc-48": (5,), "doc-49": (10,), "doc-50": (14,), "doc-51": (0, 6), "doc-53": (6,),
}
HASHES = ("tools_sha256", "agent_guide_sha256", "system_prompt_sha256")
TOOLS_SHA = ("153209", "a75e500")  # prefix, suffix as registered
DATASET_SHA = ("d87c4155eb3e", "e56efb10")  # agent-eval-v0.7 on main f45b764
PRIOR_AFTER = KEPT / "agent-eval-v0.6-paste-slip-c" / "v0.6-3c-after-r1-cold"
LEAK = re.compile(r"lời nhắc|nhắc tới|điều chỉnh lại|kiểm tra lại câu trả lời|trả lời lại|hệ thống (?:yêu cầu|nhắc)", re.IGNORECASE)
CHUNK_INDEX = re.compile(r'"chunk_index":\s*(\d+)')


def load(run: Path) -> dict:
    rows = {r["task_id"]: r for r in map(json.loads, (run / "task_results.jsonl").read_text(encoding="utf-8").splitlines())}
    events: dict[str, list] = {}
    for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        events.setdefault(event["task_id"], []).append(event)
    return {"manifest": json.loads((run / "manifest.json").read_text(encoding="utf-8")), "rows": rows, "events": events}


def payload(content: str) -> object:
    """A tool result's JSON, inside the injection-defense wrapper (its <<<…>>> lines) or not."""
    lines = (content or "").split("\n")
    body = "\n".join(lines[1:-1]) if len(lines) >= 3 and lines[0].startswith("<<<") and lines[-1].startswith("<<<") else content
    try:
        return json.loads(body or "")
    except ValueError:
        return None


def paste_chunks(content: str) -> list[int]:
    """The chunk_index of every paste chunk a read_document or search_documents result carries."""
    found = payload(content)
    items = found.get("chunks") if isinstance(found, dict) else found
    if isinstance(items, list):
        owner = found.get("document_id") if isinstance(found, dict) else None
        return [
            item["chunk_index"] for item in items
            if isinstance(item, dict) and isinstance(item.get("chunk_index"), int)
            and str(item.get("document_id") or owner or "").startswith("paste_")
        ]
    # Unparsable (cut by a size cap): fall back to every chunk_index in the text.
    return [int(x) for x in CHUNK_INDEX.findall(content or "")] if "paste_" in (content or "") else []


def task(run: dict, task_id: str) -> dict:
    row, steps = run["rows"][task_id], run["events"].get(task_id, [])
    reads, searches, nudges, pending = [], [], [], None
    order: list[tuple[str, dict]] = []
    for step in steps:
        kind, name = step["kind"], step.get("tool_name")
        if kind == "unread_paste":
            nudges.append((step.get("arguments_shape") or {}).get("pattern"))
            order.append(("nudge", {}))
        elif kind == "tool_call" and name in ("read_document", "search_documents"):
            pending = {"tool": name, "arguments": step.get("arguments") or {}}
        elif kind == "tool_result" and pending and name == pending["tool"]:
            chunks = paste_chunks(step.get("content") or "")
            if name == "read_document":
                args = pending["arguments"]
                item = {"from_chunk": args.get("from_chunk"), "n": args.get("n"), "paste": str(args.get("document_id") or "").startswith("paste_"), "returned": chunks}
                reads.append(item)
                order.append(("read", item))
            else:
                item = {"query_chars": len(str(pending["arguments"].get("query") or "")), "paste_results": chunks}
                searches.append(item)
                order.append(("search", item))
            pending = None
    answer_chunks = set(ANSWER_CHUNKS.get(task_id, ()))
    returned = {c for r in reads if r["paste"] for c in r["returned"]}
    reached = bool(answer_chunks) and answer_chunks <= returned
    found_by_search = bool(answer_chunks & {c for s in searches for c in s["paste_results"]})
    # C4: a search that returned paste chunks comes before the read that brought the last
    # answer chunk in.
    search_before_reaching = False
    if reached:
        seen: set[int] = set()
        searched = False
        for what, item in order:
            if what == "search" and item["paste_results"]:
                searched = True
            if what == "read" and item["paste"]:
                seen |= set(item["returned"])
                if answer_chunks <= seen:
                    search_before_reaching = searched
                    break
    paste_reads = [r for r in reads if r["paste"]]
    searched_paste = [i for i, (what, item) in enumerate(order) if what == "search" and item["paste_results"]]
    answered_without_read = bool(searched_paste) and not any(what == "read" and item["paste"] for what, item in order[searched_paste[0]:])
    read_at_hit = any(
        nxt[0] == "read" and nxt[1]["paste"] and nxt[1]["from_chunk"] in cur[1]["paste_results"]
        for cur, nxt in zip(order, order[1:]) if cur[0] == "search" and cur[1]["paste_results"]
    )
    final = next((s for s in reversed(steps) if s["kind"] == "final"), {})
    checks = (row.get("grade") or {}).get("checks") or []
    answer = row["answer"] or ""
    return {
        "passed": row["passed"],
        "failed_checks": [c.get("check") or c.get("name") for c in checks if not c.get("passed", True)],
        "opens": bool(paste_reads),
        "reads": [{k: r[k] for k in ("from_chunk", "n", "returned")} for r in paste_reads],
        "reached": reached,
        "nudged": nudges,
        "answer_check": any(s["kind"] == "answer_check" for s in steps),
        "searched": bool(searches),
        "search_paste_results": [s["paste_results"] for s in searches],
        "found_by_search": found_by_search,
        "read_at_search_hit": read_at_hit,
        "search_before_reaching": search_before_reaching,
        "answered_after_search_without_read": answered_without_read,
        "leak": bool(LEAK.search(answer)),
        "tools": [s.get("tool_name") for s in steps if s["kind"] == "tool_call"],
        "stop_reason": final.get("stop_reason"),
        "tokens_in": row["tokens_in"],
        "latency_ms": row["latency_ms"],
        "error": row["error"],
        "answer": answer,
    }


def tool_trace(run: dict, task_id: str) -> list:
    return [(s.get("tool_name"), json.dumps(s.get("arguments"), ensure_ascii=False, sort_keys=True)) for s in run["events"].get(task_id, []) if s["kind"] == "tool_call"]


def main() -> None:
    runs = {arm: [load(path) for path in paths] for arm, paths in ARMS.items()}
    per = {arm: [{t: task(run, t) for t in PASTE_TASKS} for run in arm_runs] for arm, arm_runs in runs.items()}
    full = {arm: load(path) for arm, path in FULL.items()}
    every = [run["manifest"] for arm_runs in runs.values() for run in arm_runs] + [run["manifest"] for run in full.values()]
    others = sorted(set(full["base"]["rows"]) - set(PASTE_TASKS))
    preconditions = {
        **{h: len({m[h] for m in every}) == 1 for h in HASHES},
        "tools_sha256_as_registered": every[0]["tools_sha256"].startswith(TOOLS_SHA[0]) and every[0]["tools_sha256"].endswith(TOOLS_SHA[1]),
        "dataset_sha256_as_registered": all(m["dataset"]["sha256"].startswith(DATASET_SHA[0]) and m["dataset"]["sha256"].endswith(DATASET_SHA[1]) for m in every),
        "dataset_version": {m["dataset"]["version"] for m in every} == {"agent-eval-v0.7"},
        "tasks_run": all(tuple(run["manifest"]["dataset"]["tasks_run"]) == PASTE_TASKS for arm_runs in runs.values() for run in arm_runs),
        "full_runs_62": all(len(run["rows"]) == 62 for run in full.values()),
        "others_47": len(others) == 47,
        "others_identical_base_vs_both": all(
            full["base"]["rows"][t]["answer"] == full["both"]["rows"][t]["answer"] and tool_trace(full["base"], t) == tool_trace(full["both"], t)
            for t in others
        ),
    }
    others_differ = [t for t in others if full["base"]["rows"][t]["answer"] != full["both"]["rows"][t]["answer"] or tool_trace(full["base"], t) != tool_trace(full["both"], t)]

    def any_pass(arm: str, t: str) -> bool:
        return any(run[t]["passed"] for run in per[arm])

    def all_pass(arm: str, t: str) -> bool:
        return all(run[t]["passed"] for run in per[arm])

    def all_runs(arm: str, t: str, key: str) -> bool:
        return all(bool(run[t][key]) for run in per[arm])

    def fail_to_pass(against: str, proposed: str, group) -> list[str]:
        return [t for t in group if not any_pass(against, t) and all_pass(proposed, t)]

    def pass_to_fail(against: str, proposed: str) -> list[str]:
        return [t for t in PASTE_TASKS if any_pass(against, t) and not all_pass(proposed, t)]

    k = sum(not any_pass("base", t) for t in NEW_REACHABLE)
    b3 = fail_to_pass("base", "nudge", NEW_REACHABLE)
    c3 = fail_to_pass("nudge", "both", NEW_PAST_CEILING)
    rule = {
        "B1_preconditions": all(preconditions.values()),
        "B2_no_pass_turns_fail_base_to_nudge": not pass_to_fail("base", "nudge"),
        "B3_new_reachable_fail_to_pass": k > 0 and len(b3) >= max(1, math.ceil(k / 2)),
        "B4_each_b3_task_nudged_in_both_runs": all(all(run[t]["nudged"] for run in per["nudge"]) for t in b3),
        "C1_preconditions": all(preconditions.values()),
        "C2_no_pass_turns_fail_nudge_to_both": not pass_to_fail("nudge", "both"),
        "C3_past_ceiling_fail_to_pass": bool(c3),
        "C4_each_c3_task_searched_before_reaching": all(all_runs("both", t, "search_before_reaching") for t in c3),
    }
    proposals = {
        "B_merge_3c_plus_step1": all(v for key, v in rule.items() if key.startswith("B")),
        "C_merge_3prime_too": all(v for key, v in rule.items() if key.startswith("C")),
    }

    prior = load(PRIOR_AFTER)["rows"]
    predictions = {
        "base_seen_equal_3c_after": all(run[t]["answer"] == prior[t]["answer"] for run in per["base"] for t in SEEN),
        "base_past_ceiling_fail": not any(any_pass("base", t) for t in NEW_PAST_CEILING),
        "base_doc52_passes_no_tool": all(run["doc-52"]["passed"] and not run["doc-52"]["tools"] for run in per["base"]),
        "nudge_unchanged_tasks_identical_to_base": all(
            n[t]["answer"] == b[t]["answer"] and n[t]["tools"] == b[t]["tools"] for n, b in zip(per["nudge"], per["base"]) for t in UNCHANGED_BY_NUDGE
        ),
        "nudge_fires_on_40_44_47": all(all_runs("nudge", t, "nudged") for t in NUDGE_EXPECTED),
        "nudge_past_ceiling_still_fail": not any(any_pass("nudge", t) for t in NEW_PAST_CEILING),
        "nudge_doc52_equals_base": all(n["doc-52"]["answer"] == b["doc-52"]["answer"] for n, b in zip(per["nudge"], per["base"])),
        "both_doc52_passes_no_tool": all(run["doc-52"]["passed"] and not run["doc-52"]["tools"] for run in per["both"]),
        "both_search_finds_answer_in_49_or_50": any(all_runs("both", t, "found_by_search") for t in NEW_PAST_CEILING),
        "both_doc53_fails": not any_pass("both", "doc-53"),
        **{f"{arm}_r1_equals_r2": all(r1[t]["answer"] == r2[t]["answer"] for t in PASTE_TASKS) for arm, (r1, r2) in per.items()},
    }

    def per_arm(fn):
        return {arm: [fn(run) for run in arm_runs] for arm, arm_runs in per.items()}

    middle = tuple(ANSWER_CHUNKS)
    result = {
        "preconditions": preconditions,
        "others_differ_base_vs_both": others_differ,
        "hashes": {arm: [{h: run["manifest"][h][:12] for h in HASHES} | {"dataset": run["manifest"]["dataset"]["sha256"][:12], "commit": run["manifest"].get("commit")} for run in arm_runs] for arm, arm_runs in runs.items()},
        "score": per_arm(lambda run: sum(run[t]["passed"] for t in PASTE_TASKS)),
        "score_new": per_arm(lambda run: sum(run[t]["passed"] for t in PASTE_TASKS if t not in SEEN)),
        "passed": per_arm(lambda run: sorted(t for t in PASTE_TASKS if run[t]["passed"])),
        "opens": per_arm(lambda run: sorted(t for t in PASTE_TASKS if run[t]["opens"])),
        "reached": per_arm(lambda run: sorted(t for t in middle if run[t]["reached"])),
        "nudged": per_arm(lambda run: {t: run[t]["nudged"] for t in PASTE_TASKS if run[t]["nudged"]}),
        "searched": per_arm(lambda run: sorted(t for t in PASTE_TASKS if run[t]["searched"])),
        "found_by_search": per_arm(lambda run: sorted(t for t in middle if run[t]["found_by_search"])),
        "answered_after_search_without_read": per_arm(lambda run: sorted(t for t in PASTE_TASKS if run[t]["answered_after_search_without_read"])),
        "leak": per_arm(lambda run: sorted(t for t in PASTE_TASKS if run[t]["leak"])),
        "max_tokens_in": per_arm(lambda run: max((run[t]["tokens_in"] or 0) for t in PASTE_TASKS)),
        "fail_to_pass": {
            "base_to_nudge": fail_to_pass("base", "nudge", PASTE_TASKS),
            "nudge_to_both": fail_to_pass("nudge", "both", PASTE_TASKS),
        },
        "pass_to_fail": {"base_to_nudge": pass_to_fail("base", "nudge"), "nudge_to_both": pass_to_fail("nudge", "both")},
        "b3_k": k,
        "predictions": predictions,
        "rule": rule,
        "proposals": proposals,
        "tasks": per,
    }
    (HERE / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "tasks"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
