"""Turn a BEIR-shaped public dataset into a corpus this system can ingest.

Why a subset. Zalo Legal has 61 425 documents. They would enter through the
product's own ingestion API one upload at a time, and with contextual retrieval
on, every chunk costs a generation call — hours of GPU that belongs to a user.
So the corpus here is every document some test query is judged relevant to,
plus a deterministic sample of distractors.

What that costs, stated plainly: recall@k measured on a 3 000-document corpus is
NOT comparable to a published number measured on 61 425. Fewer documents means
fewer chances to be wrong. What it *is* good for is comparing two configurations
against each other on identical, human-written data that this project did not
invent — which is the question H1 asks. Anyone wanting a leaderboard-comparable
number has to index the full corpus and should say so.

The sample is seeded, and the seed and every count are written next to the
output, so a rebuild is the same corpus or the manifest hash changes.

    python -m training.common.build_heldout_corpus --dataset zalo-legal --distractors 2500
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import unicodedata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = PROJECT_ROOT / "data" / "heldout_raw"
OUT_DIR = PROJECT_ROOT / "data" / "evaluation" / "heldout_retrieval_v1"

SEED = 20260904


def safe_name(corpus_id: str) -> str:
    """A filename that survives Windows, keeps the id readable, and stays unique.

    Corpus ids look like `100/2019/nđ-cp+5`: slashes, diacritics and a plus.
    Folding them away can collide, so an 8-character hash of the original id
    rides along and the mapping is written out.
    """
    folded = unicodedata.normalize("NFD", corpus_id)
    folded = "".join(c for c in folded if unicodedata.category(c) != "Mn")
    folded = folded.replace("đ", "d").replace("Đ", "D")
    folded = re.sub(r"[^A-Za-z0-9]+", "_", folded).strip("_")[:60]
    digest = hashlib.sha256(corpus_id.encode("utf-8")).hexdigest()[:8]
    return f"{folded}__{digest}.txt"


def build(dataset: str, distractors: int, max_chars: int) -> None:
    base = RAW_DIR / dataset
    if not (base / "corpus.jsonl").exists():
        raise SystemExit(f"Missing {base/'corpus.jsonl'}. Run: python -m training.common.fetch_heldout --dataset {dataset}")

    queries = {}
    for line in (base / "queries.jsonl").open(encoding="utf-8"):
        row = json.loads(line)
        queries[row["_id"]] = row["text"]

    relevant: dict[str, list[str]] = {}
    for line in (base / "qrels" / "test.jsonl").open(encoding="utf-8"):
        row = json.loads(line)
        if int(row.get("score", 0)) > 0:
            relevant.setdefault(row["query-id"], []).append(row["corpus-id"])

    needed = {doc for docs in relevant.values() for doc in docs}
    print(f"{len(relevant)} cau hoi test · {len(needed)} tai lieu duoc phan xet lien quan")

    # One pass over the corpus: keep every needed document, and reservoir-sample
    # distractors so the 115 MB file is never held in memory.
    rng = random.Random(SEED)
    kept: dict[str, dict] = {}
    pool: list[dict] = []
    seen = 0
    for line in (base / "corpus.jsonl").open(encoding="utf-8"):
        row = json.loads(line)
        if row["_id"] in needed:
            kept[row["_id"]] = row
            continue
        seen += 1
        if len(pool) < distractors:
            pool.append(row)
        else:
            j = rng.randrange(seen)
            if j < distractors:
                pool[j] = row

    missing = needed - kept.keys()
    if missing:
        # A judged document absent from the corpus makes its query unanswerable,
        # which would silently depress every score measured here.
        print(f"CANH BAO: {len(missing)} tai lieu duoc phan xet nhung khong co trong corpus; "
              f"bo cac cau hoi lien quan. Vi du: {sorted(missing)[:3]}")
        relevant = {q: d for q, d in relevant.items() if not (set(d) - kept.keys())}

    corpus_dir = base / "subset" / "corpus_files"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    for old in corpus_dir.glob("*.txt"):
        old.unlink()

    names: dict[str, str] = {}
    truncated = 0
    for row in list(kept.values()) + pool:
        name = safe_name(row["_id"])
        names[row["_id"]] = name
        title = (row.get("title") or "").strip()
        text = (row.get("text") or "").strip()
        if len(text) > max_chars:
            # A handful of documents run to 250 000 characters. Keeping them
            # whole would let one outlier dominate indexing time; the cut is
            # recorded rather than hidden.
            text = text[:max_chars]
            truncated += 1
        body = f"# {title}\n\n{text}\n" if title else f"{text}\n"
        (corpus_dir / name).write_text(body, encoding="utf-8")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cases = []
    for query_id, docs in sorted(relevant.items()):
        if query_id not in queries:
            continue
        cases.append({
            "id": query_id,
            "group": "heldout",
            "question": queries[query_id],
            "expected_docs": sorted(names[d] for d in docs),
        })
    dataset_path = OUT_DIR / f"{dataset}_subset.jsonl"
    with dataset_path.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case, ensure_ascii=False) + "\n")

    corpus_hash = hashlib.sha256()
    for name in sorted(names.values()):
        corpus_hash.update(name.encode())
        corpus_hash.update((corpus_dir / name).read_bytes())
    provenance = {
        "dataset": dataset,
        "built_by": "training/common/build_heldout_corpus.py",
        "seed": SEED,
        "source_corpus_documents": len(kept) + seen,
        "relevant_documents": len(kept),
        "distractors": len(pool),
        "corpus_documents": len(names),
        "queries": len(cases),
        "documents_truncated_at": max_chars if truncated else None,
        "documents_truncated": truncated,
        "corpus_sha256": corpus_hash.hexdigest(),
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "corpus_dir": str(corpus_dir.relative_to(PROJECT_ROOT)),
        "comparability": (
            "Subset of the published corpus. Absolute recall/nDCG here are NOT "
            "comparable to numbers measured on the full 61k corpus; comparisons "
            "between configurations measured on THIS corpus are."
        ),
    }
    (OUT_DIR / f"{dataset}_subset_provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"corpus  : {len(names)} tai lieu ({len(kept)} lien quan + {len(pool)} gay nhieu) -> {corpus_dir}")
    print(f"cau hoi : {len(cases)} -> {dataset_path}")
    if truncated:
        print(f"cat bot : {truncated} tai lieu qua {max_chars} ky tu")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="zalo-legal")
    parser.add_argument("--distractors", type=int, default=2500,
                        help="How many non-relevant documents to mix in. More is harder and slower.")
    parser.add_argument("--max-chars", type=int, default=20000,
                        help="Cut documents longer than this; a few run to 250k characters.")
    arguments = parser.parse_args()
    build(arguments.dataset, arguments.distractors, arguments.max_chars)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
