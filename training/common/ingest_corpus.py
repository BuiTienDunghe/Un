"""Push a corpus directory through the product's own ingestion path.

Deliberately the product's path, not a shortcut into Qdrant: the number this
produces has to describe the system people actually use, including its chunker,
its Vietnamese segmentation and its embedding call. A corpus injected past all
that would measure something nobody runs.

Resumable and idempotent. Three thousand uploads take a while and a stall in the
middle should cost the stall, not the run: uploads dedupe on content hash, so a
second pass resolves to the existing documents and skips anything already
indexed.

    python -m training.common.ingest_corpus --corpus-dir <dir> --base-url http://127.0.0.1:8200
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from scripts.evaluate_rag import api_key_headers  # noqa: E402


def index_state(client: httpx.Client, base_url: str, document_id: str) -> tuple[str, int]:
    response = client.get(f"{base_url}/documents/{document_id}/status")
    response.raise_for_status()
    body = response.json()
    return str(body.get("status")), int(body.get("chunks_count") or 0)


def ingest_one(client: httpx.Client, base_url: str, path: Path, wait_seconds: int) -> tuple[str, str]:
    with path.open("rb") as handle:
        upload = client.post(f"{base_url}/documents/upload",
                             files={"file": (path.name, handle, "text/plain")})
    upload.raise_for_status()
    body = upload.json()
    if body.get("action_required") and body.get("conflict") == "same_name_same_hash":
        with path.open("rb") as handle:
            upload = client.post(f"{base_url}/documents/upload",
                                 files={"file": (path.name, handle, "text/plain")},
                                 data={"decision": "use_existing"})
        upload.raise_for_status()
        body = upload.json()
    if body.get("action_required"):
        return "conflict", str(body.get("conflict"))
    document_id = body["document_id"]

    status, chunks = index_state(client, base_url, document_id)
    if status == "indexed" and chunks > 0:
        return "already", document_id

    run = client.post(f"{base_url}/documents/index", json={"document_id": document_id})
    run.raise_for_status()
    run_id = run.json()["ingestion_run_id"]
    # Poll fast at first, then back off. A fixed 1-second sleep made this loop
    # the bottleneck rather than the system: 2 926 documents took 56.7 minutes
    # of wall clock, of which the server reported ~0 ms for every upload and
    # index call and the embedding of all 4 785 chunks accounts for about two
    # minutes. The other 54 were this function waiting on its own timer, and the
    # "0.87 documents/second" it produced described the sleep, not the product.
    waited = 0.0
    delay = 0.05
    while waited < wait_seconds:
        state = client.get(f"{base_url}/documents/ingestions/{run_id}")
        state.raise_for_status()
        current = state.json()["status"]
        if current == "completed":
            return "indexed", document_id
        if current in {"failed", "cancelled"}:
            return "failed", str(state.json().get("error_message") or current)
        time.sleep(delay)
        waited += delay
        delay = min(delay * 1.5, 2.0)
    return "timeout", document_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8200")
    parser.add_argument("--limit", type=int, default=0, help="Chi nap N tai lieu dau — de do toc do truoc.")
    parser.add_argument("--wait-seconds", type=int, default=180)
    parser.add_argument("--mapping-out", default=None, help="Ghi {ten file -> document_id} ra JSON.")
    arguments = parser.parse_args()

    files = sorted(p for p in Path(arguments.corpus_dir).iterdir() if p.is_file())
    if arguments.limit:
        files = files[: arguments.limit]
    print(f"{len(files)} tai lieu tu {arguments.corpus_dir}")

    counts: dict[str, int] = {}
    mapping: dict[str, str] = {}
    started = time.monotonic()
    with httpx.Client(timeout=300, headers=api_key_headers()) as client:
        for position, path in enumerate(files, start=1):
            try:
                outcome, detail = ingest_one(client, arguments.base_url, path, arguments.wait_seconds)
            except Exception as error:
                outcome, detail = "error", f"{type(error).__name__}: {error}"
            counts[outcome] = counts.get(outcome, 0) + 1
            if outcome in {"indexed", "already"}:
                mapping[path.name] = detail
            elif outcome != "conflict":
                print(f"  [{position}] {path.name}: {outcome} — {detail}", flush=True)
            if position % 25 == 0 or position == len(files):
                elapsed = time.monotonic() - started
                rate = position / elapsed if elapsed else 0
                remaining = (len(files) - position) / rate if rate else 0
                print(f"  {position}/{len(files)}  {rate:.2f} tai lieu/s  "
                      f"con ~{remaining/60:.1f} phut  {counts}", flush=True)

    elapsed = time.monotonic() - started
    print(f"\nxong trong {elapsed/60:.1f} phut · {len(files)/elapsed:.2f} tai lieu/s · {counts}")
    if arguments.mapping_out:
        Path(arguments.mapping_out).write_text(json.dumps(mapping, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"mapping -> {arguments.mapping_out} ({len(mapping)} tai lieu)")
    return 0 if not (counts.get("failed") or counts.get("error") or counts.get("timeout")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
