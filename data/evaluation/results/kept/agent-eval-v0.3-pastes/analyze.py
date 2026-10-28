"""Ticket 20 #3 (long pastes) against #2, by PREREGISTRATION.md's rule.

    python analyze.py   # writes analysis.json beside this file
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEPT = HERE.parent
BASE = KEPT / "agent-eval-v0.3-answer-check" / "v0.3-check-r1-cold"
RUNS = [HERE / "v0.3-paste-r1-cold", HERE / "v0.3-paste-r2-cold"]
PASTE_TASK = "doc-39"
HASHES = ("tools_sha256", "agent_guide_sha256", "system_prompt_sha256")


def load(run: Path) -> dict:
    rows = {r["task_id"]: r for r in map(json.loads, (run / "task_results.jsonl").read_text(encoding="utf-8").splitlines())}
    events: dict[str, list] = {}
    for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        events.setdefault(event["task_id"], []).append(event)
    return {"manifest": json.loads((run / "manifest.json").read_text(encoding="utf-8")), "rows": rows, "events": events}


def doc39(run: dict) -> dict:
    row, steps = run["rows"][PASTE_TASK], run["events"].get(PASTE_TASK, [])
    reads = [
        {key: (e.get("arguments") or {}).get(key) for key in ("document_id", "from_chunk", "n")}
        for e in steps if e["kind"] == "tool_call" and e.get("tool_name") == "read_document"
    ]
    return {
        "passed": row["passed"],
        "error": row["error"],
        "model_rounds": row["model_rounds"],
        "tool_calls": row["tool_calls"],
        "read_document": reads,
        "reads_the_paste": any(str(r.get("document_id") or "").startswith("paste_") for r in reads),
        "answer_check": any(e["kind"] == "answer_check" for e in steps),
        "max_step_tokens_in": max((e.get("tokens_in") or 0 for e in steps), default=0),
        "tokens_in": row["tokens_in"],
        "answer": row["answer"],
    }


def main() -> None:
    base = load(BASE)
    r1, r2 = (load(run) for run in RUNS)
    others = [t for t in base["rows"] if t != PASTE_TASK]
    differ = sorted(t for t in others if base["rows"][t]["answer"] != r1["rows"][t]["answer"])
    reached = doc39(r1)
    result = {
        "hashes_equal_to_2": {h: r1["manifest"][h] == base["manifest"][h] for h in HASHES},
        "input_max_chars": {"#2": base["manifest"].get("input_max_chars"), "#3": r1["manifest"].get("input_max_chars")},
        "score": {side: sum(r["passed"] for r in run["rows"].values()) for side, run in (("#2", base), ("r1", r1), ("r2", r2))},
        "others_differ_from_2": differ,
        "doc39": {"#2": doc39(base), "r1": reached},
        "r1_equals_r2": all(r1["rows"][t]["answer"] == r2["rows"][t]["answer"] for t in r1["rows"]),
    }
    result["rule"] = {
        "others_identical": not differ,
        "doc39_reaches_agent": reached["error"] is None and reached["model_rounds"] >= 1,
        "doc39_reads_paste": reached["reads_the_paste"],
    }
    result["rule"]["propose_ship"] = all(result["rule"].values())
    (HERE / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
