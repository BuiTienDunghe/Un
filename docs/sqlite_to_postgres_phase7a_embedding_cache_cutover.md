# Phase 7A — PostgreSQL embedding-cache cutover

Date: 2026-07-18

## Scope and retained runtime state

This phase moves only the embedding-cache dependency of the PostgreSQL
document indexer and RQ OCR/index workers.  The runtime selectors remain:

```text
AUXILIARY_DATABASE_BACKEND=postgres
DOCUMENT_DATABASE_BACKEND=postgres
RETRIEVAL_DATABASE_BACKEND=postgres
```

`CleanupService` is unchanged and remains the intentional SQLite consumer.
No SQLite vectors, Qdrant legacy points, migration/audit tools, or selectors
were deleted or changed.

## Audit: actual cache consumers

| Consumer | File and function | Previous behavior | Phase 7A behavior |
|---|---|---|---|
| Thread fallback indexing | `app/services/postgres_document_service.py`, `_run_index` | called `SQLiteStore.get_embedding_cache` / `save_embedding_cache` for every chunk | calls the dedicated `EmbeddingCacheStore` contract |
| RQ index worker | `PostgresDocumentService.index_for_worker` | same two SQLite calls inside the embedding loop | calls the PostgreSQL cache contract; the Ollama call remains outside a database transaction |
| RQ worker dependency graph | `app/workers/tasks.py:_service` | constructed `SQLiteStore(settings.database_path)` solely to supply the document service cache (and used it as an auxiliary fallback) | constructs `PostgresEmbeddingCacheStore` and `PostgresAuxiliaryStore`; no `SQLiteStore` import or construction remains in the module |
| FastAPI document service | `app/main.py:lifespan` | passed the global SQLite cleanup store into `PostgresDocumentService` | passes `PostgresEmbeddingCacheStore(postgres_sessions)`; the global SQLite store remains only for cleanup/legacy lifecycle |

The legacy key in `SQLiteStore.get_embedding_cache` is only
`(model_name, content_hash)`.  The audited `models.yaml` embedding configuration
contains `provider`, `name` (`qwen3-embedding:0.6b`) and `context`, but no
model revision, dimensions, or normalization setting.  Those missing facts
must not be invented.

## PostgreSQL cache contract and identity

`app/stores/embedding_cache_store.py` adds:

* `EmbeddingCacheIdentity`, containing `content_hash`, `model_name`,
  `model_revision`, `dimensions`, `config_fingerprint`, and
  `normalization_fingerprint`.
* `EmbeddingCacheStore`, the narrow cache-only contract used by the document
  service.
* `PostgresEmbeddingCacheStore`, which uses the existing PostgreSQL
  `embedding_cache` table and its `uq_embedding_cache_key` tuple.

Fingerprints use canonical JSON plus SHA-256.  Reads validate that the JSONB
value is a finite numeric list with exactly the requested dimensions.  Invalid
payloads and dimension mismatches are cache misses, with a structured warning
containing cache identity data but never canonical document text.  Saves use a
PostgreSQL upsert keyed by the complete identity.

`PostgresDocumentService._cache_identity` returns no identity unless revision,
normalization and dimensions are explicitly known.  In the current real
configuration that yields a **safe miss**: embedding proceeds, but no cache
row is read or written under an ambiguous key.  This preserves correctness and
lets cache warming begin naturally when revision/normalization metadata is
provided by a later verified model configuration; no model setting was changed
in this phase.

The embedding flow is deliberately:

```text
construct complete identity
→ short PostgreSQL cache read
→ close session
→ call embedding model
→ validate returned vector
→ short PostgreSQL upsert
```

Lookup or save failures log a structured non-content event and proceed with
the freshly computed vector.  A model failure occurs before save, so no failed
or partial vector is cached.

## Legacy cache and warm policy

No legacy SQLite cache row was copied.  The Phase 5A audit identified four
legacy vectors whose old identity lacks revision, dimensions, configuration
fingerprint and normalization fingerprint.  During this Phase 7A operational
check the actual SQLite file contained five historical rows; all have creation
timestamps before the Phase 7A smoke run, so the discrepancy is historical
data rather than a new worker write.  They remain untouched for archive/audit
purposes.

