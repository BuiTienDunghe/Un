# Kept eval reports

Every other file in `data/evaluation/results/` is per-run scratch and stays out
of git. These four are the retrieval chain a reader can walk end to end: each
number quoted in `docs/RESULTS.md`, in a model card, or on a CV resolves to one
of them, and each carries all 82 per-case rows — so a claim like "11 questions
improved, 2 regressed" is checkable rather than asserted.

Measured on `PC-dungbt`, lab database, embedding `qwen3-embedding:0.6b`,
corpus `data/evaluation/fixtures/multidoc/` (5 documents, 82 questions).

| File | Configuration | recall@5 | MRR | doc_hit |
| --- | --- | --- | --- | --- |
| `rag-multidoc-20260821-162010.json` | bare: contextual OFF, reranker OFF | 0.8659 | 0.7287 | 0.7683 |
| `rag-multidoc-20260821-162626.json` | P4-2: contextual ON, reranker OFF | 0.9146 | 0.7967 | 0.8415 |
| `rag-multidoc-20260821-172245.json` | P4-3: contextual ON, reranker ON | 0.9756 | 0.8581 | 0.8537 |
| `rag-multidoc-20260825-190252.json` | P4-6: + sliding-window rerank (shipped) | 0.9878 | 0.9360 | 0.9268 |

Two cautions, because a number without its measuring conditions is a rumour:

- The bare row here is the local run. `data/evaluation/rag_multidoc_baseline_bare.json`
  records MRR 0.7341 for the same configuration measured **in CI** — a different
  machine, hence a slightly different number. Compare like with like.
- `data/evaluation/rag_multidoc_baseline.json` is what the gate reads. These
  files are evidence, not gates; promoting a file here never changes a gate.

To promote another report: copy it in, add a row above, and cite it from
`docs/RESULTS.md`. Nothing else in `results/` is tracked.
