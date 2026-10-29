"""Ticket 20: the full v0.8 run on the commit that brings N1 to main, against its two references, by PREREGISTRATION.md.

    python analyze.py   # writes analysis.json beside this file

Committed with the preregistration, before the run.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEPT = HERE.parent
RUN = HERE / "v0.8-n1-gate-full"
PASTE_REF = KEPT / "agent-eval-v0.8-paste-arbitration" / "v0.8-arb-n1"
OTHER_REF = KEPT / "agent-eval-v0.7-paste-nudge-search" / "v0.7-3d-iso-base-full"
PASTE_TASKS = tuple(f"doc-{n}" for n in range(39, 58))
HASHES = ("tools_sha256", "agent_guide_sha256", "system_prompt_sha256")
TOOLS_SHA = ("153209", "a75e500")


def load(run: Path) -> dict:
    rows = {r["task_id"]: r for r in map(json.loads, (run / "task_results.jsonl").read_text(encoding="utf-8").splitlines())}
    events: dict[str, list] = {}
    for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        events.setdefault(event["task_id"], []).append(event)
    return {"manifest": json.loads((run / "manifest.json").read_text(encoding="utf-8")), "rows": rows, "events": events}


def tools(run: dict, task_id: str) -> list:
    return [(s.get("tool_name"), json.dumps(s.get("arguments"), ensure_ascii=False, sort_keys=True)) for s in run["events"].get(task_id, []) if s["kind"] == "tool_call"]


def main() -> None:
    run, paste_ref, other_ref = load(RUN), load(PASTE_REF), load(OTHER_REF)
    m = run["manifest"]
    others = sorted(set(run["rows"]) - set(PASTE_TASKS))
    preconditions = {
        **{h: m[h] == paste_ref["manifest"][h] == other_ref["manifest"][h] for h in HASHES},
        "tools_sha256_as_registered": m["tools_sha256"].startswith(TOOLS_SHA[0]) and m["tools_sha256"].endswith(TOOLS_SHA[1]),
        "dataset_v08_66": m["dataset"]["version"] == "agent-eval-v0.8" and len(run["rows"]) == 66,
        "dataset_same_as_paste_ref": m["dataset"]["sha256"] == paste_ref["manifest"]["dataset"]["sha256"],
        "unload_between_tasks": m.get("unload_between_tasks") is True,
        "paste_inline_key": (m.get("paste_inline") or {}).get("max_tokens") == 12_288,
        "others_47": len(others) == 47 and set(others) <= set(other_ref["rows"]),
    }

    def same(ref: dict, t: str) -> bool:
        return run["rows"][t]["answer"] == ref["rows"][t]["answer"] and tools(run, t) == tools(ref, t)

    differ = [t for t in PASTE_TASKS if not same(paste_ref, t)] + [t for t in others if not same(other_ref, t)]
    g1 = not differ
    result = {
        "preconditions": preconditions,
        "commit": m.get("commit"),
        "G1_all_66_identical": g1,
        "merge": all(preconditions.values()) and g1,
        "differ": {t: {"passed": run["rows"][t]["passed"], "ref_passed": (paste_ref if t in PASTE_TASKS else other_ref)["rows"][t]["passed"],
                       "answer": run["rows"][t]["answer"][:300]} for t in differ},
        "score": {"all": sum(r["passed"] for r in run["rows"].values()), "paste_19": sum(run["rows"][t]["passed"] for t in PASTE_TASKS),
                  "others_47": sum(run["rows"][t]["passed"] for t in others)},
        "ref_score": {"paste_19": sum(paste_ref["rows"][t]["passed"] for t in PASTE_TASKS), "others_47": sum(other_ref["rows"][t]["passed"] for t in others)},
        "errors": {t: r["error"][:80] for t, r in run["rows"].items() if r["error"]},
    }
    (HERE / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
