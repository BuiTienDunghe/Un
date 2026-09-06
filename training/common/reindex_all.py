"""Force every active document in an eval database to be chunked and embedded again.

A chunking change only takes effect on re-index: existing chunks were written by
the old rule and stay exactly as they were, so an eval run after the change would
still measure the old boundaries and report no difference.

Never point this at production. It rewrites the chunks and vectors of everything
it finds, and with contextual retrieval on it spends one generation call per
chunk while doing it.

    python -m training.common.reindex_all --base-url http://127.0.0.1:8100
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from scripts.evaluate_rag import api_key_headers  # noqa: E402

SAFE_PORTS = {8100, 8200, 8300}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8100")
    parser.add_argument("--wait-seconds", type=int, default=900)
    parser.add_argument("--i-know-this-is-not-production", action="store_true",
                        help="Required to target a port other than 8100/8200.")
    arguments = parser.parse_args()

    port = int(arguments.base_url.rsplit(":", 1)[-1].split("/")[0])
    if port not in SAFE_PORTS and not arguments.i_know_this_is_not_production:
        print(f"Cong {port} khong nam trong {sorted(SAFE_PORTS)} (cac stack eval). "
              f"Neu that su co y, them --i-know-this-is-not-production.")
        return 2

    with httpx.Client(timeout=900, headers=api_key_headers()) as client:
        body = client.get(f"{arguments.base_url}/documents").json()
        items = body if isinstance(body, list) else body.get("documents", [])
        active = [d for d in items if str(d.get("status")) not in {"deleted", "deleting"}]
        print(f"{len(active)} tai lieu active se duoc index lai tren {arguments.base_url}")

        started = time.monotonic()
        before = sum(int(d.get("chunks_count") or 0) for d in active)
        failures = 0
        for document in active:
            document_id = document["document_id"]
            run = client.post(f"{arguments.base_url}/documents/index", json={"document_id": document_id})
            run.raise_for_status()
            run_id = run.json()["ingestion_run_id"]
            # Poll fast at first, then back off — the same fix as ingest_corpus.py.
            # A fixed one-second sleep put a floor of a second under every document,
            # which on 2 945 documents is 49 minutes spent waiting on a timer while
            # the server reports each index call finishing in well under that.
            state = "unknown"
            waited, delay = 0.0, 0.05
            while waited < arguments.wait_seconds:
                response = client.get(f"{arguments.base_url}/documents/ingestions/{run_id}")
                response.raise_for_status()
                state = response.json()["status"]
                if state == "completed":
                    break
                if state in {"failed", "cancelled"}:
                    failures += 1
                    print(f"  LOI {document.get('filename')}: {response.json().get('error_message') or state}")
                    break
                time.sleep(delay)
                waited += delay
                delay = min(delay * 1.5, 2.0)
            else:
                failures += 1
                state = "timeout"
            print(f"  {str(document.get('filename'))[:38]:40} {state:10} ({time.monotonic()-started:5.0f}s)", flush=True)

        body = client.get(f"{arguments.base_url}/documents").json()
        items = body if isinstance(body, list) else body.get("documents", [])
        after = sum(int(d.get("chunks_count") or 0) for d in items
                    if str(d.get("status")) not in {"deleted", "deleting"})

    print(f"\nxong sau {time.monotonic()-started:.0f}s · chunk {before} -> {after} · loi {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