There is no forced reindex or corpus-wide warm.  The cache warms only through
future normal indexing/reindexing where the complete identity is supplied.
Until then, safe misses preserve successful indexing without risking vector
reuse across incompatible model settings.

## Runtime verification

Before restart, PostgreSQL had `embedding_cache=0` and no queued/running/
retrying extract or index job.  A PostgreSQL backup was created at:

```text
data/backups/postgres-phase7a/local-ai-20260718-182933.dump
```

The Docker image was rebuilt and both RQ workers were restarted.  Their smoke
commands exited zero and reported the expected queues plus PostgreSQL, Redis,
and task-import connectivity:

```text
worker-ocr:   local-ai:dev:ocr
worker-index: local-ai:dev:index
```

FastAPI was restarted and `GET /health` returned HTTP 200.  A uniquely named
tiny text document was uploaded and indexed through the running service.  Its
run completed with one chunk and one embedded vector; PostgreSQL recorded an
`indexed` document, an `active` version and a versioned Qdrant point with a
`version_id` and `chunk_id`.  Because the real model config has no revision or
normalization metadata, PostgreSQL cache rows remain zero: this is the
expected safe-miss evidence, not a cache failure.  The SQLite cache row list
showed no timestamp from this smoke run.

## Tests and checks

| Command/check | Result |
|---|---|
| `pytest backend/tests/test_postgres_embedding_cache.py -q` | 10 passed |
| cache + versioned ingestion + RQ integration focus suite | 15 passed |
| full `pytest backend/tests -q` with isolated `POSTGRES_TEST_URL` | 139 passed, 1 skipped, 1 Starlette deprecation warning |
| `docker compose config -q` | exit 0 |
| `docker compose --profile workers up -d --build worker-ocr worker-index` | exit 0 |
| OCR worker container smoke | exit 0 |
| Index worker container smoke | exit 0 |
| `GET /health` | HTTP 200 |

`test_postgres_embedding_cache.py` covers complete-identity hit/miss,
revision/config/normalization/dimensions invalidation, invalid vector payload,
idempotent upsert, safe-miss when revision is absent, cache lookup/save failure
policy, and absence of `SQLiteStore` from the worker task module.  Existing
worker fixtures in `worker_integration_support.py`,
`test_rq_ingestion_integration.py`, `test_versioned_ingestion.py`, and
`test_postgres_cleanup_lifecycle.py` now use PostgreSQL cache dependencies
instead of `cache.db`/`worker-cache.db` cache fixtures.

The one skipped regression test is the pre-existing optional Phase 5B
validation-collection test requiring `PHASE5B_QDRANT_VALIDATION_COLLECTION`;
it does not cover the active embedding-cache path.

## Files changed

* `app/stores/embedding_cache_store.py` — dedicated PostgreSQL cache contract.
* `app/services/postgres_document_service.py` — complete identity, safe miss,
  and best-effort cache failure policy.
* `app/workers/tasks.py` — PostgreSQL-only worker dependency graph.
* `app/main.py` — PostgreSQL document service receives the new cache store.
* `tests/test_postgres_embedding_cache.py` — cache contract and wiring tests.
* `tests/worker_integration_support.py`, `tests/test_rq_ingestion_integration.py`,
  `tests/test_versioned_ingestion.py`, `tests/test_postgres_cleanup_lifecycle.py`
  — no SQLite cache fixture for PostgreSQL worker/document tests.

## Remaining SQLite consumers and Phase 7B gate

The RQ OCR/index worker has no SQLite embedding-cache dependency.  SQLite
remains intentionally used by legacy cleanup and by explicitly read-only
migration/audit tools; legacy BM25/cache test fixtures also remain until final
SQLite removal.  Phase 7B may begin only as a separate cleanup-lifecycle
cutover; it must not delete the historical SQLite cache rows or remove SQLite
before cleanup has moved.
