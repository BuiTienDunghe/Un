"""Record real retrieval for the Agent Eval's document tasks, once (ticket 07, Q4 b).

Every retrieval fixture marked `"source": "pending"` is a question about a real
document of the lab corpus. This posts its reference `query` ONCE to the running
API's /rag/search, so what is recorded is exactly what the shipped retrieval
returns (embedding, hybrid ranking, reranker), and writes the sources back in the
fixture shape the runner replays: filename, page, content, score, plus the ids a
reader needs to find the chunk again. The runner then replays them for any query
the model asks, cut to the model's top_k.

    cd backend
    PYTHONUTF8=1 python -m scripts.agent_eval_record_retrieval --env-file C:\\Users\\dungbt06\\local-ai-core\\.env

Writes retrieval.jsonl (the fixtures) and retrieval_manifest.json (how they were
recorded) in the dataset directory. Nothing is written unless every query
answered: a half-recorded dataset is worse than a pending one.

/rag/search clips to models.yaml rag.max_context_chunks (5), which no env var
overrides; the agent may ask for up to 8. The manifest records the clip.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from scripts.agent_eval import DATASET_DIR, PROJECT_ROOT, _read_jsonl
from scripts.agent_eval_grader import grade

# What /rag/search sends that the replay keeps: the four fields the agent reads,
# then provenance. `excerpt` is a display preview of `content` and is dropped.
KEPT_FIELDS = ("filename", "page", "content", "score", "document_id", "chunk_id", "chunk_index", "index_version", "heading_path")
AGENT_MAX_TOP_K = 8  # agent_service clamps search_documents.top_k to 1-8


def _write_lf(path: Path, text: str) -> None:
    # LF on disk like the rest of the dataset; load_dataset hashes LF bytes anyway.
    path.write_text(text, encoding="utf-8", newline="\n")


def answer_in_chunks(task: dict[str, Any], chunks: list[dict[str, Any]]) -> bool | None:
    """Do the recorded chunks hold every point the task requires? A recorded
    miss turns a document task into a retrieval test, which the agent eval
    does not measure, so the recorder reports it instead of hiding it."""
    patterns = task.get("expect", {}).get("must_mention") or []
    if not patterns:
        return None
    joined = "\n".join(str(chunk.get("content") or "") for chunk in chunks)
    return grade({"must_mention": patterns}, [], joined, {})["passed"]


def record(
    dataset_dir: Path,
    client: httpx.Client,
    *,
    task_ids: list[str] | None = None,
    max_context_chunks: int | None = None,
    commit: str = "unknown",
    progress: Any = print,
) -> dict[str, Any]:
    """Record the chosen fixtures (default: every `pending` one) and return the manifest."""
    fixtures = _read_jsonl(dataset_dir / "retrieval.jsonl")
    tasks = {task["id"]: task for task in _read_jsonl(dataset_dir / "tasks.jsonl")}
    chosen = [f for f in fixtures if (f["task_id"] in task_ids if task_ids else f["source"] == "pending")]
    if task_ids:
        unknown = sorted(set(task_ids) - {f["task_id"] for f in chosen})
        if unknown:
            raise ValueError(f"không có fixture cho: {', '.join(unknown)}")
    if not chosen:
        raise ValueError("không có fixture nào cần ghi")

    models = client.get("/models")
    models.raise_for_status()
    served = models.json()
    recorded: dict[str, dict[str, Any]] = {}
    for fixture in chosen:
        response = client.post("/rag/search", json={"message": fixture["query"], "top_k": AGENT_MAX_TOP_K})
        response.raise_for_status()
        body = response.json()
        chunks = [{key: source.get(key) for key in KEPT_FIELDS} for source in body["sources"]]
        found = answer_in_chunks(tasks.get(fixture["task_id"], {}), chunks)
        recorded[fixture["task_id"]] = {"chunks": chunks, "latency_ms": body.get("latency_ms"), "answer_in_chunks": found}
        progress(f"{fixture['task_id']:<8} {len(chunks)} chunks {body.get('latency_ms')}ms" + ("  ANSWER NOT IN CHUNKS" if found is False else ""))

    # Every query answered: only now does anything reach disk.
    for fixture in fixtures:
        if fixture["task_id"] in recorded:
            fixture["source"] = "recorded"
            fixture["chunks"] = recorded[fixture["task_id"]]["chunks"]
    _write_lf(dataset_dir / "retrieval.jsonl", "".join(json.dumps(f, ensure_ascii=False) + "\n" for f in fixtures))
    manifest = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "commit": commit,
        "api": str(client.base_url),
        "top_k_requested": AGENT_MAX_TOP_K,
        # Read from this checkout's models.yaml: the API does not expose it. A
        # replay asked for more than this many chunks gets this many.
        "max_context_chunks": max_context_chunks,
        "rag": served.get("rag"),
        "models": {role: served.get("models", {}).get(role) for role in ("embedding", "reranker")},
        "tasks": {
            task_id: {"chunks": len(item["chunks"]), "latency_ms": item["latency_ms"], "answer_in_chunks": item["answer_in_chunks"]}
            for task_id, item in recorded.items()
        },
    }
    _write_lf(dataset_dir / "retrieval_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def main(argv: list[str] | None = None) -> int:
    from scripts.agent_eval import build_settings

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=DATASET_DIR)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--tasks", help="comma-separated task ids to (re-)record (default: every pending fixture)")
    parser.add_argument("--env-file", type=Path, help="the .env holding LOCAL_AI_API_KEY (default: this checkout's)")
    args = parser.parse_args(argv)

    settings = build_settings(args.env_file, probe=False)
    headers = {"X-API-Key": settings.local_ai_api_key} if settings.local_ai_api_key.strip() else {}
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True, text=True).stdout.strip() or "unknown"
    with httpx.Client(base_url=args.api, headers=headers, timeout=120.0) as client:
        manifest = record(
            args.dataset,
            client,
            task_ids=[t.strip() for t in args.tasks.split(",") if t.strip()] if args.tasks else None,
            max_context_chunks=int(settings.load_config().get("rag", {}).get("max_context_chunks", 5)),
            commit=commit,
        )
    misses = [task_id for task_id, item in manifest["tasks"].items() if item["answer_in_chunks"] is False]
    print(f"recorded {len(manifest['tasks'])} fixtures" + (f"; answer missing from the chunks of: {', '.join(misses)}" if misses else ""))
    return 1 if misses else 0


if __name__ == "__main__":
    raise SystemExit(main())
