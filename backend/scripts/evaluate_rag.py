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


def ensure_indexed(client: httpx.Client, base_url: str, document_id: str) -> None:
    """Index a just-uploaded document, or verify an already-known one is live."""
    status = client.get(f"{base_url}/documents/{document_id}/status")
    status.raise_for_status()
    body = status.json()
    if body["status"] == "indexed" and body.get("chunks_count", 0) > 0:
        return
    index = client.post(f"{base_url}/documents/index", json={"document_id": document_id})
    index.raise_for_status()
    run_id = index.json()["ingestion_run_id"]
    for _ in range(180):
        run = client.get(f"{base_url}/documents/ingestions/{run_id}")
        run.raise_for_status()
        state = run.json()["status"]
        if state == "completed":
            return
        if state in {"failed", "cancelled"}:
            raise RuntimeError(run.json().get("error_message") or f"Indexing failed for {document_id}")
        sleep(1)
    raise TimeoutError(f"Document {document_id} did not finish indexing within 180 seconds")


def bootstrap_corpus(client: httpx.Client, base_url: str, corpus_dir: Path) -> dict[str, str]:
    """Upload and index every fixture in the corpus directory, idempotently.

    Re-running against the same server must not error or duplicate: uploads
    dedupe on content hash, so a second run resolves to the existing documents.
    Returns {fixture filename -> document_id} for expected_docs scoring.
    """
    mapping: dict[str, str] = {}
    for file_path in sorted(p for p in corpus_dir.iterdir() if p.is_file()):
        with file_path.open("rb") as handle:
            upload = client.post(f"{base_url}/documents/upload", files={"file": (file_path.name, handle, "text/plain")})
        upload.raise_for_status()
        body = upload.json()
        if body.get("action_required") and body.get("conflict") == "same_name_same_hash":
            # A previous bootstrap already owns this exact fixture; confirming
            # use_existing resolves to that document, keeping reruns idempotent.
            with file_path.open("rb") as handle:
                upload = client.post(f"{base_url}/documents/upload", files={"file": (file_path.name, handle, "text/plain")}, data={"decision": "use_existing"})
            upload.raise_for_status()
            body = upload.json()
        if body.get("action_required"):
            # Same filename, different bytes: the fixture changed after a
            # previous bootstrap. Refuse rather than silently measuring a mixed
            # corpus — the operator deletes the stale eval documents first.
            raise RuntimeError(f"Fixture {file_path.name} conflicts with an existing document ({body.get('conflict')}); remove the old eval corpus documents and rerun")
        document_id = body["document_id"]
        ensure_indexed(client, base_url, document_id)
        mapping[file_path.name] = document_id
    return mapping


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


def score_multidoc_sources(sources: list[dict[str, object]], expected_ids: set[str], expected_terms: list[str]) -> tuple[float, bool]:
    """(reciprocal rank of the first hit, top-1 document correctness).

    A hit is a source from an expected document whose full chunk text contains
    every expected term — the same contains_all contract as the single-doc
    modes, tightened by document identity because the whole corpus competes.
    """
    doc_hit = bool(sources) and str(sources[0].get("document_id")) in expected_ids
    for rank, source in enumerate(sources, start=1):
        if str(source.get("document_id")) in expected_ids and contains_all(str(source.get("content") or source.get("excerpt", "")), expected_terms):
            return 1 / rank, doc_hit
    return 0.0, doc_hit


