"""Bootstrap an evaluation document, run RAG cases, and write reproducible baseline metrics."""

from __future__ import annotations

import argparse
import json
import os
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


def run_conversation_case(client: httpx.Client, base_url: str, case: dict, document_id: str) -> dict[str, object]:
    """One follow-up pair, measured twice.

    The baseline posts turn2 WITHOUT a conversation: a fresh conversation has
    no history, so the condense step structurally skips and retrieval sees the
    raw follow-up. The real run posts turn1 then turn2 in one conversation.
    The delta between the two is what proves the condense step itself works,
    rather than BM25 getting lucky on leftover keywords in turn2.
    """
    selected = document_id if case.get("document_id") == "__BOOTSTRAP__" else case.get("document_id")
    expected = case.get("expected_source_terms", [])

    baseline = client.post(f"{base_url}/rag/chat", json={"message": case["turn2"], "document_id": selected})
    baseline_payload = baseline.json() if baseline.status_code != 204 else {}
    if baseline_payload.get("conversation_id"):
        client.delete(f"{base_url}/conversations/{baseline_payload['conversation_id']}")
    baseline_rr = reciprocal_rank(baseline_payload.get("sources", []), expected) if baseline.is_success else 0.0

    first = client.post(f"{base_url}/rag/chat", json={"message": case["turn1"], "document_id": selected})
    conversation_id = first.json().get("conversation_id") if first.is_success else None
    follow = client.post(
        f"{base_url}/rag/chat",
        json={"message": case["turn2"], "document_id": selected, "conversation_id": conversation_id},
    )
    payload = follow.json() if follow.status_code != 204 else {}
    if conversation_id:
        client.delete(f"{base_url}/conversations/{conversation_id}")
    rr = reciprocal_rank(payload.get("sources", []), expected) if follow.is_success else 0.0
    return {
        "id": case["id"],
        "status": follow.status_code,
        "recall": rr > 0,
        "reciprocal_rank": rr,
        "baseline_recall": baseline_rr > 0,
        "baseline_reciprocal_rank": baseline_rr,
        "retrieval_question": payload.get("retrieval_question"),
        "latency_ms": payload.get("latency_ms"),
    }


def run_conversation_mode(client: httpx.Client, base_url: str, cases: list[dict], document_id: str, output_dir: Path) -> int:
    results = [run_conversation_case(client, base_url, case, document_id) for case in cases]
    count = len(results)
    recall = sum(item["recall"] for item in results) / count if count else 0
    baseline_recall = sum(item["baseline_recall"] for item in results) / count if count else 0
    mrr = sum(float(item["reciprocal_rank"]) for item in results) / count if count else 0
    baseline_mrr = sum(float(item["baseline_reciprocal_rank"]) for item in results) / count if count else 0
    summary = {
        "created_at": datetime.now(UTC).isoformat(),
        "mode": "conversation",
        "document_id": document_id,
        "cases": count,
        "recall_at_k": recall,
        "baseline_recall_at_k": baseline_recall,
        "condense_gain": recall - baseline_recall,
        "mrr": mrr,
        "baseline_mrr": baseline_mrr,
        "results": results,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"rag-conversation-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Saved report: {output_path}")
    # Acceptance (P1-2): >=80% follow-up recall, and the condense step must
    # beat asking the raw follow-up standalone. On a small corpus recall@k
    # saturates (top-5 covers a third of the chunks), so ranking (MRR) is the
    # discriminating half of the comparison.
    return 0 if recall >= 0.8 and (recall > baseline_recall or mrr > baseline_mrr) else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(PROJECT_ROOT / "data" / "evaluation" / "rag_eval.jsonl"))
    parser.add_argument("--conversation-dataset", help="Run follow-up pairs (turn1/turn2) instead of single questions.")
    parser.add_argument("--fixture", default=str(PROJECT_ROOT / "data" / "evaluation" / "fixtures" / "local_ai_core_baseline.txt"))
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "data" / "evaluation" / "results"))
    parser.add_argument("--document-id", help="Skip bootstrap and use this already-indexed document ID.")
    args = parser.parse_args()

    if args.conversation_dataset:
        pairs = [json.loads(line) for line in Path(args.conversation_dataset).read_text(encoding="utf-8").splitlines() if line.strip()]
        api_key = os.environ.get("LOCAL_AI_API_KEY", "").strip()
        headers = {"X-API-Key": api_key} if api_key else {}
        with httpx.Client(timeout=600, headers=headers) as client:
            document_id = args.document_id or bootstrap_document(client, args.base_url, Path(args.fixture))
            return run_conversation_mode(client, args.base_url, pairs, document_id, Path(args.output_dir))

    cases = [json.loads(line) for line in Path(args.dataset).read_text(encoding="utf-8").splitlines() if line.strip()]
    # The harness drives write endpoints, so it needs the key whenever the
    # backend has one configured.
    api_key = os.environ.get("LOCAL_AI_API_KEY", "").strip()
    headers = {"X-API-Key": api_key} if api_key else {}
    with httpx.Client(timeout=180, headers=headers) as client:
        document_id = args.document_id or bootstrap_document(client, args.base_url, Path(args.fixture))
        results: list[dict[str, object]] = []
        for case in cases:
            selected_document_id = document_id if case.get("document_id") == "__BOOTSTRAP__" else case.get("document_id")
            response = client.post(f"{args.base_url}/rag/chat", json={"message": case["question"], "document_id": selected_document_id})
            payload = response.json()
            # Each eval question persists a conversation now; clean it up so
            # benchmark runs do not pollute the user's conversation list.
            if payload.get("conversation_id"):
                client.delete(f"{args.base_url}/conversations/{payload['conversation_id']}")
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
