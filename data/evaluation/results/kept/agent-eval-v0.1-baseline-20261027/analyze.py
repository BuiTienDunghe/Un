"""Analyse the ticket-07 baseline runs. Usage: python analyze.py <results_dir> <dataset_dir> <out_json>"""
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

results_dir, dataset_dir, out_path = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
RUNS = ["baseline-v0.1-t0-seed42-r1", "baseline-v0.1-t0-seed42-r2", "baseline-v0.1-t0-seed42-r3", "baseline-v0.1-t0.4-noseed-r1"]
T0 = RUNS[:3]
EXCERPT = 399  # agent_service clips each chunk to 400 characters, the last being "…"


def jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


fixtures = {f["task_id"]: f for f in jsonl(dataset_dir / "retrieval.jsonl")}
# Chunks whose agent-visible excerpt says almost nothing another chunk's does not,
# computed from the recorded fixtures rather than listed by hand (fable's review,
# 27/10). "Almost": a shared opening of at least SHARED characters. An exact match
# would miss backup_restore.md 0-1: chunk 0 is the whole 388-character preamble and
# chunk 1's excerpt is that preamble plus 11 characters of a table header.
SHARED = 350
_excerpts = {}
for _fixture in fixtures.values():
    if _fixture["source"] == "recorded":
        for _chunk in _fixture["chunks"]:
            _excerpts[(_chunk["filename"], _chunk["chunk_index"])] = str(_chunk.get("content") or "")[:EXCERPT]
DUP = {
    a for a in _excerpts for b in _excerpts
    if a != b and len(os.path.commonprefix([_excerpts[a], _excerpts[b]])) >= SHARED
}
tasks = {t["id"]: t for t in jsonl(dataset_dir / "tasks.jsonl")}
data = {}
for run in RUNS:
    d = results_dir / run
    data[run] = {
        "manifest": json.loads((d / "manifest.json").read_text(encoding="utf-8")),
        "summary": json.loads((d / "summary.json").read_text(encoding="utf-8")),
        "results": {r["task_id"]: r for r in jsonl(d / "task_results.jsonl")},
        "events": jsonl(d / "events.jsonl"),
    }

report = {"runs": {}}
for run in RUNS:
    s, m = data[run]["summary"], data[run]["manifest"]
    events = data[run]["events"]
    truncated = sorted({e["task_id"] for e in events if e.get("kind") == "tool_result" and "…\n<<<HẾT" in (e.get("content") or "")})
    truncated_calls = sum(1 for e in events if e.get("kind") == "tool_result" and "…\n<<<HẾT" in (e.get("content") or ""))
    topks = Counter(
        (e.get("arguments") or {}).get("top_k", "default(4)")
        for e in events if e.get("kind") == "tool_call" and e.get("tool_name") == "search_documents"
    )
    # Which recorded tasks were handed a chunk whose first 400 characters repeat another chunk's.
    dup_exposed = set()
    for e in events:
        if e.get("kind") == "tool_call" and e.get("tool_name") == "search_documents":
            fx = fixtures.get(e["task_id"])
            if fx and fx["source"] == "recorded":
                k = (e.get("arguments") or {}).get("top_k", 4)
                try:
                    k = min(max(int(k), 1), 8)
                except (TypeError, ValueError):
                    k = 4
                if any((c["filename"], c["chunk_index"]) in DUP for c in fx["chunks"][:k]):
                    dup_exposed.add(e["task_id"])
    report["runs"][run] = {
        "temperature": m["temperature"], "seed": m["seed"], "verified": m["general_version"]["verified"],
        "dirty": m["worktree_dirty"], "commit": m["commit"][:7], "dataset_sha": m["dataset"]["sha256"][:12],
        "overall": s["overall"], "errors": s["errors"], "by_category": s["by_category"],
        "by_retrieval_source": s.get("by_retrieval_source"), "by_check": s["by_check"],
        "citation_verbatim": s.get("citation_verbatim"), "latency_ms": s["latency_ms"],
        "tokens_in_total": s["tokens_in_total"], "tokens_out_total": s["tokens_out_total"],
        "mean_tool_calls": s["mean_tool_calls"], "budget_exhausted": s["budget_exhausted"],
        "failed_tasks": s["failed_tasks"], "truncated_tool_results": {"calls": truncated_calls, "tasks": truncated},
        "search_documents_top_k": dict(topks), "recorded_tasks_with_duplicate_prefix_chunk": sorted(dup_exposed),
    }

ids = list(tasks)
per_task = {}
for tid in ids:
    pattern = "".join("P" if data[r]["results"][tid]["passed"] else "F" for r in RUNS)
    answers = [data[r]["results"][tid]["answer"] for r in T0]
    calls = [json.dumps(data[r]["results"][tid]["tool_calls"], ensure_ascii=False, sort_keys=True) for r in T0]
    per_task[tid] = {
        "category": tasks[tid]["category"], "pattern_t0x3_then_t04": pattern,
        "t0_answers_identical": len(set(answers)) == 1, "t0_tool_calls_identical": len(set(calls)) == 1,
        "failed_checks": {r: [c["check"] for c in data[r]["results"][tid]["grade"]["checks"] if not c["passed"]] for r in RUNS if not data[r]["results"][tid]["passed"]},
    }
report["per_task"] = per_task
t0_patterns = Counter(v["pattern_t0x3_then_t04"][:3] for v in per_task.values())
report["t0_stability"] = {
    "tasks": len(ids),
    "pass_pattern_counts": dict(t0_patterns),
    "flipping_tasks_t0": sorted(t for t, v in per_task.items() if len(set(v["pattern_t0x3_then_t04"][:3])) > 1),
    "identical_answers_all_3": sum(v["t0_answers_identical"] for v in per_task.values()),
    "identical_tool_calls_all_3": sum(v["t0_tool_calls_identical"] for v in per_task.values()),
}
report["t04_vs_t0_majority"] = sorted(
    t for t, v in per_task.items()
    if (v["pattern_t0x3_then_t04"][:3].count("P") >= 2) != (v["pattern_t0x3_then_t04"][3] == "P")
)
check_fail = defaultdict(Counter)
for run in RUNS:
    for tid, r in data[run]["results"].items():
        for c in r["grade"]["checks"]:
            if not c["passed"]:
                check_fail[run][c["check"].split(":")[0]] += 1
report["failed_checks_by_run"] = {r: dict(c) for r, c in check_fail.items()}
out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
for run, v in report["runs"].items():
    print(run, v["overall"], "err", v["errors"], "src", v["by_retrieval_source"], "lat p50", v["latency_ms"]["p50"], "trunc", v["truncated_tool_results"]["calls"], "dup", len(v["recorded_tasks_with_duplicate_prefix_chunk"]), "topk", v["search_documents_top_k"])
print("t0 stability", report["t0_stability"])
print("t0.4 differs from t0 majority on", report["t04_vs_t0_majority"])
print("failed checks", report["failed_checks_by_run"])
