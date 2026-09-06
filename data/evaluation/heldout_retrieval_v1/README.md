# Held-out retrieval sets

The first evaluation in this project that this project did not write.

Everything else under `data/evaluation/` was authored here: the corpus is this
repository's own documentation, and the questions were written by hand against the
chunk text the system had already produced. That set is a good regression gate and a
poor argument. A score on it cannot be compared with anyone else's, and — as the first
run against a public corpus proved within thirty documents — it cannot see failures
that only appear in document types the author did not have.

## What is here

| File | What it is |
| --- | --- |
| `zalo-legal_subset.jsonl` | 788 questions with the organisers' own relevance judgements |
| `zalo-legal_subset_provenance.json` | seed, counts and corpus hash for the subset |
| `results/` | one report per measured configuration |

Source: [Zalo AI Challenge 2021 legal text retrieval](https://huggingface.co/datasets/GreenNode/zalo-ai-legal-text-retrieval-vn),
MIT licensed, 61 425 documents and 3 298 queries in BEIR layout. The questions are
real Vietnamese legal questions; the judgements say which article answers each one.

## The subset, and what it costs

The corpus here is 2 947 documents: every document some test query is judged relevant
to (447), plus 2 500 distractors sampled with a fixed seed. Not the full 61 425,
because documents enter through the product's own ingestion API one at a time —
measured at roughly one document per second, so the full corpus would be most of a
day, and with contextual retrieval on it would additionally spend one generation call
per chunk.

**So absolute recall and nDCG here are not comparable to a published number measured
on the full corpus.** Fewer documents means fewer chances to be wrong. What the subset
is good for is comparing configurations against each other on identical, human-written
data — which is the question the reranker work asks. A leaderboard-comparable number
needs the whole corpus and should say so.

## Reproducing it

```bash
python -m training.common.fetch_heldout --dataset zalo-legal      # checks the licence first
python -m training.common.build_heldout_corpus --dataset zalo-legal --distractors 2500
python -m training.common.eval_stack --profile heldout --start    # own db, collection, queue
python -m training.common.ingest_corpus --corpus-dir data/heldout_raw/zalo-legal/subset/corpus_files \
    --base-url http://127.0.0.1:8200
python -m training.common.eval_heldout --dataset data/evaluation/heldout_retrieval_v1/zalo-legal_subset.jsonl \
    --base-url http://127.0.0.1:8200 --label bare
```

The build is seeded. A rebuild that produces a different `corpus_sha256` than the
provenance file records is a different corpus, and its numbers are not comparable with
earlier ones.

Raw downloads live in `data/heldout_raw/`, which is gitignored: 115 MB of somebody
else's corpus does not belong in this repository, and the fetch script makes it
reproducible without it.

## Scoring

Document-level, the way the retrieval literature reports it: nDCG@10, recall@5 and
@10, MRR. A query is answered when a judged-relevant document appears in the ranking;
several chunks of one document collapse to that document's first appearance.

This is a different contract from `scripts/evaluate_rag.py`, which requires a chunk to
contain every expected verbatim phrase. That works because those questions were
written against the chunk text; a public set has no verbatim phrases, only judgements.
The two scorers are kept separate so that adding one cannot break the gate the other
runs in CI.

## What this set already found

On the first ingest, 32.6% of the corpus was rejected as containing no readable text —
the chunker was reading every numbered legal clause as a heading, which left no body
to chunk. That took 166 of the 447 relevant documents and 184 of the 788 questions
with it. The 82-question in-repo eval could not have found it: its corpus is markdown
with `#` headings.

Written up in `docs/FAILURE_MODES.md` §5; the fix and its pre-registered experiment
are in `.scratch/chunker-numbered-clause/spec.md`.

## Not here yet

- **Table-Markdown-Retrieval-VN** (MIT): a different document shape, worth adding.
- **UIT-ViQuAD 2.0**: **no licence is declared** on the Hub as of 04/09/2026. Scoring
  a model on it locally is ordinary benchmarking; redistributing it, or publishing a
  set derived from it, is not. It is also parquet-only, which the runtime environment
  cannot read. Left out deliberately rather than by oversight.
