"""Apply the 1a-v2 ship rule pre-registered in ticket 10 (27/10 21:15 + 21:45) to the runs kept here.

Usage, from the repo root: python data/evaluation/results/kept/agent-eval-v0.2-1a-v2-20261027/decide.py
Writes analysis.json next to this file. B (the first 1a) and the 19:43 cold baseline are read from the
sibling folder agent-eval-v0.2-harness-20261027/.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
V02 = HERE.parent / "agent-eval-v0.2-harness-20261027"
TARGETS = ["doc-10", "doc-22", "doc-25", "doc-30", "stat-02"]
WATCH = ["doc-17", "doc-19", "doc-26", "doc-27", "doc-28", "hist-03", "hist-05"]
CITE = ["doc-26", "doc-27", "doc-28"]
HIST = ["hist-03", "hist-07"]


def load(path):
    rows = (path / "task_results.jsonl").read_text(encoding="utf-8").splitlines()
    return {r["task_id"]: r for r in map(json.loads, rows)}


def cite_lost(res, t):
    return any(c["check"] == "citation" and not c["passed"] for c in res[t]["grade"]["checks"])


A, E, F = (load(HERE / f"v0.2-1a2-{x}-cold") for x in "AEF")
A_1943, B = load(V02 / "v0.2-base-r1-cold"), load(V02 / "v0.2-B-cold")
out = {
    "A_repeat_vs_19h43": {
        "same_answers": sum(A[t]["answer"] == A_1943[t]["answer"] for t in A),
        "of": len(A),
    },
    "E_vs_F_answers_differ": [t for t in E if E[t]["answer"] != F[t]["answer"]],
}
for name, X in (("A", A), ("B_first_1a", B), ("E", E), ("F", F)):
    out[name] = {
        "passed": sum(r["passed"] for r in X.values()),
        "targets": [t for t in TARGETS if X[t]["passed"]],
        "watch_lost_vs_A": [t for t in WATCH if A[t]["passed"] and not X[t]["passed"]],
        "citation_lost_26_28": [t for t in CITE if cite_lost(X, t)],
        "gained_vs_A": sorted(t for t in X if X[t]["passed"] and not A[t]["passed"]),
        "lost_vs_A": sorted(t for t in X if not X[t]["passed"] and A[t]["passed"]),
        "hist_calls": {t: [c["name"] for c in X[t]["tool_calls"]] for t in HIST},
    }
a, e, f = out["A"], out["E"], out["F"]
out["rule_E"] = {
    "total_ge_A": e["passed"] >= a["passed"],
    "targets_ge_A_plus_1": len(e["targets"]) >= len(a["targets"]) + 1,
    "watch_lost_le_1": len(e["watch_lost_vs_A"]) <= 1,
    "citation_lost_le_1": len(e["citation_lost_26_28"]) <= 1,
}
out["rule_E"]["ship_E"] = all(out["rule_E"].values())
# F can only replace a shippable E; the hand count of hist-03/07 is read from the answers, not here.
out["rule_F_total_ge_E"] = f["passed"] >= e["passed"]
out["F_passes_E_conditions"] = (
    f["passed"] >= a["passed"]
    and len(f["targets"]) >= len(a["targets"]) + 1
    and len(f["watch_lost_vs_A"]) <= 1
    and len(f["citation_lost_26_28"]) <= 1
)
(HERE / "analysis.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")
print(json.dumps({k: out[k] for k in ("rule_E", "rule_F_total_ge_E", "F_passes_E_conditions")}, indent=1))
