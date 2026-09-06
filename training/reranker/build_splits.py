"""Split Zalo Legal into train / dev / test for reranker fine-tuning.

Two defects in the published packaging have to be handled here, and both were
found by counting rather than by reading the dataset card.

**24 queries appear in both the train and the test qrels**, each with a
*different* relevant document — for example one question about reform schools is
judged against article 2 of a circular in train and article 12 of the same
circular in test. So this is not a duplicated row; it is one question whose real
relevance set was split across the two files.

Two consequences, and they point in opposite directions:

1. Training on those queries lets the model see a test question. They are
   dropped from train. Test is left untouched, because a baseline has already
   been measured on all 788 of its queries and moving the goalposts after the
   fact is how a number stops meaning anything.
2. The test labels are *incomplete*. A system that returns article 2 for that
   question is right and will be scored wrong. Every number measured on this
   set therefore understates the truth. That is inherent to sparse labelling and
   cannot be fixed here — only stated.

`queries.jsonl` also carries 102 duplicate lines (identical ids, identical text).
Harmless, deduplicated for tidiness.

    python -m training.reranker.build_splits
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW = PROJECT_ROOT / "data" / "heldout_raw" / "zalo-legal"
OUT = PROJECT_ROOT / "data" / "evaluation" / "reranker_v1"

SEED = 20260905


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def relevance(rows: list[dict]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = collections.defaultdict(set)
    for row in rows:
        if int(row.get("score", 0)) > 0:
            out[row["query-id"]].add(row["corpus-id"])
    return dict(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev-fraction", type=float, default=0.10,
                        help="Share of training queries held back for early stopping.")
    arguments = parser.parse_args()

    queries: dict[str, str] = {}
    duplicates = 0
    for row in read_jsonl(RAW / "queries.jsonl"):
        if row["_id"] in queries:
            duplicates += 1
            continue
        queries[row["_id"]] = row["text"]

    train_rel = relevance(read_jsonl(RAW / "qrels" / "train.jsonl"))
    test_rel = relevance(read_jsonl(RAW / "qrels" / "test.jsonl"))

    contaminated = sorted(set(train_rel) & set(test_rel))
    for query_id in contaminated:
        del train_rel[query_id]

    # Split by QUERY, never by row: two rows of the same query landing on
    # opposite sides of the boundary is the same leak this file exists to close.
    ids = sorted(train_rel)
    random.Random(SEED).shuffle(ids)
    dev_size = int(len(ids) * arguments.dev_fraction)
    dev_ids, train_ids = set(ids[:dev_size]), set(ids[dev_size:])

    OUT.mkdir(parents=True, exist_ok=True)
    written = {}
    for name, keep, source in (("train", train_ids, train_rel),
                               ("dev", dev_ids, train_rel),
                               ("test", set(test_rel), test_rel)):
        path = OUT / f"zalo_legal_{name}.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for query_id in sorted(keep):
                handle.write(json.dumps({
                    "query_id": query_id,
                    "query": queries[query_id],
                    "positive_ids": sorted(source[query_id]),
                }, ensure_ascii=False) + "\n")
        written[name] = (len(keep), path)

    # Assert the property rather than trust the code that just produced it.
    sets = {name: {json.loads(l)["query_id"] for l in (OUT / f"zalo_legal_{name}.jsonl").read_text(encoding="utf-8").splitlines()}
            for name in ("train", "dev", "test")}
    for a, b in (("train", "dev"), ("train", "test"), ("dev", "test")):
        shared = sets[a] & sets[b]
        if shared:
            raise SystemExit(f"RO RI: {len(shared)} cau hoi nam o ca {a} lan {b}")

    manifest = {
        "built_by": "training/reranker/build_splits.py",
        "seed": SEED,
        "source": "GreenNode/zalo-ai-legal-text-retrieval-vn (MIT)",
        "queries_deduplicated": duplicates,
        "contaminated_queries_dropped_from_train": len(contaminated),
        "contaminated_query_ids": contaminated,
        "splits": {name: {"queries": n, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                   for name, (n, p) in written.items()},
        "label_completeness_warning": (
            "Test labels are sparse: the 24 dropped queries each carry a different relevant "
            "document in train than in test, proving the real relevance set is larger than "
            "either file records. Every score on this set understates true performance."
        ),
        "roles": {
            "train": "gradient updates only",
            "dev": "early stopping and hyperparameter choice; never reported as a result",
            "test": "reported numbers only; a baseline was measured on it on 04/09/2026",
        },
    }
    (OUT / "splits_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"queries.jsonl: bo {duplicates} dong trung, con {len(queries)} cau hoi")
    print(f"bo khoi TRAIN {len(contaminated)} cau hoi bi nhiem tu test")
    for name, (n, path) in written.items():
        print(f"  {name:6} {n:5} cau hoi -> {path.name}")
    print(f"kiem cheo: khong cap tap nao chung cau hoi")
    print(f"manifest -> {OUT / 'splits_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
