# Phase 6A — PostgreSQL retrieval preparation

Date: 2026-07-18.  This phase builds and verifies the PostgreSQL retrieval
path only.  Runtime remains:

```text
AUXILIARY_DATABASE_BACKEND=postgres
DOCUMENT_DATABASE_BACKEND=postgres
RETRIEVAL_DATABASE_BACKEND=sqlite
```

No selector was changed, no legacy Qdrant point was deleted, and cleanup plus
the legacy embedding cache remain SQLite-owned.

## Audit mapping

| Legacy implementation | PostgreSQL preparation | Behavioural result |
|---|---|---|
| `Bm25Service.search` reads `SQLiteStore.get_document_chunks` and builds `BM25Okapi` per request. | `PostgresBm25Service.search` reads `PostgresDocumentRepository.active_chunk_snapshot`. | Both use `tokenize_vietnamese` and `BM25Okapi`; PostgreSQL cache is process-local. |
| `RetrievalService.retrieve` performs dense/BM25/hybrid selection, RRF, optional rerank, SQLite content lookup and `touch_documents`. | `PostgresRetrievalService.retrieve` now performs the same mode selection, RRF and reranking, then resolves candidates from PostgreSQL. | The public result keys used by `RagService`/`rag.py` are retained. |
| `RetrievalService._filter_active_versions` filters legacy `index_version` after Qdrant search. | `_dense` asks Qdrant for authoritative active PostgreSQL `version_id` values and additionally checks the returned document/version/chunk tuple. | Versionless legacy points are ignored, not repaired or deleted. |
| `SQLiteStore.get_chunks_by_keys` batch-loads canonical content/citations. | `active_chunks_by_ids` batch-loads only active PostgreSQL chunks by `chunk_id`. | Qdrant payload never supplies canonical content. |
| `SQLiteStore.touch_documents` writes `last_accessed_at`. | `PostgresDocumentRepository.touch_documents` uses a short PostgreSQL transaction. | Only final reranked result documents are touched; touch failure is best-effort and cannot fail retrieval. |

`RagService.respond`, `RagService.stream_response`, and `routers/rag.py` were
audited.  They consume `content`, document/chunk identity, score and citation
fields; no API contract was changed.  `RerankerService` is reused unchanged.

## PostgreSQL BM25 and cache

`PostgresBm25Service` builds candidates only from:

```text
documents.status = indexed
AND documents.active_version_id = document_versions.id
AND document_versions.status = active
AND document_chunks.version_id = document_versions.id
```

The cached record preserves document/version/chunk IDs, canonical content and
hash, filename/source availability, page range, locations, heading path,
section title, block type and extraction method.  Its fingerprint is the
ordered active document/version set plus document update timestamp, version
activation timestamp, active chunk count and latest chunk timestamp.  It is
protected by a process-local `RLock`; identical fingerprints reuse the index.
Activation, superseding, deletion or chunk-count changes alter the fingerprint
and rebuild on the next search.  `invalidate()` is available for explicit
service-lifecycle invalidation.

`rank_bm25` can assign a zero IDF when every indexed chunk contains a token
(including a one-document corpus).  Only when no positive BM25 candidate
exists, the PostgreSQL implementation uses deterministic token-overlap as an
exact-lexical fallback.  This prevents an exact keyword from disappearing; it
does not replace a positive BM25 ranking.

## Dense filtering, fusion and citations

The Qdrant request is filtered by the active `version_id` values calculated
from PostgreSQL.  Every returned candidate is rejected unless it has both
`version_id` and `chunk_id`, and those fields, document ID and chunk index
match one active PostgreSQL chunk.  This rejects legacy `index_version` points,
stale/missing chunks, superseded versions and old/new duplicates.

Hybrid behavior retains the existing Reciprocal Rank Fusion implementation:
`1 / (rrf_k + rank)` for dense and sparse rankings.  The PostgreSQL key includes
document, version and chunk identity, preventing cross-version collapse.  The
existing `rag.rrf_k` config is used; no model or reranker setting changed.

