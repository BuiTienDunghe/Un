# Local AI Core

A self-hosted Vietnamese document assistant: retrieval-augmented answers with verifiable
citations, and a Discord agent with a layered, auditable memory. Every model runs locally
on one consumer GPU; PostgreSQL is the only source of truth.

Vietnamese documentation, which is more detailed and is what the system is operated from,
is in [README.md](README.md).

## Run it

```bash
docker compose up -d          # PostgreSQL 16, Redis, Qdrant
run-local-ai-core.bat         # API + OCR/index/cleanup/backup workers, runs migrations
```

Requires Docker and [Ollama](https://ollama.com) with the models listed in
`backend/app/config/models.yaml`. Open `http://127.0.0.1:8000`.

## What it is measured at

Every number below resolves to a JSON file in this repository. The chain of evidence is in
[docs/RESULTS.md](docs/RESULTS.md); the failures these numbers did *not* catch are in
[docs/FAILURE_MODES.md](docs/FAILURE_MODES.md).

| | | Measured on |
| --- | --- | --- |
| Retrieval recall@5 · MRR | **0.988** · **0.936** (from 0.866 · 0.734) | 82 questions over 5 documents, gated in CI |
| Retrieval latency p50 | **341 ms** (p95 358 ms) | same corpus, RTX 5060 Ti |
| Answer grounding rate | **0.939**, 0 ungrounded, 0 false positives | 82 answers, no extra model calls |
| Prompt-injection attack success | **0.000** (from 0.143), benign pass 1.000 | 12-case red-team suite |
| Memory extraction, end to end | P **0.94** · R **0.80** · 0 forged facts | 21-case pipeline eval |
| Memory poison rate after guard | **21.6%** (from 36.2%) at 96.7% coverage | 150-case extractor benchmark |
| Tests | **811** across 90 files, on real PostgreSQL/Redis/Qdrant | 4 CI jobs |
| Schema migrations | **32**, each with a working downgrade | `alembic check` gated in CI |

## How it is built

```
Web UI ─┐                                    ┌─ Qdrant  (vector index, derived)
        ├─ FastAPI ── services ── PostgreSQL ┤
Discord ┘     │                              └─ BM25 + pyvi (sparse index, derived)
              ├─ retrieval: hybrid BM25 + dense → RRF → cross-encoder rerank
              ├─ grounding self-check + prompt-injection defense (no extra model calls)
              ├─ memory: raw ledger → extractor → deterministic guard → verifier → review
              └─ RQ workers (OCR, index, memory) + outbox + cleanup + backup
```

Retrieval is hybrid: BM25 over `pyvi`-segmented Vietnamese lexemes and dense vectors are
fused with reciprocal rank fusion, then reordered by a cross-encoder that scores long
passages in overlapping windows. Answers carry citations that are persisted with the
message, so reopening an old conversation shows the sources it actually used.

The Discord agent's memory never trusts a single model. A message reaches long-term memory
only after a rule filter, an extractor, a deterministic evidence guard, and an entailment
verifier agree; anything applied automatically is audited and revocable in one click.

Design decisions and their measurements live in `docs/`, one document per phase, including
the experiments that were run and rejected.

## Operating rules the code enforces

1. PostgreSQL is the only source of truth. Qdrant and the sparse index are derived and
   rebuildable.
2. No database transaction ever wraps a model call.
3. Migrations are additive and every one has a downgrade; restore is rehearsed quarterly.
4. A retrieval change becomes the default only after the eval gate passes. No exceptions
   for "it looks better".
5. A fixed inference budget: no feature may add a generation call to the default answer
   path.
6. Every autonomous action is auditable and revocable.
7. Measure before changing a schema, on real data, before the migration is written.

## How this repo is built with AI assistance

Most commits here are co-authored with an AI coding agent, and the split is deliberate.
The agent scaffolds harnesses, tests, refactors, and writes documentation from numbers that
already exist. Hypotheses, ablation design, threshold decisions, hand-reading of failure
cases, and every claim in `docs/RESULTS.md` are the author's. Where a trained model lives in
this repository, its directory carries an `AUTHORSHIP.md` recording that split for that
model specifically.

## Stack

Python 3.11 · FastAPI · PostgreSQL 16 · Redis + RQ · Qdrant · Ollama
(`qwen3.5:9b`, `qwen3-embedding:0.6b`) · sentence-transformers cross-encoder · discord.py ·
Alembic · pytest · GitHub Actions · Docker Compose
