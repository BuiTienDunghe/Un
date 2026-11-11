"""Count, for one Agent Eval run, which tasks called a tool by the model's own choice and which only
after the harness sent the turn back. NOT RUN YET (written 11/11 with nothing allowed to run).

    .venv/Scripts/python.exe -X utf8 backend/scripts/count_self_chosen.py <run_dir> [<run_dir> ...]

This is the definition .scratch/harness-research/PREREGISTRATION-2b-baseline.md fixes ("Cách phân tích"); the numbers its
decision table reads come from here, not from the grader's pass count.

A task's steps are its lines of events.jsonl that carry `step_index`, in that order. A step is a NUDGE
when its kind is one of NUDGES: the harness rejected what the model wrote, or did the work itself, and
gave the turn another round. Then, for one task:

- self-chosen call: a `tool_call` step that the code did not make (`by_code` and `constrained` both
  absent) with NO nudge step before it;
- nudged call: such a step with at least one nudge step before it, and no self-chosen call in the task.

A task with both kinds counts as self-chosen. A call the code made itself (read_rest's reads, the promise
check's filled call) is neither: the model did not write it.

A `tool_call_error` step is a call the model wrote that Ollama could not parse. It is the model choosing
to call, so it counts exactly like a `tool_call` (self-chosen with no nudge before it), under the name
"(unparsed)", and the tasks where it happened are also listed on their own.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

# answer_check: figures the turn saw nowhere; lookup_check: gave up before looking; read_on_check: stopped at
# excerpts; promise_check: said it did what only a tool does; read_rest: the code read the rest itself.
NUDGES = ("answer_check", "lookup_check", "read_on_check", "promise_check", "read_rest")


def classify(steps: list[dict]) -> dict:
    """{"self": [tool names], "nudged": {nudge kind: [tool names]}} for one task's steps, in order."""
    seen: list[str] = []
    own: list[str] = []
    nudged: dict[str, list[str]] = defaultdict(list)
    for step in steps:
        kind = step.get("kind")
        if kind in NUDGES:
            seen.append(kind)
        elif kind == "tool_call_error" or (kind == "tool_call" and not step.get("by_code") and not step.get("constrained")):
            name = "(unparsed)" if kind == "tool_call_error" else str(step.get("tool_name"))
            if seen:
                nudged[seen[-1]].append(name)
            else:
                own.append(name)
    return {"self": own, "nudged": dict(nudged)}


def report(run_dir: Path) -> dict:
    steps: dict[str, list[dict]] = defaultdict(list)
    for raw in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines():
        if raw.strip():
            event = json.loads(raw)
            if "step_index" in event:
                steps[event["task_id"]].append(event)
    results = [json.loads(raw) for raw in (run_dir / "task_results.jsonl").read_text(encoding="utf-8").splitlines() if raw.strip()]
    rows = {}
    for result in results:
        ordered = sorted(steps.get(result["task_id"], []), key=lambda event: event["step_index"])
        rows[result["task_id"]] = {"category": result["category"], "passed": result["passed"], **classify(ordered)}
    quiet = {task_id: row for task_id, row in rows.items() if row["category"] == "no_tool"}
    self_chosen = sorted(task_id for task_id, row in quiet.items() if row["self"])
    only_nudged = sorted(task_id for task_id, row in quiet.items() if not row["self"] and row["nudged"])
    by_nudge: dict[str, list[str]] = defaultdict(list)
    for task_id in only_nudged:
        for kind in quiet[task_id]["nudged"]:
            by_nudge[kind].append(task_id)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    return {
        "run": run_dir.name,
        "clock_note": manifest.get("clock_note"),
        "discord_persona": manifest.get("discord_persona_sha256") is not None,
        "no_tool_tasks": len(quiet),
        "self_chosen": {"count": len(self_chosen), "tasks": {task_id: quiet[task_id]["self"] for task_id in self_chosen}},
        "nudged_only": {"count": len(only_nudged), "by_nudge": dict(by_nudge)},
        "unparsed_calls": sorted(task_id for task_id, row in quiet.items() if "(unparsed)" in row["self"] or any("(unparsed)" in names for names in row["nudged"].values())),
        "other_tasks": {task_id: {"passed": row["passed"], "self": row["self"], "nudged": row["nudged"]} for task_id, row in rows.items() if row["category"] != "no_tool"},
    }


def main() -> int:
    for argument in sys.argv[1:]:
        print(json.dumps(report(Path(argument)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