Citation fields resolved from PostgreSQL are `page_start`, `page_end`,
`locations`, heading path (serialized as the compatible `"A > B"` string),
section title, block type, extraction method, source availability and content
hash.  Filters accept one document ID, a list or no filter.  A source-less
document with no active version has no searchable rows.

## Parity set and observed result

`scripts/benchmark_retrieval_parity.py` defines ten read-only cases based on
the audited RAG and Local AI chunks: exact keyword, exact phrase, semantic
paraphrase, identifier, citation wording, no exact match, document filter,
hybrid candidate, legacy-point exclusion and source-less exclusion.  It
disables SQLite and PostgreSQL access touching during benchmarking.

Command run:

```powershell
.venv\Scripts\python.exe backend\scripts\benchmark_retrieval_parity.py `
  --output data\benchmarks\phase6a_retrieval_parity.json --top-k 3
```

The generated ignored artifact is `data/benchmarks/phase6a_retrieval_parity.json`.
For the four exact/filter/citation cases, PostgreSQL returned the same mapped
document/chunk IDs and content hashes in the top-k as SQLite.  Example first
run latency: exact keyword SQLite 1150.22 ms (cold model) versus PostgreSQL
362.10 ms; later representative queries were roughly 276–320 ms on both
paths.  The no-exact-match case still returns dense semantic candidates in
both paths because the current product has no score threshold; this is existing
behaviour, not treated as a no-answer guarantee.

Acceptance evidence:

* exact keyword and phrase candidates remain in PostgreSQL top-k;
* citations/content hashes for mapped active chunks agree;
* source-less filtered query returns no result in either path;
* PostgreSQL output has no versionless legacy candidate and no old/new duplicate.

## Tests

| Command | Actual result |
|---|---|
| `pytest test_postgres_retrieval_preparation.py test_hybrid_retrieval.py -q` | 9 passed |
| Retrieval/document/Qdrant focus suite | 18 passed |
| Full regression with isolated `POSTGRES_TEST_URL` | 128 passed, 1 skipped |
| `docker compose config -q` | exit 0 |

The Phase 5C optional skip is
`test_validation_collection_payload_batch_loads_postgres_chunk`; it is skipped
only when `PHASE5B_QDRANT_VALIDATION_COLLECTION` is unset.  It is a validation
collection integration test rather than the active Phase-6A retrieval path;
the active path has direct PostgreSQL/Qdrant tests in
`test_postgres_retrieval_preparation.py`.

## Files

* `app/services/postgres_bm25_service.py` — PostgreSQL sparse cache.
* `app/services/postgres_retrieval_service.py` — dense validation, hybrid RRF,
  citation resolution and best-effort touch.
* `app/postgres/repositories.py` — active snapshot, active chunk batch lookup,
  PostgreSQL touch.
* `app/stores/qdrant_store.py` — versioned writes now include a content hash,
  never canonical text.
* `app/main.py` — prepares the PG retrieval dependency graph only if the
  retrieval selector is switched in a later phase.
* `scripts/benchmark_retrieval_parity.py` — read-only parity harness.
* `tests/test_postgres_retrieval_preparation.py` — active-version, cache,
  fallback, stale/legacy rejection, fusion, citation and touch tests.

## Remaining differences, risks and Phase 6B gate

The legacy path has no score threshold and can return dense candidates for a
query with no exact sparse hit.  PostgreSQL intentionally retains that product
behavior.  BM25 caches are per process; a multi-process deployment rebuilds
independently after an activation.  This is safe but may cause a short cold
search after cutover.

Before Phase 6B, run the full regression with `POSTGRES_TEST_URL`, repeat the
parity benchmark after any corpus/model change, choose an explicit score/no
answer policy if desired, freeze retrieval writers/config, then and only then
switch `RETRIEVAL_DATABASE_BACKEND=postgres`.  Cleanup, embedding cache and
legacy Qdrant cleanup remain out of scope.
