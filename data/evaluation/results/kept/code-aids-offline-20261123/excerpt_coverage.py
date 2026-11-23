"""Offline check of agent.focused_excerpts (23/11/2026). No model, no GPU, no database.

For every Agent Eval v0 documents task with must_mention patterns: take the chunks the eval replays for
it (retrieval.jsonl), build the search excerpt both ways (the first 400 characters, and
excerpts.focused_excerpt), and ask whether every required pattern appears in the excerpts the model would
see. The query is the one qwen3.5:2b actually wrote in its first search_documents call on 10/11 (kept run
c57-compare-20261110/ae/ae-C-main-2b); a task where it wrote none falls back to the recorded retrieval
query, and is reported as such.

Run from the repo root:  .venv\\Scripts\\python.exe -I data\\evaluation\\results\\kept\\code-aids-offline-20261123\\excerpt_coverage.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "backend"))
from app.services.agent_service import SEARCH_EXCERPT_CHARS, _clip  # noqa: E402
from app.services.excerpts import focused_excerpt  # noqa: E402

DATASET = ROOT / "data" / "benchmarks" / "agent_eval" / "v0"
RUN = ROOT / "data" / "evaluation" / "results" / "kept" / "c57-compare-20261110" / "ae" / "ae-C-main-2b"


def lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


tasks = lines(DATASET / "tasks.jsonl")
retrieval = {row["task_id"]: row for row in lines(DATASET / "retrieval.jsonl")}
small = {row["task_id"]: row for row in lines(RUN / "task_results.jsonl")}

rows = []
for task in tasks:
    patterns = (task.get("expect") or {}).get("must_mention") or []
    record = retrieval.get(task["id"])
    if task.get("category") != "documents" or not patterns or not record or not record.get("chunks"):
        continue
    searches = [c for c in small.get(task["id"], {}).get("tool_calls") or [] if c["name"] == "search_documents"]
    query, source = (searches[0]["arguments"].get("query"), "2b") if searches else (record.get("query") or task["input"], "recorded")
    contents = [str(chunk.get("content") or "") for chunk in record["chunks"]]
    if not any(all(re.search(p, c, re.IGNORECASE) for p in patterns) or any(re.search(p, c, re.IGNORECASE) for p in patterns) for c in contents):
        continue  # the answer is in no replayed chunk: nothing an excerpt can show

    def covered(excerpts: list[str]) -> bool:
        return all(any(re.search(p, e, re.IGNORECASE) for e in excerpts) for p in patterns)

    heads = [_clip(c, SEARCH_EXCERPT_CHARS) for c in contents]
    focused = [focused_excerpt(c, query, SEARCH_EXCERPT_CHARS)[0] for c in contents]
    full = covered(contents)
    rows.append({
        "task": task["id"], "query_from": source, "answer_in_chunks": full,
        "head_covers": covered(heads), "focused_covers": covered(focused),
        "moved": sum(1 for h, f in zip(heads, focused) if h != f), "chunks": len(contents),
        "2b_passed": small.get(task["id"], {}).get("passed"),
        "2b_read_document_calls": sum(1 for c in small.get(task["id"], {}).get("tool_calls") or [] if c["name"] == "read_document"),
    })

summary = {
    "tasks": len(rows),
    "answer_in_replayed_chunks": sum(r["answer_in_chunks"] for r in rows),
    "head_excerpt_covers": sum(r["head_covers"] for r in rows),
    "focused_excerpt_covers": sum(r["focused_covers"] for r in rows),
    "gained": [r["task"] for r in rows if r["focused_covers"] and not r["head_covers"]],
    "lost": [r["task"] for r in rows if r["head_covers"] and not r["focused_covers"]],
}
out = Path(__file__).with_name("excerpt_coverage.json")
out.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False))
for row in rows:
    print(row)
