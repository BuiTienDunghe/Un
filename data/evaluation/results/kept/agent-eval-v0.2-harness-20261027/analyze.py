"""Ticket 10 analysis, as pre-registered. Usage: analyze.py <results_dir> <out_json>"""
import json
import sys
from pathlib import Path

results, out_path = Path(sys.argv[1]), Path(sys.argv[2])
TARGET = {"1a": ["doc-10", "doc-22", "doc-25", "doc-30", "stat-02"], "2b": ["hist-07", "hist-03"]}
# B = A+1a, C = A+2b (the stacking rule fired: 1a lost 5 untargeted for 3 targets),
# D = A+1a+2b (supplementary).
CONDITIONS = {
    "A": {"t0": "v0.2-base-r2-warm", "t04": ["v0.2-A-t04-r1", "v0.2-A-t04-r2", "v0.2-A-t04-r3"], "targets": []},
    "B": {"t0": "v0.2-B-t0", "warmup": "v0.2-B-warmup-discard", "t04": ["v0.2-B-t04-r1", "v0.2-B-t04-r2", "v0.2-B-t04-r3"], "targets": ["1a"]},
    "C": {"t0": "v0.2-C-t0", "warmup": "v0.2-C-warmup-discard", "t04": ["v0.2-C-t04-r1", "v0.2-C-t04-r2", "v0.2-C-t04-r3"], "targets": ["2b"]},
    "D": {"t0": "v0.2-D-t0", "warmup": "v0.2-D-warmup-discard", "t04": ["v0.2-D-t04-r1", "v0.2-D-t04-r2", "v0.2-D-t04-r3"], "targets": ["1a", "2b"]},
}


def load(run):
    path = results / run / "task_results.jsonl"
    if not path.exists():
        return None
    return {r["task_id"]: r for r in map(json.loads, path.read_text(encoding="utf-8").splitlines())}


def failed_check(result, name):
    return any(c["check"].startswith(name) and not c["passed"] for c in result["grade"]["checks"])


def profile(runs):
    return {
        "passed": sum(r["passed"] for r in runs.values()),
        "tools_required_fail": sorted(t for t, r in runs.items() if failed_check(r, "tools_required")),
        "tools_forbidden_fail": sorted(t for t, r in runs.items() if failed_check(r, "tools_forbidden")),
    }


report = {}
base = load(CONDITIONS["A"]["t0"])
for name, spec in CONDITIONS.items():
    t0 = load(spec["t0"])
    if t0 is None:
        continue
    entry = {"t0": profile(t0)}
    if spec.get("warmup") and load(spec["warmup"]):
        warm = load(spec["warmup"])
        entry["warmup_vs_t0_same_answers"] = sum(warm[t]["answer"] == t0[t]["answer"] for t in t0)
    if name != "A":
        targets = [t for group in spec["targets"] for t in TARGET[group]]
        entry["t0_vs_A"] = {
            "targets_passed_A": [t for t in targets if base[t]["passed"]],
            "targets_passed": [t for t in targets if t0[t]["passed"]],
            "non_target_gained": sorted(t for t in t0 if t not in targets and t0[t]["passed"] and not base[t]["passed"]),
            "non_target_lost": sorted(t for t in t0 if t not in targets and not t0[t]["passed"] and base[t]["passed"]),
        }
    runs04 = [r for r in (load(x) for x in spec["t04"]) if r]
    if runs04:
        entry["t04_totals"] = [sum(r[t]["passed"] for t in r) for r in runs04]
        entry["t04_target_pass"] = {
            group: f"{sum(r[t]['passed'] for r in runs04 for t in ids)}/{len(ids) * len(runs04)}"
            for group, ids in TARGET.items()
        }
        entry["t04_tools_forbidden_fails"] = [len(profile(r)["tools_forbidden_fail"]) for r in runs04]
        entry["t04_per_task_failrate"] = {
            t: sum(not r[t]["passed"] for r in runs04) for t in runs04[0] if any(not r[t]["passed"] for r in runs04)
        }
    report[name] = entry
out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=1))
