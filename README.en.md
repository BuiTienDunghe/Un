# Local AI Core

A self-hosted Vietnamese document assistant: retrieval-augmented answers with verifiable
citations, and a Discord agent with a layered, auditable memory. Every model runs locally
on one consumer GPU; PostgreSQL is the only source of truth.

Vietnamese documentation, which is more detailed and is what the system is operated from,
is in [README.md](README.md).

## Run it

```bash
run-local-ai-core.bat   # starts PostgreSQL 16, Qdrant and Redis in Docker, runs migrations,
                        # pulls the models, then the API (OCR/indexing run in its threads)
                        # plus the cleanup and backup workers
```

Requires Docker and [Ollama](https://ollama.com). The models are the active versions in
`backend/app/config/model_versions.yaml`; the launcher pulls them, and builds the OCR model
`ocr-v1` with `ollama create` from its tracked Modelfile once its gguf exists, which is made
once by hand (`docs/model_registry.md`). It opens
`http://127.0.0.1:8000/ui/`.

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
| Tests | **2,181** collected (03/11/2026), on real PostgreSQL/Redis/Qdrant | 4 CI jobs |
| Schema migrations | **35**, each with a downgrade | `alembic check` gated in CI |

## How it is built

```
Web UI ─┐                                    ┌─ Qdrant  (vector index, derived)
        ├─ FastAPI ── services ── PostgreSQL ┤
Discord ┘     │                              └─ BM25 + pyvi (sparse index, derived)
              ├─ retrieval: hybrid BM25 + dense → RRF → cross-encoder rerank
              ├─ grounding self-check + prompt-injection defense (no extra model calls)
              ├─ memory: raw ledger → extractor → deterministic guard → verifier → review
              └─ OCR/index in API threads · RQ memory worker + outbox · cleanup · backup
```

Retrieval is hybrid: BM25 over `pyvi`-segmented Vietnamese lexemes and dense vectors are
fused with reciprocal rank fusion, then reordered by a cross-encoder that scores long
passages in overlapping windows. Answers carry citations that are persisted with the
message, so reopening an old conversation shows the sources it actually used.

The Discord agent's memory never trusts a single model. A message reaches long-term memory
automatically only after a rule filter, an extractor, a deterministic evidence guard and
(when switched on; it ships off) an entailment verifier agree; everything else waits for a
human. Anything applied automatically is audited and revocable in one click.

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
   path, with three exceptions of at most one extra call per turn each: rewriting a
   follow-up question before retrieval, one retry when an answer states figures the turn
   never saw, and one retry when the model writes a tool call that cannot be parsed. Both
   retries stay inside the turn's time budget. A fourth exception ships off
   (`AGENT_LONG_INPUT_ENABLED`): a pasted text too long for the model's window is read in
   parts, one call per part, at most `ceil(100 000 / part size)` parts (3 with the 16k window)
   and never more than 8. Those calls are counted in a budget of their own, equal to the
   number of parts, nested inside the agent's, so the agent's cap is unchanged; the parts
   stop at the turn's time budget and the answer says which were not read. A fifth exception,
   on by the owner's decision (`agent.lookup_check`): a turn that called no tool and answered
   "I have no information", about anything but a text pasted into it, is sent back once to
   look, one extra call (`max_steps + 4`). A sixth, on by the owner's decision (`agent.read_rest`): a turn that
   found a document, left part of it unread and said the fact is not there has the code read
   the rest, one call per part, at most 8, in a budget of its own, plus one call for the
   answer; the parts stop at the turn's time budget and the answer says what was not read.
   A seventh, on wherever a tool carries it (today `remind`, so only with Discord reminders
   on): the speaker asked for what only that tool does and the answer never called it, so the
   model is asked once for the tool's arguments alone, in an Ollama structured output held to
   the tool's schema, the tool runs through its own checks, and one more round answers from
   the result (two calls); without structured output the turn is sent back in words, and a
   request still not carried out is said by the code.
   The router counts
   every generation call a turn makes (`services/call_budget.py`): a cap of 1 for plain
   chat, 2 for RAG, and `max_steps + 5` for the agent with both checks on. A turn past its cap is logged and
   recorded, never blocked, and `tests/test_call_budget.py` fails when a path goes over or a
   cap has room to spare.
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
