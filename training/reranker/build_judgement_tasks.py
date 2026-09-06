"""Prepare the chunk-level labelling tasks that the document-level qrels cannot answer.

Zalo's labels say "this legal article answers this question". The reranker scores
*chunks*, so for any article the chunker splits, something has to decide which
piece carries the answer. There is no automatic source of that truth: the
released labels simply do not contain it.

Measured on the 2 168 training questions:

  1 354 questions (62.5%)  every positive article is a single chunk — the label
                           transfers with no inference at all
    814 questions (37.5%)  at least one positive article splits, giving 820
                           (question, article) pairs and 5 385 chunks to read

The split is heavily skewed. Most articles produce three to seven chunks, but
the Penal Code comes out as 371, and finding one answer inside it by reading is
neither reliable nor worth the time. Those go to a separate bucket and are
excluded rather than guessed at, because a low-confidence label is worse than no
label — it teaches the model something false with full confidence.

    python -m training.reranker.build_judgement_tasks
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.utils.chunking import chunk_pages  # noqa: E402

RAW = PROJECT_ROOT / "data" / "heldout_raw" / "zalo-legal"
OUT = PROJECT_ROOT / "data" / "evaluation" / "reranker_v1"
CHUNK_TOKENS, CHUNK_OVERLAP = 480, 80


def document_chunks(doc: dict) -> list[str]:
    title = (doc.get("title") or "").strip()
    text = (doc.get("text") or "").strip()
    body = f"# {title}\n\n{text}\n" if title else text + "\n"
    return [c.content for c in chunk_pages([(None, body, "text")], CHUNK_TOKENS, CHUNK_OVERLAP)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-chunks", type=int, default=30,
                        help="Articles above this go to the oversized bucket instead of being judged.")
    parser.add_argument("--batch-chunks", type=int, default=140,
                        help="Roughly how many chunks one judgement batch should carry.")
    arguments = parser.parse_args()

    questions = [json.loads(l) for l in (OUT / "zalo_legal_train.jsonl").read_text(encoding="utf-8").splitlines()]
    wanted = {d for q in questions for d in q["positive_ids"]}
    docs: dict[str, dict] = {}
    with (RAW / "corpus.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row["_id"] in wanted:
                docs[row["_id"]] = row

    chunked = {doc_id: document_chunks(doc) for doc_id, doc in docs.items()}

    clean, tasks, oversized = [], [], []
    for question in questions:
        singles = [d for d in question["positive_ids"] if len(chunked[d]) == 1]
        for doc_id in singles:
            clean.append({"query_id": question["query_id"], "query": question["query"],
                          "doc_id": doc_id, "chunk_index": 0, "text": chunked[doc_id][0],
                          "label_source": "single-chunk article, no inference"})
        for doc_id in question["positive_ids"]:
            pieces = chunked[doc_id]
            if len(pieces) == 1:
                continue
            record = {"query_id": question["query_id"], "query": question["query"],
                      "doc_id": doc_id, "chunk_count": len(pieces), "chunks": pieces}
            (oversized if len(pieces) > arguments.max_chunks else tasks).append(record)

    # Batch by chunk volume, not by pair count: pairs carry between 2 and 30
    # chunks, so equal-sized batches would be wildly unequal reading loads.
    batches, current, load = [], [], 0
    for task in sorted(tasks, key=lambda t: -t["chunk_count"]):
        if current and load + task["chunk_count"] > arguments.batch_chunks:
            batches.append(current); current, load = [], 0
        current.append(task); load += task["chunk_count"]
    if current:
        batches.append(current)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "chunk_labels_clean.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in clean), encoding="utf-8")
    batch_dir = OUT / "judgement_batches"
    batch_dir.mkdir(exist_ok=True)
    for old in batch_dir.glob("*.json"):
        old.unlink()
    for index, batch in enumerate(batches):
        (batch_dir / f"batch_{index:03d}.json").write_text(
            json.dumps(batch, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "oversized_articles.json").write_text(
        json.dumps([{k: v for k, v in r.items() if k != "chunks"} for r in oversized],
                   ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"nhan SACH, khong suy luan : {len(clean):5} cap (bai bao 1 chunk)")
    print(f"can doc va cham           : {len(tasks):5} cap · {sum(t['chunk_count'] for t in tasks)} chunk · {len(batches)} lo")
    print(f"qua lon, LOAI bo          : {len(oversized):5} cap (tren {arguments.max_chunks} chunk)")
    if oversized:
        worst = max(oversized, key=lambda r: r["chunk_count"])
        print(f"   lon nhat: {worst['doc_id']} voi {worst['chunk_count']} chunk")
    print(f"lo -> {batch_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
