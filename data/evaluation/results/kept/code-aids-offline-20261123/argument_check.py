"""Offline check of agent.validate_arguments (23/11/2026). No model, no GPU, no database.

Every tool call recorded in a kept Agent Eval run (task_results.jsonl, the calls exactly as the model
wrote them) is put through tool_arguments.check_arguments with the schema Agent Eval shows for that
tool (core_tools() plus search_history, as scripts.agent_eval builds it). Counted: how many calls the
check would have converted, how many it would have refused, and, for each refusal, whether the task
passed anyway, which is the case to fear: a refusal of a call the tool ran correctly.

A run kept twice (a copy under another folder) is counted twice; the numbers are calls as stored.

Run from the repo root:  .venv\\Scripts\\python.exe -I data\\evaluation\\results\\kept\\code-aids-offline-20261123\\argument_check.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "backend"))
from app.discord import agent_tools  # noqa: E402
from app.services.agent_service import core_tools  # noqa: E402
from app.services.tool_arguments import check_arguments  # noqa: E402

KEPT = ROOT / "data" / "evaluation" / "results" / "kept"

registry = core_tools()
agent_tools.register(registry, None)
parameters = {tool.name: tool.schema["function"]["parameters"] for tool in registry.tools()}

totals: Counter[str] = Counter()
by_model: dict[str, Counter[str]] = {}
coerced_examples: list[dict] = []
refused: list[dict] = []
files = sorted(KEPT.rglob("task_results.jsonl"))
for path in files:
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        model = str(row.get("model") or "?")
        counts = by_model.setdefault(model, Counter())
        totals["tasks"] += 1
        counts["tasks"] += 1
        for call in row.get("tool_calls") or []:
            totals["calls"] += 1
            counts["calls"] += 1
            name = call.get("name")
            if name not in parameters:
                totals["calls_to_undeclared_names"] += 1
                continue
            checked = check_arguments(call.get("arguments"), parameters[name])
            if checked.coerced:
                totals["coerced"] += 1
                counts["coerced"] += 1
                if len(coerced_examples) < 20:
                    coerced_examples.append({"run": str(path.parent.relative_to(KEPT)), "task": row.get("task_id"), "tool": name,
                                             "paths": checked.coerced, "arguments": call.get("arguments")})
            if checked.problems:
                totals["refused"] += 1
                counts["refused"] += 1
                refused.append({"run": str(path.parent.relative_to(KEPT)), "task": row.get("task_id"), "model": model, "tool": name,
                                "problems": checked.problems, "arguments": call.get("arguments"), "task_passed": row.get("passed")})

summary = {
    "result_files": len(files),
    **totals,
    "refused_in_passed_tasks": sum(1 for item in refused if item["task_passed"]),
    "by_model": {model: dict(counts) for model, counts in sorted(by_model.items())},
}
out = Path(__file__).with_name("argument_check.json")
out.write_text(json.dumps({"summary": summary, "coerced_examples": coerced_examples, "refused": refused}, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=2))
for item in refused[:20]:
    print(item)
for item in coerced_examples[:10]:
    print(item)
