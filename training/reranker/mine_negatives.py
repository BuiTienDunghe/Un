"""Mine the negatives the reranker will actually have to reject.

A cross-encoder only ever sees what the retriever hands it, so a negative that the
retriever would never return teaches nothing. These are mined with the *product's* sparse
layer — `rank_bm25.BM25Okapi` over `tokenize_vietnamese`, the same tokenizer and version
the index is built with — run over the **full 61 425-article corpus**, not the 2 947-article
evaluation subset. Mining inside the subset would produce artificially easy negatives and
would draw them from the documents that are test answers.

Why BM25 alone, and not the shipped hybrid: the dense layer contributes **+0.004 Acc@1**
over BM25 on this corpus (`.scratch/reranker-finetune/spec.md`), so BM25's top window is
within a rounding error of the candidate pool the reranker is handed, and it can be built
offline in about three minutes instead of the four hours it would take to index 61 425
articles through the product path. The cost is stated rather than hidden: a negative that
only dense retrieval would surface is not represented here.

**Sampled within a wide window, not taken from the top.** Measured on this exact
configuration — cross-encoder, binary labels, Vietnamese legal text (arXiv 2507.14619):

    negatives/query   from the top   sampled in the top 90
    2                 0.2689         0.7681
    5                 0.4796         0.7791
    10                0.6751         0.7892
    (no fine-tuning: 0.5584)

MRR@10. Taking the hardest negatives lands **below the untrained baseline** — worse than
doing nothing. The top ranks are not skipped either: the system's error lives at ranks
2-3, and excluding them means never teaching the model to separate the candidates it
actually gets wrong.

Dev is mined too, but as a *pool*, not as pairs: dev carries no chunk-level labels (the
judgement pass covered train only), so it is scored the way the reported test set is —
by document identity, a hit being a chunk whose document answers the question.

    python -m training.reranker.mine_negatives
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

import numpy as np  # noqa: E402
from rank_bm25 import BM25Okapi  # noqa: E402

from app.utils.chunking import chunk_pages  # noqa: E402
from app.utils.vi_tokenizer import TOKENIZER_VERSION, tokenize_vietnamese  # noqa: E402

RAW = PROJECT_ROOT / "data" / "heldout_raw" / "zalo-legal"
OUT = PROJECT_ROOT / "data" / "evaluation" / "reranker_v1"
CHUNK_TOKENS, CHUNK_OVERLAP = 480, 80
SEED = 20260907


def document_chunks(doc: dict) -> list[str]:
    # Byte-for-byte the construction in build_judgement_tasks.py and remap_judgements.py,
    # so a chunk mined here is the chunk that was judged and the chunk the index holds.
    title = (doc.get("title") or "").strip()
    text = (doc.get("text") or "").strip()
    body = f"# {title}\n\n{text}\n" if title else text + "\n"
    return [c.content for c in chunk_pages([(None, body, "text")], CHUNK_TOKENS, CHUNK_OVERLAP)]


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]



def poison_check(drop_above: float | None = None) -> int:
    """Are the mined negatives actually negative, in the untrained model's own opinion?

    A negative the base model already scores as a confident positive is either a labelling
    miss (the article does answer the question and the qrels are sparse) or a near-duplicate
    of the positive; training on it teaches the model to contradict itself. The threshold is
    the paper's, on a sigmoid scale, and the base model emits raw logits — so the comparison
    is made after a sigmoid, and the logit that corresponds to it is printed too.
    """
    import math

    from sentence_transformers import CrossEncoder

    rows = [r for r in read_jsonl(OUT / "train_pairs.jsonl") if r["label"] == 0]
    positives = [r for r in read_jsonl(OUT / "train_pairs.jsonl") if r["label"] == 1]
    model = CrossEncoder("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
                         revision="1427fd652930e4ba29e8149678df786c240d8825", max_length=512)
    marked = time.perf_counter()
    logits = model.predict([[r["query"], r["text"]] for r in rows], batch_size=64,
                           show_progress_bar=False, convert_to_numpy=True)
    pos_logits = model.predict([[r["query"], r["text"]] for r in positives], batch_size=64,
                               show_progress_bar=False, convert_to_numpy=True)
    probabilities = 1.0 / (1.0 + np.exp(-logits))
    hot = float((probabilities >= 0.9).mean())
    print(f"cham {len(rows)} am + {len(positives)} duong bang model CHUA TRAN ({time.perf_counter()-marked:.0f}s)")
    print(f"  nguong 0.9 tren thang sigmoid = logit {math.log(0.9/0.1):.3f}")
    print(f"  AM     >= 0.9 : {hot*100:.1f}%   (nguong hong: ~10% · bo sach trong bai: 8.6%)")
    print(f"  AM     logit  : p50 {np.percentile(logits,50):.2f} · p90 {np.percentile(logits,90):.2f} · max {logits.max():.2f}")
    pos_prob = 1.0 / (1.0 + np.exp(-pos_logits))
    print(f"  DUONG  >= 0.9 : {float((pos_prob>=0.9).mean())*100:.1f}%")
    print(f"  DUONG  logit  : p50 {np.percentile(pos_logits,50):.2f} · p10 {np.percentile(pos_logits,10):.2f}")
    overlap = float((probabilities >= np.percentile(pos_prob, 50)).mean())
    print(f"  am cham cao hon trung vi cua duong: {overlap*100:.1f}%")
    if drop_above is not None:
        keep = [r for r, prob in zip(rows, probabilities) if prob < drop_above]
        dropped = len(rows) - len(keep)
        merged = sorted(positives + keep, key=lambda r: (r["query_id"], -r["label"]))
        (OUT / "train_pairs_clean.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in merged), encoding="utf-8")
        per_query = collections.Counter(row["query_id"] for row in keep)
        spread = collections.Counter(per_query.values())
        queries = {row["query_id"] for row in positives}
        print(f"loc >= {drop_above}: bo {dropped} am ({dropped / len(rows) * 100:.1f}%), con {len(keep)}")
        print(f"  am moi cau sau khi loc: {dict(sorted(spread.items()))}")
        print(f"  cau khong con am nao  : {len(queries - set(per_query))}")
        print("  -> " + str(OUT / "train_pairs_clean.jsonl"))

    manifest_path = OUT / "mining_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["poison_check"] = {
        "negatives_scored": len(rows), "share_at_or_above_0.9": round(hot, 4),
        "threshold": 0.10, "verdict": "sach" if hot < 0.10 else "HONG",
        "scored_with": "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 @ 1427fd65 (untrained)",
    }
    if drop_above is not None:
        manifest["poison_check"]["dropped_above"] = drop_above
        manifest["poison_check"]["negatives_dropped"] = dropped
        manifest["poison_check"]["negatives_kept"] = len(keep)
        manifest["poison_check"]["clean_file"] = "train_pairs_clean.jsonl"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nket luan: {'SACH' if hot < 0.10 else 'HONG — dung train'} -> {manifest_path}")
    return 0 if hot < 0.10 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, default=90,
                        help="Rank depth the negatives are sampled from. Production hands the reranker "
                             "candidate_limit*3 = 45 candidates; 90 covers that with margin.")
    parser.add_argument("--per-query", type=int, default=10,
                        help="Negatives per training query. 10 was the best of 2/5/10 in the table above.")
    parser.add_argument("--dev-pool", type=int, default=45,
                        help="Candidates kept per dev query — exactly the production pool size.")
    parser.add_argument("--limit-docs", type=int, default=0, help="Only for a timing check.")
    parser.add_argument("--poison-check", action="store_true",
                        help="Score the mined negatives with the UNTRAINED reranker and stop. "
                             "Pre-registered gate: above ~10%% scoring >= 0.9 the set is poisoned "
                             "(arXiv 2507.14619 measured 50.9%% for a poisoned set, 8.6%% for a safe one).")
    parser.add_argument("--drop-above", type=float, default=None, metavar="P",
                        help="With --poison-check: also write train_pairs_clean.jsonl without the "
                             "negatives the untrained model scores at or above P on the sigmoid "
                             "scale. Those are the labels most likely to be wrong — these qrels are "
                             "sparse by construction (see build_splits.py) — and a binary loss taught "
                             "on them learns confident rejection of correct answers, which is how "
                             "reranker-vi-v1 destroyed 13 answers that stood at rank 1-3.")
    arguments = parser.parse_args()

    if arguments.poison_check:
        return poison_check(arguments.drop_above)

    started = time.perf_counter()
    corpus_path = RAW / "corpus.jsonl"
    chunk_texts: list[str] = []
    chunk_doc: list[str] = []
    chunk_index: list[int] = []
    with corpus_path.open(encoding="utf-8") as handle:
        for count, line in enumerate(handle):
            if arguments.limit_docs and count >= arguments.limit_docs:
                break
            row = json.loads(line)
            for index, content in enumerate(document_chunks(row)):
                chunk_texts.append(content)
                chunk_doc.append(row["_id"])
                chunk_index.append(index)
    print(f"cat manh : {len(chunk_texts)} chunk tu {len(set(chunk_doc))} tai lieu ({time.perf_counter()-started:.0f}s)", flush=True)

    marked = time.perf_counter()
    tokenized = [tokenize_vietnamese(text) for text in chunk_texts]
    print(f"tach tu  : {TOKENIZER_VERSION} ({time.perf_counter()-marked:.0f}s)", flush=True)

    marked = time.perf_counter()
    index = BM25Okapi(tokenized)
    del tokenized
    print(f"BM25     : dung xong ({time.perf_counter()-marked:.0f}s)", flush=True)

    positives_by_query: dict[str, list[dict]] = collections.defaultdict(list)
    for row in read_jsonl(OUT / "chunk_labels_clean.jsonl") + read_jsonl(OUT / "chunk_labels_judged.jsonl"):
        positives_by_query[row["query_id"]].append(row)

    # A chunk is addressed by (doc_id, chunk_index) everywhere in this pipeline.
    position = {(doc, idx): n for n, (doc, idx) in enumerate(zip(chunk_doc, chunk_index))}

    rng = random.Random(SEED)
    marked = time.perf_counter()
    stats = collections.Counter()
    train_rows: list[dict] = []
    dev_rows: list[dict] = []

    for split in ("train", "dev"):
        queries = read_jsonl(OUT / f"zalo_legal_{split}.jsonl")
        for number, query in enumerate(queries, 1):
            scores = index.get_scores(tokenize_vietnamese(query["query"]))
            # argpartition then sort the window only: a full sort of 81k scores per query
            # would cost more than the BM25 scoring it follows.
            top = np.argpartition(-scores, arguments.window)[:arguments.window]
            window = [int(n) for n in top[np.argsort(-scores[top])]]
            forbidden = set(query["positive_ids"])

            if split == "dev":
                # A pool, scored later by document identity: no chunk labels exist for dev.
                pool = window[:arguments.dev_pool]
                dev_rows.append({
                    "query_id": query["query_id"], "query": query["query"],
                    "positive_ids": sorted(forbidden),
                    "candidates": [{"doc_id": chunk_doc[n], "chunk_index": chunk_index[n],
                                    "text": chunk_texts[n], "bm25_rank": rank}
                                   for rank, n in enumerate(pool)],
                })
                stats["dev_pool_hits"] += any(chunk_doc[n] in forbidden for n in pool)
                continue

            rows = positives_by_query.get(query["query_id"])
            if not rows:
                stats["train_no_label"] += 1
                continue
            candidates = [n for n in window if chunk_doc[n] not in forbidden]
            if len(candidates) < arguments.per_query:
                stats["train_thin_window"] += 1
            rank_of = {n: rank for rank, n in enumerate(window)}
            chosen = rng.sample(candidates, min(arguments.per_query, len(candidates)))
            for row in rows:
                train_rows.append({"query_id": query["query_id"], "query": query["query"], "label": 1,
                                   "doc_id": row["doc_id"], "chunk_index": row["chunk_index"], "text": row["text"],
                                   "source": row.get("label_source", "")})
                stats["positives"] += 1
                # A positive whose chunk is missing from the mined corpus would mean the
                # label and the index disagree; assert it rather than discover it in training.
                if not arguments.limit_docs and (row["doc_id"], row["chunk_index"]) not in position:
                    raise SystemExit(f"nhan tro toi chunk khong co trong corpus: {row['doc_id']}#{row['chunk_index']}")
            for n in chosen:
                train_rows.append({"query_id": query["query_id"], "query": query["query"], "label": 0,
                                   "doc_id": chunk_doc[n], "chunk_index": chunk_index[n], "text": chunk_texts[n],
                                   "source": f"bm25 rank {rank_of[n]} of {arguments.window}"})
                stats["negatives"] += 1
            stats["ranks_under_10"] += sum(1 for n in chosen if rank_of[n] < 10)
            if number % 250 == 0:
                print(f"  {split} {number}/{len(queries)} ({time.perf_counter()-marked:.0f}s)", flush=True)

    (OUT / "train_pairs.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in train_rows), encoding="utf-8")
    (OUT / "dev_pool.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in dev_rows), encoding="utf-8")

    manifest = {
        "built_by": "training/reranker/mine_negatives.py",
        "seed": SEED,
        "window": arguments.window,
        "negatives_per_query": arguments.per_query,
        "dev_pool": arguments.dev_pool,
        "corpus": {"path": str(corpus_path.relative_to(PROJECT_ROOT)),
                   "documents": len(set(chunk_doc)), "chunks": len(chunk_texts),
                   "chunker": f"chunk_pages({CHUNK_TOKENS}, {CHUNK_OVERLAP})"},
        "tokenizer_version": TOKENIZER_VERSION,
        "retriever": "rank_bm25.BM25Okapi — sparse layer only; dense adds +0.004 Acc@1 on this corpus",
        "counts": dict(stats),
        "sha256": {name: hashlib.sha256((OUT / name).read_bytes()).hexdigest()
                   for name in ("train_pairs.jsonl", "dev_pool.jsonl")},
    }
    (OUT / "mining_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\ntrain: {stats['positives']} duong + {stats['negatives']} am = {len(train_rows)} cap")
    print(f"  am o hang < 10 (khong bo qua dinh): {stats['ranks_under_10']} ({stats['ranks_under_10']/max(stats['negatives'],1)*100:.0f}%)")
    print(f"  cau hoi khong co nhan chunk       : {stats['train_no_label']}")
    print(f"  cua so khong du am                : {stats['train_thin_window']}")
    print(f"dev  : {len(dev_rows)} cau · pool {arguments.dev_pool} · co it nhat 1 chunk dung trong pool: "
          f"{stats['dev_pool_hits']}/{len(dev_rows)} ({stats['dev_pool_hits']/max(len(dev_rows),1)*100:.0f}%)")
    print(f"tong {time.perf_counter()-started:.0f}s -> {OUT/'mining_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
