"""Score retrieval on a public held-out set, the way the published numbers are scored.

The in-repo harness asks a different question. It scores a chunk as a hit when it
comes from the expected document *and* contains every expected verbatim phrase —
a strict contract that works because the questions were written by hand against
the chunk text. A public set does not come with verbatim phrases; it comes with
judgements saying which document answers which query. So relevance here is
document identity, and the metrics are the ones the retrieval literature reports:
nDCG@10, recall@k, MRR.

Kept out of `scripts/evaluate_rag.py` on purpose. That harness gates CI, and a
second scoring contract bolted into it is a way to break the gate while adding a
feature.

    python -m training.common.eval_heldout \\
        --dataset data/evaluation/heldout_retrieval_v1/zalo-legal_subset.jsonl \\
        --base-url http://127.0.0.1:8200 --label bare
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from scripts.evaluate_rag import api_key_headers  # noqa: E402

OUT_DIR = PROJECT_ROOT / "data" / "evaluation" / "heldout_retrieval_v1" / "results"


def ranked_documents(sources: list[dict]) -> list[str]:
    """Chunk ranking collapsed to a document ranking, first appearance wins.

    Several chunks of one document may be returned; a document's rank is where it
    first appears, which is what a reader scrolling the citation list experiences.
    """
    seen: list[str] = []
    for source in sources:
        name = str(source.get("filename") or "")
        if name and name not in seen:
            seen.append(name)
    return seen


def ndcg_at(ranking: list[str], relevant: set[str], k: int) -> float:
    gain = sum(1.0 / math.log2(rank + 1) for rank, name in enumerate(ranking[:k], start=1) if name in relevant)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(len(relevant), k) + 1))
    return gain / ideal if ideal else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8200")
    parser.add_argument("--top-k", type=int, default=20, help="Chunks requested per query; the API caps this at 20.")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--label", default="", help="Free tag for the report filename, e.g. bare / reranker-on.")
    arguments = parser.parse_args()

    cases = [json.loads(line) for line in Path(arguments.dataset).read_text(encoding="utf-8").splitlines() if line.strip()]
    if arguments.limit:
        cases = cases[: arguments.limit]
    print(f"{len(cases)} cau hoi · {arguments.base_url} · top_k={arguments.top_k}")

    results: list[dict] = []
    latencies: list[int] = []
    started = time.monotonic()
    with httpx.Client(timeout=120, headers=api_key_headers()) as client:
        # Model registry (invariant #4): a report names the version ids that produced
        # it, read from the server, and is never written for a fallback — checked
        # BEFORE the queries, because three thousand of them against the wrong
        # version would be GPU time spent on a number nothing may cite.
        served = client.get(f"{arguments.base_url}/models")
        served.raise_for_status()
        payload = served.json()
        registry = payload.get("registry") if isinstance(payload.get("registry"), dict) else {}
        deviating = sorted(role for role, row in registry.items() if row.get("fallback"))
        if deviating:
            print(f"TU CHOI ghi bao cao: {', '.join(deviating)} khong chay dung phien ban trong registry "
                  f"(fallback) - xem {arguments.base_url}/models. Sua roi khoi dong lai API va chay lai.")
            return 1
        versions = {role: (registry.get(role) or {}).get("loaded") for role in ("general", "embedding", "reranker")}
        rag = payload.get("rag") if isinstance(payload.get("rag"), dict) else {}
        for position, case in enumerate(cases, start=1):
            relevant = set(case["expected_docs"])
            response = client.post(f"{arguments.base_url}/rag/search",
                                   json={"message": case["question"], "top_k": arguments.top_k})
            if not response.is_success:
                results.append({"id": case["id"], "status": response.status_code, "rank": None,
                                "reciprocal_rank": 0.0, "ndcg_at_10": 0.0, "hit_at_5": False, "hit_at_10": False})
                continue
            payload = response.json()
            ranking = ranked_documents(payload.get("sources", []))
            rank = next((i for i, name in enumerate(ranking, start=1) if name in relevant), None)
            if payload.get("latency_ms") is not None:
                latencies.append(int(payload["latency_ms"]))
            results.append({
                "id": case["id"],
                "status": response.status_code,
                "documents_returned": len(ranking),
                "rank": rank,
                "reciprocal_rank": (1.0 / rank) if rank else 0.0,
                "ndcg_at_10": ndcg_at(ranking, relevant, 10),
                "hit_at_5": bool(rank and rank <= 5),
                "hit_at_10": bool(rank and rank <= 10),
                "latency_ms": payload.get("latency_ms"),
            })
            if position % 100 == 0 or position == len(cases):
                elapsed = time.monotonic() - started
                print(f"  {position}/{len(cases)}  {position/elapsed:.1f} cau/s", flush=True)

    count = len(results)
    # The depth the API can actually reach, which is not the depth requested.
    # /rag/search clips to rag.max_context_chunks so that it returns exactly what
    # /rag/chat would cite — deliberate product behaviour, and it means a metric
    # named @10 would be @5 wearing a false label. Published Zalo Legal tables
    # report Acc@1/@3/@5/@10; only the first three are comparable with this.
    depth = max((r.get("documents_returned", 0) for r in results), default=0)
    summary = {
        "created_at": datetime.now(UTC).isoformat(),
        "dataset": arguments.dataset,
        "base_url": arguments.base_url,
        "label": arguments.label,
        "versions": versions,
        "rag": rag,
        "top_k_requested": arguments.top_k,
        "retrieval_depth_reached": depth,
        "depth_note": (
            f"/rag/search returned at most {depth} distinct documents per query regardless of top_k, "
            "because it clips to rag.max_context_chunks to match what /rag/chat cites. Metrics deeper "
            "than that are not measurable here and are reported as null."
        ),
        "queries": count,
        "accuracy_at_1": sum(1 for r in results if r.get("rank") == 1) / count if count else 0.0,
        "accuracy_at_3": sum(1 for r in results if r.get("rank") and r["rank"] <= 3) / count if count else 0.0,
        "recall_at_5": sum(r["hit_at_5"] for r in results) / count if count else 0.0,
        "recall_at_10": (sum(r["hit_at_10"] for r in results) / count) if (count and depth >= 10) else None,
        "mrr": sum(float(r["reciprocal_rank"]) for r in results) / count if count else 0.0,
        "ndcg_at_10": (sum(float(r["ndcg_at_10"]) for r in results) / count) if (count and depth >= 10) else None,
        f"ndcg_at_{depth or 5}": sum(float(r["ndcg_at_10"]) for r in results) / count if count else 0.0,
        "documents_returned_median": statistics.median([r.get("documents_returned", 0) for r in results]) if count else 0,
        "latency_ms": {
            "measured": len(latencies),
            "p50": statistics.median(latencies) if latencies else None,
            "p95": sorted(latencies)[int(0.95 * len(latencies))] if latencies else None,
        },
        "results": results,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = f"-{arguments.label}" if arguments.label else ""
    path = OUT_DIR / f"heldout{tag}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nAcc@1 {summary['accuracy_at_1']:.4f} · Acc@3 {summary['accuracy_at_3']:.4f} · "
          f"recall@5 {summary['recall_at_5']:.4f} · MRR {summary['mrr']:.4f} · "
          f"nDCG@{depth or 5} {summary[f'ndcg_at_{depth or 5}']:.4f}")
    if depth < 10:
        print(f"CANH BAO: chi do duoc toi hang {depth}; moi chi so @10 tra ve null. {summary['depth_note']}")
    print(f"do tre p50 {summary['latency_ms']['p50']} ms · p95 {summary['latency_ms']['p95']} ms")
    print(f"bao cao -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
