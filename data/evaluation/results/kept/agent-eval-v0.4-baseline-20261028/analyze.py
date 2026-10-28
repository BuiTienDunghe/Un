"""Agent Eval v0.4 baseline: what ticket 20's registration (02:00) asks to record. No ship rule.

    python analyze.py   # writes analysis.json beside this file
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = [HERE / "v0.4-base-r1-cold", HERE / "v0.4-base-r2-cold"]
NEW = ("doc-33", "doc-34", "doc-35", "doc-36", "doc-37", "doc-38", "doc-39", "hist-11")


def load(run: Path) -> dict:
    rows = {r["task_id"]: r for r in map(json.loads, (run / "task_results.jsonl").read_text(encoding="utf-8").splitlines())}
    events: dict[str, list] = {}
    for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        events.setdefault(event["task_id"], []).append(event)
    return {
        "manifest": json.loads((run / "manifest.json").read_text(encoding="utf-8")),
        "summary": json.loads((run / "summary.json").read_text(encoding="utf-8")),
        "rows": rows, "events": events,
    }


def check(row: dict, name: str) -> dict | None:
    return next((c for c in row["grade"]["checks"] if c["check"] == name), None)


def main() -> None:
    r1, r2 = (load(run) for run in RUNS)
    rows = r1["rows"]
    made_up = {t: check(r, "figures_without_lookup")["detail"] for t, r in rows.items()
               if (c := check(r, "figures_without_lookup")) and not c["passed"]}
    reads = {}
    for t, steps in r1["events"].items():
        calls = [{k: (e.get("arguments") or {}).get(k) for k in ("document_id", "from_chunk", "n")}
                 for e in steps if e["kind"] == "tool_call" and e.get("tool_name") == "read_document"]
        if calls:
            valid = check(rows[t], "args_valid")
            reads[t] = {"calls": calls, "args_valid": None if valid is None else valid["passed"], "detail": None if valid is None else valid["detail"]}
    doc39 = rows["doc-39"]
    result = {
        "commit": r1["manifest"]["commit"],
        "dataset": r1["manifest"]["dataset"]["version"],
        "grader": r1["manifest"]["grader_version"],
        "gpu_shared": r1["manifest"].get("gpu_shared"),
        "score": {"r1": r1["summary"]["overall"], "r2": r2["summary"]["overall"]},
        "new_8_passed": {t: rows[t]["passed"] for t in NEW},
        "figures_without_lookup_failed": made_up,
        "read_document": reads,
        "doc39": {
            "passed": doc39["passed"], "error": doc39["error"], "model_rounds": doc39["model_rounds"],
            "tool_calls": doc39["tool_calls"], "failed_checks": [c for c in doc39["grade"]["checks"] if not c["passed"]],
            "answer": doc39["answer"],
        },
        "failed": {t: [c["check"] for c in r["grade"]["checks"] if not c["passed"]] for t, r in sorted(rows.items()) if not r["passed"]},
        "r1_equals_r2": all(rows[t]["answer"] == r2["rows"][t]["answer"] for t in rows),
        "answers_differ_r1_r2": sorted(t for t in rows if rows[t]["answer"] != r2["rows"][t]["answer"]),
    }
    (HERE / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
