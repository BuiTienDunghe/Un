"""Ticket 22 C4 (pluggable registry): main before C4 against C4, by PREREGISTRATION.md.

    python analyze.py   # writes analysis.json beside this file
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIDES = {"A": HERE / "v0.3-c4-A-cold", "C4": HERE / "v0.3-c4-C4-cold"}
EXPECTED_TOOLS_SHA = "153209652c0672a2337be105bd711a1e343a9c7bdf93911e7d14dba18a75e500"
HASHES = ("tools_sha256", "agent_guide_sha256", "system_prompt_sha256")
STEP_KEYS = ("kind", "tool_name", "tool_declared", "arguments", "arguments_shape", "error_code")
WEB_HIST = ("hist-08", "hist-09", "hist-10")


def load(run: Path) -> dict:
    rows = {r["task_id"]: r for r in map(json.loads, (run / "task_results.jsonl").read_text(encoding="utf-8").splitlines())}
    events: dict[str, list] = {}
    for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        events.setdefault(event["task_id"], []).append({key: event.get(key) for key in STEP_KEYS})
    return {"manifest": json.loads((run / "manifest.json").read_text(encoding="utf-8")), "rows": rows, "events": events}


def first_difference(a: dict, b: dict, task: str) -> dict | None:
    """Stop at the first place a task differs, as the rule asks."""
    steps_a, steps_b = a["events"].get(task, []), b["events"].get(task, [])
    for index, (x, y) in enumerate(zip(steps_a, steps_b)):
        if x != y:
            return {"step": index, "A": x, "C4": y}
    if len(steps_a) != len(steps_b):
        return {"step": min(len(steps_a), len(steps_b)), "A_steps": len(steps_a), "C4_steps": len(steps_b)}
    if a["rows"][task]["answer"] != b["rows"][task]["answer"]:
        return {"step": "answer", "A": a["rows"][task]["answer"], "C4": b["rows"][task]["answer"]}
    return None


def main() -> None:
    a, c4 = (load(run) for run in SIDES.values())
    hashes = {h: [a["manifest"][h], c4["manifest"][h]] for h in HASHES}
    preconditions = {
        "tools_sha_equal": hashes["tools_sha256"][0] == hashes["tools_sha256"][1],
        "tools_sha_is_registered_value": hashes["tools_sha256"][0] == EXPECTED_TOOLS_SHA,
        "guide_and_system_equal": all(hashes[h][0] == hashes[h][1] for h in ("agent_guide_sha256", "system_prompt_sha256")),
    }
    differences = {t: d for t in a["rows"] if (d := first_difference(a, c4, t))}
    hist = {
        t: [e["tool_name"] for e in c4["events"].get(t, []) if e["kind"] == "tool_call"]
        for t in sorted(c4["rows"]) if t.startswith("hist-")
    }
    unavailable = {
        t: [e["error_code"] for e in c4["events"].get(t, []) if e["kind"] == "tool_result"] for t in WEB_HIST
    }
    result = {
        "commits": {side: load(run)["manifest"]["commit"] for side, run in SIDES.items()},
        "hashes": hashes,
        "preconditions": preconditions,
        "score": {"A": sum(r["passed"] for r in a["rows"].values()), "C4": sum(r["passed"] for r in c4["rows"].values())},
        "answers_identical": sum(a["rows"][t]["answer"] == c4["rows"][t]["answer"] for t in a["rows"]),
        "tasks": len(a["rows"]),
        "first_differences": differences,
        "hist_tool_calls_C4": hist,
        "web_hist_error_codes_C4": unavailable,
    }
    result["rule"] = {
        "answers_48_identical": result["answers_identical"] == len(a["rows"]),
        "traces_identical": not differences,
        "web_hist_unavailable": all("TOOL_UNAVAILABLE_HERE" in codes for codes in unavailable.values()),
    }
    result["rule"]["keeps_behaviour"] = all(preconditions.values()) and all(result["rule"].values())
    (HERE / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
