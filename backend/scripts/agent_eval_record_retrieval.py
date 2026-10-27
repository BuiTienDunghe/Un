"""Record real retrieval for the Agent Eval's document tasks, once (ticket 07, Q4 b).

Every retrieval fixture marked `"source": "pending"` is a question about a real
document of the lab corpus. This posts its reference `query` ONCE to the running
API's /rag/search, so what is recorded is exactly what the shipped retrieval
returns (embedding, hybrid ranking, reranker), and writes the sources back in the
fixture shape the runner replays: filename, page, content, score, plus the ids a
reader needs to find the chunk again. The runner then replays them for any query
the model asks, cut to the model's top_k.

    python -m training.common.eval_stack --profile lab --start     # repo root: the lab API, port 8100
    cd backend
    PYTHONUTF8=1 python -m scripts.agent_eval_record_retrieval --env-file C:\\Users\\dungbt06\\local-ai-core\\.env

Writes retrieval.jsonl (the fixtures) and retrieval_manifest.json (how they were
recorded) in the dataset directory. Nothing is written unless every request got
an HTTP answer: a half-recorded dataset is worse than a pending one. An answer
is not yet a usable fixture, though: when the agent could not see the task's
answer in the chunks, or none of them comes from the document the task cites,
the fixture STAYS pending and the runner refuses the task, so a retrieval miss
can never pass for an agent mistake. The manifest says which and what came back.

/rag/search clips to models.yaml rag.max_context_chunks (5), which no env var
overrides; the agent may ask for up to 8. The manifest records the clip.

v0.3 (ticket 20): every document a search returned is also fetched whole
(GET /documents/{id}/chunks, read-only) into documents.jsonl, which a read past
the preview replays; a document already there must come back identical or
nothing is written. A task marked `long_read` is the opposite case: its answer
must NOT be visible in any returned preview, and is classed L-a (inside a
returned chunk, past character 400) or L-b (only in a chunk next to a returned
one); anything else stays pending. Each recording keeps the previous manifests
under `earlier`.
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

from app.services.agent_service import _clip
from scripts.agent_eval import DATASET_DIR, PROJECT_ROOT, _read_jsonl
from scripts.agent_eval_grader import grade

# What /rag/search sends that the replay keeps: the four fields the agent reads,
# then provenance. `excerpt` is a display preview of `content` and is dropped.
KEPT_FIELDS = ("filename", "page", "content", "score", "document_id", "chunk_id", "chunk_index", "index_version", "heading_path")
AGENT_MAX_TOP_K = 8  # agent_service clamps search_documents.top_k to 1-8
AGENT_EXCERPT_CHARS = 400  # agent_service clips every chunk to this before the model reads it


def _write_lf(path: Path, text: str) -> None:
    # LF on disk like the rest of the dataset; load_dataset hashes LF bytes anyway.
    path.write_text(text, encoding="utf-8", newline="\n")


def answer_in_chunks(task: dict[str, Any], chunks: list[dict[str, Any]]) -> bool | None:
    """Can the agent see every point the task requires in the recorded chunks?
    A miss turns a document task into a retrieval test, which the agent eval
    does not measure, so the recorder reports it instead of hiding it.

    "See" is literal: the agent reads each chunk clipped to 400 characters
    (agent_service._dump), so the check reads exactly that. A task whose answer
    is computed or translated names its `evidence` instead of its answer."""
    patterns = task.get("evidence") or task.get("expect", {}).get("must_mention") or []
    if not patterns:
        return None
    visible = "\n".join(_clip(str(chunk.get("content") or ""), AGENT_EXCERPT_CHARS) for chunk in chunks)
    return grade({"must_mention": patterns}, [], visible, {})["passed"]


def _points(task: dict[str, Any]) -> list[str]:
    return task.get("evidence") or task.get("expect", {}).get("must_mention") or []


def _has(pattern: str, text: str) -> bool:
    return grade({"must_mention": [pattern]}, [], text, {})["passed"]


def reading_needed(task: dict[str, Any], chunks: list[dict[str, Any]], documents: dict[str, dict[str, Any]]) -> str | None:
    """A long-read task's class: "L-a" when every point is in a returned chunk
    but past its 400-character preview, "L-b" when some point is only in a chunk
    next to a returned one. None when a point shows in a preview (the agent could
    answer without reading) or is nowhere near what came back."""
    points = _points(task)
    if not points:
        return None
    previews = "\n".join(_clip(str(chunk.get("content") or ""), AGENT_EXCERPT_CHARS) for chunk in chunks)
    returned = "\n".join(str(chunk.get("content") or "") for chunk in chunks)
    neighbours = []
    for chunk in chunks:
        document = documents.get(str(chunk.get("document_id")))
        index = chunk.get("chunk_index")
        if document and isinstance(index, int):
            neighbours += [c["content"] for c in document["chunks"] if abs(c["chunk_index"] - index) == 1]
    near = returned + "\n" + "\n".join(neighbours)
    if any(_has(point, previews) for point in points) or not all(_has(point, near) for point in points):
        return None
    return "L-a" if all(_has(point, returned) for point in points) else "L-b"


def fetch_document(client: httpx.Client, document_id: str) -> dict[str, Any]:
    """The document's active version, whole, in the documents.jsonl shape."""
    items: list[dict[str, Any]] = []
    while True:
        response = client.get(f"/documents/{document_id}/chunks", params={"limit": 200, "offset": len(items)})
        response.raise_for_status()
        body = response.json()
        items += body["chunks"]
        if not body["chunks"] or len(items) >= body["total_chunks"]:
            break
    chunks = [
        {"chunk_index": item["chunk_index"], "page_start": item.get("page_start"), "page_end": item.get("page_end"), "content": item["content"]}
        for item in sorted(items, key=lambda item: item["chunk_index"])
    ]
    return {"document_id": document_id, "filename": body["filename"], "chunks": chunks}


