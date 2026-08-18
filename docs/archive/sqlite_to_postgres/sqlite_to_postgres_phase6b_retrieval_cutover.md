# Phase 6B — PostgreSQL BM25/hybrid retrieval cutover

Date: 2026-07-18

## Preflight state

The approved PostgreSQL runtime database was reachable and Alembic reported
`20260718_09 (head)`.  Redis and Qdrant were reachable.  Immediately before
cutover the selectors were:

```text
AUXILIARY_DATABASE_BACKEND=postgres
DOCUMENT_DATABASE_BACKEND=postgres
RETRIEVAL_DATABASE_BACKEND=sqlite
```

Preflight evidence:

| Item | Observed value |
|---|---:|
| Active PostgreSQL documents | 5 |
| Active PostgreSQL versions | 5 |
| Active PostgreSQL chunks | 7 |
| Source-less documents with active version | 0 |
| OCR/index jobs queued/running/retrying | 0 |
| Qdrant points with `version_id` and `chunk_id` | 6 |
| Qdrant legacy `index_version`-only points | 65 |
| SQLite `documents` / `document_chunk_versions` / `document_chunks` | 3 / 4 / 0 |

The two verified legacy indexed documents have active PostgreSQL versions, the
PostgreSQL document smoke has a valid versioned Qdrant point, and the
source-less document `doc_b374b28332c640b28c98e2af2187bbbf` has no active
version.  Legacy Qdrant points deliberately remain present.

## Final test gate and parity

Commands completed before the switch:

* Alembic current: `20260718_09 (head)`.
* Retrieval/document/Qdrant/selector focus suite: **24 passed**.
* `scripts/benchmark_retrieval_parity.py --output
  data/benchmarks/phase6b_pre_cutover_parity.json --top-k 3`: exit 0.

The ten parity cases include keyword, phrase, semantic paraphrase, identifier,
citation, no-exact-match, document filter, hybrid, legacy-point and
source-less cases.  Required exact/filter/citation PostgreSQL results were
non-empty; every PostgreSQL result had `version_id` and `chunk_id`; no result
was duplicated; and the source-less filter returned an empty result.  The
current product has no score threshold, so the no-exact-match query continues
to return dense candidates by design.

## Freeze, protection and selector cutover

FastAPI, OCR Worker, Index Worker and Outbox Dispatcher were stopped briefly.
There were no queued OCR/index jobs.  PostgreSQL, Redis and Qdrant remained
available.

Protections created before changing configuration:

* PostgreSQL backup:
  `data/backups/postgres-phase6b/local-ai-20260718-053034.dump` (52,235 bytes).
* Qdrant production snapshot:
  `documents-7079489509187321-2026-07-17-22-30-34.snapshot`.

Only the local ignored `.env` selector was changed:

```text
RETRIEVAL_DATABASE_BACKEND=postgres
```

`AUXILIARY_DATABASE_BACKEND` and `DOCUMENT_DATABASE_BACKEND` remain
PostgreSQL.  Docker worker configuration now propagates the retrieval selector
rather than hard-coding SQLite.  FastAPI, OCR Worker, Index Worker and Outbox
Dispatcher were restarted.  No dual read/write path was enabled.

## Runtime RAG smoke

`POST /rag/chat` was executed against the running FastAPI process with the
exact-keyword query `BM25`, document-filtered to the migrated RAG document.
It returned HTTP 200, model `qwen3.5:9b`, three PostgreSQL-mapped sources and
the existing response contract.  The sources had the expected document,
chunk index, active index version, locations, heading, extraction method and
source availability.  The LLM response took 36,159 ms; retrieval itself is not
the source of that generation latency.

The ten direct runtime retrieval smoke cases produced:

* exact keyword, phrase, semantic, citation, filter and hybrid: 3 versioned,
  unique candidates each;
* identifier: 1 versioned candidate;
* no-exact-match: 3 versioned dense candidates, as expected without a threshold;
* source-less document filter: 0 candidates;
* legacy-risk query: only versioned PostgreSQL candidates.

Every non-empty result carried citation metadata and a content hash.  No
source-less result, versionless legacy point or duplicate old/new point was
returned.

## BM25 cache and PostgreSQL access evidence

The integration tests cover cache cold build, stable fingerprint reuse,
activation rebuild, supersede/deactivation rebuild and empty active corpus.
They use isolated PostgreSQL rather than a runtime fixture to avoid changing
the production corpus.  `PostgresBm25Service` is process-local, concurrency
protected and is rebuilt only when its active-corpus fingerprint changes.

Runtime retrieval touched exactly these PostgreSQL documents during the smoke:

* `doc_8eea844701b041b980e8142a2793f3ee`
* `doc_e002fbb8408c4d419531b15e1491e1e1`
* `doc_f2f1ba8d96b942e9ac3b523442234e29`

The three SQLite legacy `last_accessed_at` values remained unchanged.  A
selector-isolation test starts FastAPI with all PostgreSQL selectors and makes
`SQLiteStore.get_active_index_versions`, `get_document_chunks`,
`get_chunks_by_keys` and `touch_documents` fail if called; the application
injects `PostgresRetrievalService` successfully.  This proves the RAG
dependency path does not call legacy SQLite retrieval methods after selector
cutover.  SQLite remains instantiated only for explicitly out-of-scope cleanup
and embedding-cache consumers.

## Failure behavior

PostgreSQL BM25 failure and Qdrant failure tests prove errors propagate rather
than silently falling back to SQLite.  Dense retrieval rejects a legacy point,
missing PostgreSQL chunk, inactive version and duplicate candidate.  Empty
active corpus returns an empty result.  Touch failure is explicitly best-effort
and does not alter a valid retrieval response.

## Operations and tests

| Check | Result |
|---|---|
| `GET /health` after restart | HTTP 200; PostgreSQL, Redis, Qdrant and workers reachable |
| OCR worker smoke | exit 0; queue `local-ai:dev:ocr` |
| Index worker smoke | exit 0; queue `local-ai:dev:index` |
| `docker compose config -q` | exit 0 |
| Full regression with isolated `POSTGRES_TEST_URL` | **129 passed, 1 skipped** |

The remaining skip is
`test_validation_collection_payload_batch_loads_postgres_chunk`.  It requires
the optional Phase-5B validation-collection environment variable and is not an
active retrieval critical-path test; active PostgreSQL retrieval is covered by
the unskipped Phase 6A/6B tests.

## Files changed

* `.env` (local ignored selector only)
* `docker-compose.yml`
* `app/main.py`
* `app/postgres/repositories.py`
* `app/services/postgres_bm25_service.py`
* `app/services/postgres_retrieval_service.py`
* `app/stores/qdrant_store.py`
* `scripts/benchmark_retrieval_parity.py`
* `tests/test_postgres_retrieval_preparation.py`
* `tests/test_document_backend_selectors.py`
* `tests/test_postgres_cleanup_lifecycle.py`

## Rollback and remaining SQLite consumers

No rollback was used.  A controlled rollback to SQLite is still technically
possible only if the active corpus has not changed and the legacy
SQLite/Qdrant mapping remains compatible; it must be an explicit operational
decision, never an automatic fallback.  If PostgreSQL corpus state changes,
roll forward is required.

SQLite remains intentionally responsible for legacy cleanup and the embedding
cache.  No legacy Qdrant point was deleted, no SQLite database/table/store was
removed, and no score threshold, RRF or reranker behavior changed.

Phase 7 may begin only to move cleanup and embedding-cache ownership; it must
not remove the temporary selectors until the final SQLite-removal phase.
