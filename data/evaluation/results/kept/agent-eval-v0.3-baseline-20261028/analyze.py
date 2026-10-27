"""The v0.3 baseline (ticket 20) against its pre-registration (ticket 20 Comments, 28/10 00:10).

Usage, from the repo root: python data/evaluation/results/kept/agent-eval-v0.3-baseline-20261028/analyze.py
Writes analysis.json next to this file; reads ticket 16's cold run B for the 40 old tasks.
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
RUNS = HERE
KEPT = HERE.parent
NEW = ["doc-33", "doc-34", "doc-35", "doc-36", "doc-37", "doc-38", "doc-39", "hist-11"]
LONG = ["doc-33", "doc-34", "doc-35", "doc-36", "doc-37", "hist-11"]


def load(run):
    return {r["task_id"]: r for r in map(json.loads, (run / "task_results.jsonl").read_text(encoding="utf-8").splitlines())}


r1, r2 = load(RUNS / "v0.3-base-r1-cold"), load(RUNS / "v0.3-base-r2-cold")
b16 = load(KEPT / "agent-eval-v0.2-harness-controls-20261027" / "v0.2-16-B-cold")
m1 = json.loads((RUNS / "v0.3-base-r1-cold" / "manifest.json").read_text(encoding="utf-8"))
m16 = json.loads((KEPT / "agent-eval-v0.2-harness-controls-20261027" / "v0.2-16-B-cold" / "manifest.json").read_text(encoding="utf-8"))
s1 = json.loads((RUNS / "v0.3-base-r1-cold" / "summary.json").read_text(encoding="utf-8"))

out = {
    "manifest": {k: m1.get(k) for k in ("commit", "worktree_dirty", "temperature", "seed", "grader_version")}
    | {"verified": m1["general_version"]["verified"], "dataset": m1["dataset"].get("version"), "dataset_sha256": m1["dataset"].get("sha256", "")[:12]},
    "prompt_hashes_equal_16B": {k: m1[k] == m16[k] for k in ("agent_guide_sha256", "system_prompt_sha256", "discord_context_sha256", "tools_sha256")},
    "passed": {"r1": sum(r["passed"] for r in r1.values()), "r2": sum(r["passed"] for r in r2.values()), "of": len(r1)},
    "r1_equals_r2": sum(r1[t]["answer"] == r2[t]["answer"] for t in r1),
    "old40": {
        "passed_r1": sum(r1[t]["passed"] for t in b16),
        "passed_16B_v02_grader": sum(b16[t]["passed"] for t in b16),
        "answers_same_as_16B": sum(r1[t]["answer"] == b16[t]["answer"] for t in b16),
        "answers_differ_from_16B": [t for t in b16 if r1[t]["answer"] != b16[t]["answer"]],
        "verdict_flips_vs_16B": {t: [b16[t]["passed"], r1[t]["passed"]] for t in b16 if b16[t]["passed"] != r1[t]["passed"]},
    },
    "new": {
        t: {
            "passed": r1[t]["passed"],
            "failed_checks": [c["check"] for c in r1[t]["grade"]["checks"] if not c["passed"]],
            "calls": [c["name"] for c in r1[t]["tool_calls"]],
            "error": r1[t]["error"],
            "model_rounds": r1[t]["model_rounds"],
        }
        for t in NEW
    },
    "by_check": s1.get("by_check"),
}
out["prediction"] = {
    "long_read_all_fail": not any(r1[t]["passed"] for t in LONG),
    "doc39_refused": (r1["doc-39"]["error"] or "").startswith("INPUT_TOO_LONG") and r1["doc-39"]["model_rounds"] == 0,
    "doc38_passes": r1["doc-38"]["passed"],
    "r1_equals_r2": out["r1_equals_r2"] == len(r1),
}
(HERE / "analysis.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(json.dumps(out["prediction"], indent=1))
for t in NEW:
    print(t, "::", (r1[t]["answer"] or "")[:300].replace("\n", " / "))
