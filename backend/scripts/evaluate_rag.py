"""Bootstrap an evaluation document, run RAG cases, and write reproducible baseline metrics."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from time import sleep

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def bootstrap_document(client: httpx.Client, base_url: str, file_path: Path) -> str:
    with file_path.open("rb") as handle:
        upload = client.post(f"{base_url}/documents/upload", files={"file": (file_path.name, handle, "text/plain")})
    upload.raise_for_status()
    document_id = upload.json()["document_id"]
    index = client.post(f"{base_url}/documents/index", json={"document_id": document_id})
    index.raise_for_status()
    run_id = index.json()["ingestion_run_id"]
    for _ in range(180):
        status = client.get(f"{base_url}/documents/ingestions/{run_id}")
        status.raise_for_status()
        state = status.json()["status"]
        if state == "completed":
            return document_id
        if state in {"failed", "cancelled"}:
            raise RuntimeError(status.json().get("error_message") or "Document indexing failed")
        sleep(1)
    raise TimeoutError("Document did not finish indexing within 180 seconds")


def contains_all(text: str, terms: list[str]) -> bool:
    normalized = text.lower()
    return all(term.lower() in normalized for term in terms)


def reciprocal_rank(sources: list[dict[str, object]], expected_terms: list[str]) -> float:
    for rank, source in enumerate(sources, start=1):
        # Match against the full chunk text; the 300-char excerpt is a display
        # preview and misses most of a 480-token chunk.
        if contains_all(str(source.get("content") or source.get("excerpt", "")), expected_terms):
            return 1 / rank
    return 0.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(PROJECT_ROOT / "data" / "evaluation" / "rag_eval.jsonl"))
    parser.add_argument("--fixture", default=str(PROJECT_ROOT / "data" / "evaluation" / "fixtures" / "local_ai_core_baseline.txt"))
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "data" / "evaluation" / "results"))
    parser.add_argument("--document-id", help="Skip bootstrap and use this already-indexed document ID.")
    args = parser.parse_args()

    cases = [json.loads(line) for line in Path(args.dataset).read_text(encoding="utf-8").splitlines() if line.strip()]
    with httpx.Client(timeout=180) as client:
        document_id = args.document_id or bootstrap_document(client, args.base_url, Path(args.fixture))
        results: list[dict[str, object]] = []
        for case in cases:
            selected_document_id = document_id if case.get("document_id") == "__BOOTSTRAP__" else case.get("document_id")
            response = client.post(f"{args.base_url}/rag/chat", json={"message": case["question"], "document_id": selected_document_id})
            payload = response.json()
            sources = payload.get("sources", [])
            answer_ok = response.is_success and contains_all(str(payload.get("answer", "")), case.get("expected_answer_terms", []))
            rr = reciprocal_rank(sources, case.get("expected_source_terms", []))
            results.append({"id": case["id"], "status": response.status_code, "answer_pass": answer_ok, "source_recall": rr > 0, "reciprocal_rank": rr, "latency_ms": payload.get("latency_ms"), "sources": sources})

    count = len(results)
    summary = {
        "created_at": datetime.now(UTC).isoformat(),
        "document_id": document_id,
        "cases": count,
        "answer_pass_rate": sum(item["answer_pass"] for item in results) / count if count else 0,
        "source_recall_at_k": sum(item["source_recall"] for item in results) / count if count else 0,
        "mrr": sum(float(item["reciprocal_rank"]) for item in results) / count if count else 0,
        "average_latency_ms": sum(int(item["latency_ms"] or 0) for item in results) / count if count else 0,
        "results": results,
    }
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"rag-baseline-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Saved report: {output_path}")
    return 0 if summary["source_recall_at_k"] == 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