def run_multidoc_mode(client: httpx.Client, base_url: str, cases: list[dict], mapping: dict[str, str], retrieval_only: bool, output_dir: Path, baseline_path: Path | None, tolerance: float, write_baseline: Path | None) -> int:
    models = client.get(f"{base_url}/models")
    embedding_model = models.json().get("models", {}).get("embedding", {}).get("name") if models.is_success else None

    results: list[dict[str, object]] = []
    for case in cases:
        unknown = [name for name in case["expected_docs"] if name not in mapping]
        if unknown:
            raise RuntimeError(f"Case {case['id']} names fixtures missing from the corpus dir: {unknown}")
        expected_ids = {mapping[name] for name in case["expected_docs"]}
        terms = case.get("expected_source_terms", [])
        # No document filter, deliberately: choosing the right document among
        # the whole corpus is the capability this eval measures.
        if retrieval_only:
            response = client.post(f"{base_url}/rag/search", json={"message": case["question"]})
            payload = response.json() if response.is_success else {}
            answer_pass = None
        else:
            response = client.post(f"{base_url}/rag/chat", json={"message": case["question"]})
            payload = response.json() if response.is_success else {}
            if payload.get("conversation_id"):
                client.delete(f"{base_url}/conversations/{payload['conversation_id']}")
            answer_pass = response.is_success and contains_all(str(payload.get("answer", "")), case.get("expected_answer_terms", []))
        rr, doc_hit = score_multidoc_sources(payload.get("sources", []), expected_ids, terms) if response.is_success else (0.0, False)
        # D3a: the server's no-model self-check rides on the full-mode answer;
        # retrieval-only runs have no answer to grade, so nothing is recorded.
        grounding = (payload.get("grounding") or {}) if not retrieval_only else {}
        results.append({"id": case["id"], "group": case.get("group", "single"), "status": response.status_code, "source_recall": rr > 0, "reciprocal_rank": rr, "doc_hit": doc_hit, "answer_pass": answer_pass, "grounding_label": grounding.get("label"), "grounded_ratio": grounding.get("grounded_ratio"), "language_mismatch": grounding.get("language_mismatch"), "ungrounded_sentences": [item.get("text") for item in grounding.get("sentences", []) if item.get("label") == "ungrounded"], "latency_ms": payload.get("latency_ms")})

    count = len(results)

    def rate(items: list[dict[str, object]], key: str) -> float:
        return sum(bool(item[key]) for item in items) / len(items) if items else 0.0

    def mean_rr(items: list[dict[str, object]]) -> float:
        return sum(float(item["reciprocal_rank"]) for item in items) / len(items) if items else 0.0

    groups = sorted({str(item["group"]) for item in results})
    answered = [item for item in results if item["answer_pass"] is not None]
    # Grounding (D3a, full mode only): share of answers whose self-check came
    # back "grounded", plus the label distribution so a drift toward "weak"
    # is visible even while the headline rate holds.
    graded = [item for item in results if item.get("grounding_label")]
    grounding_summary = None
    if graded:
        labels = sorted({str(item["grounding_label"]) for item in graded})
        grounding_summary = {
            "graded": len(graded),
            "grounding_rate": sum(1 for item in graded if item["grounding_label"] == "grounded") / len(graded),
            "ungrounded_rate": sum(1 for item in graded if item["grounding_label"] == "ungrounded") / len(graded),
            "language_mismatch": sum(1 for item in graded if item.get("language_mismatch")),
            "labels": {label: sum(1 for item in graded if item["grounding_label"] == label) for label in labels},
        }
    summary = {
        "created_at": datetime.now(UTC).isoformat(),
        "mode": "multidoc-retrieval" if retrieval_only else "multidoc-full",
        "embedding_model": embedding_model,
        "corpus": sorted(mapping),
        "cases": count,
        "recall_at_k": rate(results, "source_recall"),
        "mrr": mean_rr(results),
        "doc_hit_rate": rate(results, "doc_hit"),
        "answer_pass_rate": rate(answered, "answer_pass") if answered else None,
        "grounding": grounding_summary,
        "by_group": {group: {"cases": len(items), "recall_at_k": rate(items, "source_recall"), "mrr": mean_rr(items), "doc_hit_rate": rate(items, "doc_hit")} for group in groups for items in [[item for item in results if item["group"] == group]]},
        "results": results,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"rag-multidoc-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "results"}, ensure_ascii=False, indent=2))
    misses = [item["id"] for item in results if not item["source_recall"]]
    if misses:
        print(f"Missed cases: {', '.join(misses)}")
    ungrounded = [item["id"] for item in results if item.get("grounding_label") == "ungrounded"]
    if ungrounded:
        print(f"Ungrounded answers (D3a): {', '.join(ungrounded)}")
    print(f"Saved report: {output_path}")

    if write_baseline:
        baseline = {"created_at": summary["created_at"], "embedding_model": embedding_model, "cases": count, "recall_at_k": summary["recall_at_k"], "mrr": summary["mrr"], "doc_hit_rate": summary["doc_hit_rate"]}
        write_baseline.write_text(json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Recorded baseline: {write_baseline}")

    # Regression gate (D1): fail only against a recorded baseline, with the
    # plan's tolerance ("không tụt quá 2 điểm"). No baseline yet = report-only,
    # so the gate can land in CI before the machine that records the numbers.
    if baseline_path is not None:
        if not baseline_path.exists():
            print(f"No baseline recorded at {baseline_path}; reporting without gating.")
            return 0
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        if baseline.get("embedding_model") not in {None, embedding_model}:
            print(f"Baseline embedding model {baseline.get('embedding_model')} != current {embedding_model}; re-record the baseline on the final configuration.")
            return 1
        failed = [
            f"{metric} {summary[metric]:.3f} < baseline {baseline[metric]:.3f} - {tolerance}"
            for metric in ("recall_at_k", "mrr")
            if metric in baseline and float(summary[metric]) < float(baseline[metric]) - tolerance
        ]
        if failed:
            print("Retrieval regression gate FAILED: " + "; ".join(failed))
            return 1
        print("Retrieval regression gate passed.")
    return 0


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
    parser.add_argument("--multidoc-dataset", help="Run the whole-corpus dataset (D1): no document filter, scored by document identity + verbatim terms.")
    parser.add_argument("--corpus-dir", default=str(PROJECT_ROOT / "data" / "evaluation" / "fixtures" / "multidoc"), help="Fixture directory bootstrapped for --multidoc-dataset.")
    parser.add_argument("--retrieval-only", action="store_true", help="Multidoc mode: score /rag/search sources only — no answer model needed (CI gate).")
    parser.add_argument("--baseline", help="Multidoc mode: baseline JSON to gate against (missing file = report-only).")
    parser.add_argument("--tolerance", type=float, default=0.02, help="Allowed drop below the baseline before the gate fails.")
    parser.add_argument("--write-baseline", help="Multidoc mode: record this run's metrics as the new baseline JSON.")
    parser.add_argument("--fixture", default=str(PROJECT_ROOT / "data" / "evaluation" / "fixtures" / "local_ai_core_baseline.txt"))
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output-dir", default=str(PROJECT_ROOT / "data" / "evaluation" / "results"))
    parser.add_argument("--document-id", help="Skip bootstrap and use this already-indexed document ID.")
    args = parser.parse_args()

    if args.multidoc_dataset:
        cases = [json.loads(line) for line in Path(args.multidoc_dataset).read_text(encoding="utf-8").splitlines() if line.strip()]
        api_key = os.environ.get("LOCAL_AI_API_KEY", "").strip()
        headers = {"X-API-Key": api_key} if api_key else {}
        with httpx.Client(timeout=600, headers=headers) as client:
            mapping = bootstrap_corpus(client, args.base_url, Path(args.corpus_dir))
            return run_multidoc_mode(client, args.base_url, cases, mapping, args.retrieval_only, Path(args.output_dir), Path(args.baseline) if args.baseline else None, args.tolerance, Path(args.write_baseline) if args.write_baseline else None)

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