def source_in_chunks(task: dict[str, Any], chunks: list[dict[str, Any]]) -> bool | None:
    """Did any chunk come from the document the task is about? An answer that is
    visible but came from another file would fail `must_cite` for reasons that
    are retrieval's, not the agent's. None when the task names no source."""
    source = (task.get("corpus_source") or {}).get("file")
    if not source:
        return None
    return any(str(chunk.get("filename") or "").casefold() == source.casefold() for chunk in chunks)


def record(
    dataset_dir: Path,
    client: httpx.Client,
    *,
    task_ids: list[str] | None = None,
    rerecord: bool = False,
    max_context_chunks: int | None = None,
    commit: str = "unknown",
    progress: Any = print,
) -> dict[str, Any]:
    """Record the chosen fixtures (default: every `pending` one) and return the manifest.

    Refused before any request: a hand-written fixture, ever (the traps must
    stay deterministic), and an already recorded one unless `rerecord` (its
    chunks are part of a citable dataset hash, so replacing them is a version
    bump someone has to mean)."""
    fixtures = _read_jsonl(dataset_dir / "retrieval.jsonl")
    tasks = {task["id"]: task for task in _read_jsonl(dataset_dir / "tasks.jsonl")}
    chosen = [f for f in fixtures if (f["task_id"] in task_ids if task_ids else f["source"] == "pending")]
    if task_ids:
        unknown = sorted(set(task_ids) - {f["task_id"] for f in chosen})
        if unknown:
            raise ValueError(f"không có fixture cho: {', '.join(unknown)}")
    handwritten = [f["task_id"] for f in chosen if f["source"] == "handwritten"]
    if handwritten:
        raise ValueError(f"không bao giờ ghi đè bài viết tay: {', '.join(handwritten)}")
    recorded_already = [f["task_id"] for f in chosen if f["source"] == "recorded"]
    if recorded_already and not rerecord:
        raise ValueError(f"đã ghi rồi: {', '.join(recorded_already)} (ghi lại cần --rerecord và nâng version)")
    if not chosen:
        raise ValueError("không có fixture nào cần ghi")

    models = client.get("/models")
    models.raise_for_status()
    served = models.json()
    documents_path = dataset_dir / "documents.jsonl"
    documents = {d["document_id"]: d for d in _read_jsonl(documents_path)} if documents_path.exists() else {}
    fetched: dict[str, dict[str, Any]] = {}
    recorded: dict[str, dict[str, Any]] = {}
    for fixture in chosen:
        response = client.post("/rag/search", json={"message": fixture["query"], "top_k": AGENT_MAX_TOP_K})
        response.raise_for_status()
        body = response.json()
        chunks = [{key: source.get(key) for key in KEPT_FIELDS} for source in body["sources"]]
        for chunk in chunks:
            document_id = str(chunk["document_id"])
            if document_id not in fetched:
                fetched[document_id] = fetch_document(client, document_id)
                known = documents.get(document_id)
                if known is not None and known != fetched[document_id]:
                    raise ValueError(f"{document_id} trên API khác documents.jsonl: dữ liệu đã ghi không còn khớp corpus, không ghi gì")
            own = fetched[document_id]["chunks"]
            if not (0 <= chunk["chunk_index"] < len(own) and own[chunk["chunk_index"]]["content"] == chunk["content"]):
                raise ValueError(f"{fixture['task_id']}: đoạn {document_id}#{chunk['chunk_index']} của /rag/search khác đoạn của tài liệu")
        task = tasks.get(fixture["task_id"], {})
        from_source = source_in_chunks(task, chunks)
        if task.get("long_read"):
            reading = reading_needed(task, chunks, {**documents, **fetched})
            found = None
            usable = reading is not None and from_source is not False
        else:
            reading = None
            found = answer_in_chunks(task, chunks)
            usable = found is not False and from_source is not False
        recorded[fixture["task_id"]] = {
            "chunks": chunks, "latency_ms": body.get("latency_ms"), "reading": reading,
            "answer_in_chunks": found, "source_in_chunks": from_source, "usable": usable,
        }
        progress(
            f"{fixture['task_id']:<8} {len(chunks)} chunks {body.get('latency_ms')}ms" + (f" {reading}" if reading else "")
            + ("" if usable else f"  KEPT PENDING (answer visible: {found}, long read: {reading}, cited file present: {from_source})")
        )

    # Every request answered: only now does anything reach disk, and only the
    # fixtures the agent can actually be graded on leave `pending`.
    for fixture in fixtures:
        item = recorded.get(fixture["task_id"])
        if item and item["usable"]:
            fixture["source"] = "recorded"
            fixture["chunks"] = item["chunks"]
    _write_lf(dataset_dir / "retrieval.jsonl", "".join(json.dumps(f, ensure_ascii=False) + "\n" for f in fixtures))
    documents.update(fetched)
    _write_lf(documents_path, "".join(json.dumps(d, ensure_ascii=False) + "\n" for d in documents.values()))
    manifest_path = dataset_dir / "retrieval_manifest.json"
    previous = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
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
            task_id: {
                "status": "recorded" if item["usable"] else "kept pending",
                "chunks": len(item["chunks"]),
                "latency_ms": item["latency_ms"],
                "answer_in_chunks": item["answer_in_chunks"],
                **({"reading": item["reading"]} if tasks.get(task_id, {}).get("long_read") else {}),
                "source_in_chunks": item["source_in_chunks"],
                # For a fixture left pending, what did come back: enough to fix the query.
                **({} if item["usable"] else {"retrieved": [
                    {"filename": c.get("filename"), "chunk_index": c.get("chunk_index"), "score": c.get("score")} for c in item["chunks"]
                ]}),
            }
            for task_id, item in recorded.items()
        },
        # Earlier recordings, newest first: the fixtures they wrote are still in use.
        "earlier": ([{k: v for k, v in previous.items() if k != "earlier"}] + previous.get("earlier", [])) if previous else [],
    }
    _write_lf(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def main(argv: list[str] | None = None) -> int:
    from scripts.agent_eval import build_settings

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=DATASET_DIR)
    parser.add_argument("--api", default="http://127.0.0.1:8100", help="the lab API (training.common.eval_stack --profile lab)")
    parser.add_argument("--tasks", help="comma-separated task ids to record (default: every pending fixture)")
    parser.add_argument("--rerecord", action="store_true", help="allow replacing already recorded fixtures (then bump the dataset version)")
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
            rerecord=args.rerecord,
            max_context_chunks=int(settings.load_config().get("rag", {}).get("max_context_chunks", 5)),
            commit=commit,
        )
    pending = [task_id for task_id, item in manifest["tasks"].items() if item["status"] != "recorded"]
    print(
        f"recorded {len(manifest['tasks']) - len(pending)} of {len(manifest['tasks'])} fixtures"
        + (f"; kept pending (fix the query or the task, see retrieval_manifest.json): {', '.join(pending)}" if pending else "")
    )
    return 1 if pending else 0


if __name__ == "__main__":
    raise SystemExit(main())
