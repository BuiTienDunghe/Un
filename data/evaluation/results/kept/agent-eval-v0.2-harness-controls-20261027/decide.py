"""Apply ticket 16 step 5's pre-registered checks (Comments, 27/10 23:02) to the runs kept here.

Usage, from the repo root: python data/evaluation/results/kept/agent-eval-v0.2-harness-controls-20261027/decide.py
Writes analysis.json next to this file. The 22:31 cold baseline is read from agent-eval-v0.2-1a-v2-20261027/.
"""
import json
import re
import sys
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
A_2231 = HERE.parent / "agent-eval-v0.2-1a-v2-20261027" / "v0.2-1a2-A-cold"
TARGETS = ["hist-08", "hist-09", "hist-10"]
HASHES = ["agent_guide_sha256", "system_prompt_sha256", "discord_context_sha256", "tools_sha256"]
DECLARED = {"search_documents", "search_history", "system_status"}
KINDS = {"tool_call", "tool_result", "final"}
CODES = {"TOOL_UNAVAILABLE_HERE", "BAD_ARGUMENTS", "UNKNOWN_TOOL", "TOOL_FAILED", "TOOL_TIMEOUT"}
STOPS = {"final", "max_steps", "turn_budget", "turn_budget_exhausted"}
IDENT = re.compile(r"^[A-Za-z_][\w.]*$")
HEX = re.compile(r"^[0-9a-f]{64}$")
SHAPE = re.compile(r"^str:\d+$")


def load(run):
    rows = (run / "task_results.jsonl").read_text(encoding="utf-8").splitlines()
    return {r["task_id"]: r for r in map(json.loads, rows)}


def events(run):
    return [json.loads(line) for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines()]


def manifest(run):
    return json.loads((run / "manifest.json").read_text(encoding="utf-8"))


def summary_row(step, source):
    """What PostgresAuxiliaryStore.add_agent_traces writes to agent_trace_summaries for one step."""
    name = step.get("tool_name") or None
    content = step.get("content")
    return {
        "kind": str(step.get("kind", "tool_call")),
        "tool_name": name if step.get("tool_declared") else ("unknown" if name else None),
        "latency_ms": step.get("latency_ms"),
        "error_code": step.get("error_code") or None,
        "error_type": step.get("error_type") or None,
        "stop_reason": step.get("stop_reason") or None,
        "arguments_shape": step.get("arguments_shape") if isinstance(step.get("arguments_shape"), dict) else None,
        "content_sha256": sha256(str(content).encode("utf-8")).hexdigest() if content is not None else None,
        "source": source,
    }


def outside_vocabulary(row):
    bad = []
    allowed = {"kind": KINDS, "error_code": CODES, "stop_reason": STOPS, "source": {"web", "discord"}}
    for key, values in allowed.items():
        if row[key] is not None and row[key] not in values:
            bad.append((key, row[key]))
    if row["tool_name"] is not None and row["tool_name"] not in DECLARED | {"unknown"}:
        bad.append(("tool_name", row["tool_name"]))
    if row["error_type"] is not None and not IDENT.match(row["error_type"]):
        bad.append(("error_type", row["error_type"]))
    if row["content_sha256"] is not None and not HEX.match(row["content_sha256"]):
        bad.append(("content_sha256", row["content_sha256"]))
    for key, value in (row["arguments_shape"] or {}).items():
        ok = isinstance(value, (int, float)) if key == "_undeclared" else (isinstance(value, (int, float)) or (isinstance(value, str) and SHAPE.match(value)))
        if not ok:
            bad.append(("arguments_shape", key))
    return bad


A_run, B_run = HERE / "v0.2-16-A-cold", HERE / "v0.2-16-B-cold"
A, B, A0 = load(A_run), load(B_run), load(A_2231)
order = list(A)
first_diff = next((t for t in order if A[t]["answer"] != B[t]["answer"]), None)
before_hist08 = order[: order.index("hist-08")]
out = {
    "hashes_equal": {h: manifest(A_run)[h] == manifest(B_run)[h] for h in HASHES},
    "commits": {"A": manifest(A_run)["commit"][:7], "B": manifest(B_run)["commit"][:7]},
    "dirty": {"A": manifest(A_run)["worktree_dirty"], "B": manifest(B_run)["worktree_dirty"]},
    "A_same_as_2231": sum(A[t]["answer"] == A0[t]["answer"] for t in A),
    "same_before_hist08": sum(A[t]["answer"] == B[t]["answer"] for t in before_hist08),
    "of_before_hist08": len(before_hist08),
    "first_answer_diff": first_diff,
    "answers_differ": [t for t in order if A[t]["answer"] != B[t]["answer"]],
    "passed": {"A": sum(r["passed"] for r in A.values()), "B": sum(r["passed"] for r in B.values())},
    "flips": {
        "gained": [t for t in order if B[t]["passed"] and not A[t]["passed"]],
        "lost": [t for t in order if A[t]["passed"] and not B[t]["passed"]],
    },
    "targets": {t: {"A": A[t]["passed"], "B": B[t]["passed"]} for t in TARGETS},
}
out["rule"] = {
    "total_not_lower": out["passed"]["B"] >= out["passed"]["A"],
    "no_target_lost": not any(A[t]["passed"] and not B[t]["passed"] for t in TARGETS),
}
out["rule"]["no_regression"] = all(out["rule"].values())

surface = {t: r.get("surface") for t, r in B.items()}
steps = [e for e in events(B_run) if e.get("kind") in KINDS]
rounds = [e for e in events(B_run) if e.get("kind") == "model_round"]
finals = [s for s in steps if s["kind"] == "final"]
out["budget"] = {
    "stop_reasons": {r: sum(s.get("stop_reason") == r for s in finals) for r in sorted(STOPS)},
    "finals": len(finals),
    "slowest_task_ms": max((r["latency_ms"], t) for t, r in B.items()),
}
rows = [(s["task_id"], summary_row(s, "discord" if surface.get(s["task_id"]) == "discord" else "web"), s) for s in steps]
out["summary_checks"] = {
    "1_missing_latency": [t for t, row, _ in rows if row["latency_ms"] is None],
    "2_final_without_stop_reason": [t for t, row, _ in rows if row["kind"] == "final" and row["stop_reason"] is None],
    "3_tool_call_without_declared_or_shape": [
        t for t, row, s in rows if row["kind"] == "tool_call" and ("tool_declared" not in s or row["arguments_shape"] is None)
    ],
    "4_targets_without_unavailable_code": [
        t for t in TARGETS
        if not any(tt == t and row["kind"] == "tool_result" and row["error_code"] == "TOOL_UNAVAILABLE_HERE" for tt, row, _ in rows)
    ],
    "5_outside_vocabulary": [(t, bad) for t, row, _ in rows if (bad := outside_vocabulary(row))],
}
out["summary_checks_pass"] = not any(out["summary_checks"].values())
out["summary_rows"] = len(rows)
out["error_codes_seen"] = sorted({row["error_code"] for _, row, _ in rows if row["error_code"]})
out["tokens"] = {
    "steps_with_tokens": sum(s.get("tokens_in") is not None for s in steps),
    "model_rounds": len(rounds),
    "model_rounds_with_tokens": sum(r.get("tokens_in") is not None for r in rounds),
}
(HERE / "analysis.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=1))
for t in TARGETS:
    print(t, "B:", B[t]["answer"].replace("\n", " / "))
