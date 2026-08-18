# Phase 5A — Remaining SQLite Domains Audit

**Scope:** read-only audit of the SQLite consumers that remain after the Phase 4B
auxiliary-domain cutover.  This document does not migrate data, change runtime
configuration, alter Alembic, or modify the SQLite database.

**Audit date:** 2026-07-18

## 1. Boundary and method

The following documents were read before this audit:

- `SQLITE_TO_POSTGRES_MIGRATION_PLAN.md`
- `docs/sqlite_to_postgres_audit.md`
- `docs/sqlite_to_postgres_phase2_design.md`
- `docs/sqlite_to_postgres_phase4b_cutover.md`

The primary SQLite file was opened as
`file:data/sqlite/local_ai_core.db?mode=ro` with `PRAGMA query_only=ON`.
PostgreSQL inspection used `SET TRANSACTION READ ONLY`.  Qdrant inspection only
used collection metadata and `scroll` reads.  No SQLite, PostgreSQL, Qdrant,
filesystem, runtime selector, or Alembic data was changed by the audit.

Phase 4B remains in effect: `AUXILIARY_DATABASE_BACKEND=postgres`.  Conversations,
messages, memories, OCR runs, request logs, and OCR cache are explicitly out of
scope here and were not changed.

## 2. Runtime reality at audit time

`app/main.py:create_app` still constructs `SQLiteStore(settings.database_path)`
unconditionally for the legacy document side.  With the current
`DOCUMENT_DATABASE_BACKEND=sqlite`, it wires:

```text
Document API -> DocumentService -> SQLiteStore + QdrantStore
RAG API      -> RetrievalService -> Bm25Service + SQLiteStore + QdrantStore
startup      -> CleanupService -> SQLiteStore + filesystem + QdrantStore
```

The existing PostgreSQL document implementation is present but inactive:
`main.py` selects `PostgresDocumentService` and `PostgresRetrievalService` only
when `Settings.uses_postgres_documents` is true.  This means PostgreSQL is not
yet the runtime source of truth for documents, even though its document schema
and partial matching rows already exist.

The independent RQ OCR/index workers in `app/workers/tasks.py:_service` use
`PostgresDocumentService`/`PostgresDocumentRepository` for document jobs, pages,
chunks and activation, but still instantiate `SQLiteStore` solely for the legacy
embedding cache passed to `PostgresDocumentService`.  OCR cache and request
logging there follow the already-cut-over auxiliary backend.

## 3. Direct data inventory and relationships

### 3.1 SQLite primary database

| SQLite table | Rows | Direct relationship evidence | Current classification |
|---|---:|---|---|
| `documents` | 3 | Two `indexed`, one `uploaded`; two indexed rows point to the two runs below. | `MIGRATE_WITH_MAPPING` |
| `document_ingestion_runs` | 2 | Both reference existing documents; orphan count `0`. | `MIGRATE_WITH_MAPPING` |
| `document_chunk_versions` | 4 | Three chunks for one indexed document and one for the other; orphan count `0`. | `MIGRATE_WITH_MAPPING` |
| `document_chunks` | 0 | Superseded flat chunk table; current store reads `document_chunk_versions`. | `DROP_AFTER_CUTOVER` |
| `embedding_cache` | 4 | `(model_name, content_hash)` cache with JSON vectors. | `REBUILD_FROM_POSTGRES` |
| `bm25_index` | absent | No persisted BM25 table exists. `Bm25Service` creates an in-memory index per search. | `REBUILD_FROM_POSTGRES` |

`documents` rows and source artifacts were checked directly.  Two source files
exist under `data/documents/{document_id}/original.{ext}` and their SHA-256
equals the SQLite `content_hash`; the remaining uploaded text document has no
source artifact, `source_available=0`, and no legacy content hash.

### 3.2 PostgreSQL document-side inventory

| PostgreSQL table | Rows | Result of comparison |
|---|---:|---|
| `documents` | 3 | All three SQLite opaque document IDs exist, with the same original filename, stored filename and MIME/content type. |
| `document_versions` | 2 | Deterministic IDs `ver_{document_id}_1`; each matches a SQLite indexed document/version 1. |
| `ingestion_runs` | 2 | IDs exactly match the two SQLite run IDs; `document_id`, status, stage and chunk/vector counts agree. |
| `document_pages` | 0 | Legacy SQLite has no page table, so no direct page migration evidence exists. |
| `document_chunks` | 4 | Same document/count/chunk-index/content-hash tuples as SQLite chunk versions. |
| `embedding_cache` | 0 | No legacy vectors copied, by design. |

There is, however, a **state mismatch** that blocks document cutover:

- SQLite says the two documents are `indexed`, `active_index_version=1`, and
  names the matching completed run.
- PostgreSQL has matching `ingestion_runs.status='indexed'` and four matching
  chunks, but both `document_versions.status='staging'`, both PostgreSQL
  `documents.status='uploaded'`, and `documents.active_version_id IS NULL`.
- No `document_pages` rows exist.  This is acceptable only if the Phase 5B
  policy permits the legacy source/chunk migration without page reconstruction;
  the policy must be explicit because page-level OCR/native provenance cannot
  be invented.

### 3.3 Exact document and version mapping conclusion

1. **Yes, all three SQLite document IDs have PostgreSQL rows.**  The proof is
   the same opaque `documents.id`, matching logical/original filename, stored
   filename and MIME type.  Two also have identical content hashes and source
   file SHA-256.  The third has no source in SQLite and SQLite has no content
   hash; PostgreSQL has a hash, so it must be treated as an explicit
   field-level mismatch to resolve rather than silently overwrite.
2. `SQLite.documents.active_index_version = 1` maps deterministically to
   `PostgreSQL.document_versions.id = 'ver_' + document_id + '_1'`, verified
   for both indexed documents.  This is a **mapping convention already present
   in data**, not an assumption.
3. The two SQLite ingestion-run IDs occur verbatim in PostgreSQL.  Their
   `document_id`, `index_version=1`/mapped `version_id`, status `indexed`, stage
   `indexed`, chunk count and vector count agree.  PostgreSQL timestamps are
   incomplete (`started_at`/`completed_at` null), so Phase 5B must preserve the
   legacy timestamps where its target schema permits it or record that
   information as non-representable.
4. `document_chunk_versions` is **not merely a disposable vector derivative**.
   `SQLiteStore.stage_document_chunks` writes canonical extracted chunk text,
   content hash, citation page range, locations JSON, heading path, section
   title, block type and extraction method.  Those fields drive
   `SQLiteStore.get_document_chunks` and `get_chunks_by_keys`, which in turn
   drive BM25 and dense-result content/citation resolution.  It therefore needs
   `MIGRATE_WITH_MAPPING` unless a source-document reparse/rechunk is chosen
   deliberately.  In this dataset the PostgreSQL chunk content hashes already
   match all four legacy chunks; Phase 5B still needs verification and state
   activation, not blind reinsertion.

### 3.4 Qdrant evidence

The `documents` collection contains 57 points.  The four points for the two
SQLite indexed documents use legacy payload `index_version=1`; they do **not**
have `version_id` or `chunk_id`.  Their point IDs are deterministic UUID5 values
derived from `{document_id}:{index_version}:{chunk_index}`.  The corresponding
PostgreSQL versioned retrieval path requires payload `version_id` and then
batch-loads PostgreSQL chunks.  Therefore Phase 5B/5C must re-upsert or map
these four points with the PostgreSQL `version_id` and `chunk_id` before setting
the new versions active.  Existing unrelated legacy points in the collection
are an additional duplicate/stale-data risk and must not be treated as
PostgreSQL-active candidates.

## 4. Consumer mapping

| Area | File / class / function | SQLite table or method | Read / write path | PostgreSQL/Qdrant equivalent and source of truth |
|---|---|---|---|---|
| Document upload/list/status/source/retention/delete/index | `app/routers/documents.py` endpoints -> `DocumentService` | `documents`, `document_ingestion_runs`, `document_chunk_versions`; `create_document`, `get_document`, `list_documents`, `next_index_version`, `create_ingestion_run`, `activate_ingestion`, `permanently_delete_document` | Both | PG `Document`, `DocumentVersion`, `IngestionRun`, `DocumentChunk`, `Job` exist but are inactive for this selector. SQLite is current runtime truth. |
| Legacy synchronous index | `app/services/document_service.py:_run_index_locked` | Run status, `stage_document_chunks`, embedding cache | Both | PG worker pipeline provides a versioned alternative; legacy source is SQLite until Phase 5C. |
| Document storage | `DocumentService._source_exists`, `upload`, `replace_source`, `remove_source`; `scripts/migrate_document_storage.py:migrate` | `documents.stored_filename`, `content_hash`, source availability methods | Both filesystem + SQLite metadata | `documents`/`source_available` exist in PG. Source folders are shared physical artifacts; SQLite still decides legacy state. |
| BM25 sparse retrieval | `app/services/bm25_service.py:Bm25Service.search` | `SQLiteStore.get_document_chunks` -> `document_chunk_versions` joined to active `documents` | Read | No PostgreSQL BM25 implementation. The index is ephemeral `rank_bm25.BM25Okapi`, so it can be rebuilt from PG active chunks. |
| Dense/hybrid retrieval | `app/services/retrieval_service.py:RetrievalService` | `get_active_index_versions`, `get_chunks_by_keys`, `touch_documents` | Read plus last-access write | `PostgresRetrievalService.retrieve` already filters active PG versions and batch-loads chunks. SQLite need is data + old implementation, not a Qdrant-only requirement. |
| Qdrant document mapping | `app/stores/qdrant_store.py:upsert_chunks/search/delete_document_version` | Legacy points use `index_version`; no SQLite content in payload | Read/write Qdrant | PG pipeline uses `version_id` + `chunk_id`; Phase 5B must bridge/re-upsert old points. |
| Legacy TTL cleanup | `app/services/cleanup_service.py:CleanupService` | temporary-source lookup, expired OCR/logs/inactive-run methods | Both filesystem/Qdrant/SQLite | OCR logs/runs are auxiliary PG now, but legacy service still calls SQLite methods. PG `PostgresCleanupService` handles PG superseded/deleting documents; SQLite remains source for old documents/runs. |
| PG cleanup worker | `scripts/cleanup_worker.py`, `app/services/postgres_cleanup_service.py` | none for document data | PG/Qdrant/filesystem | Active for PG lifecycle only. It cannot safely clean legacy SQLite state. |
| RQ OCR/index worker cache | `app/workers/tasks.py:_service`; `PostgresDocumentService.index_for_worker` | `SQLiteStore.get_embedding_cache/save_embedding_cache` | Both cache reads/writes | New PG `embedding_cache` table exists but has 0 rows and richer cache-key schema. Legacy four vectors must be rebuilt rather than copied. |
| Storage migration utility | `scripts/migrate_document_storage.py:migrate` | `list_documents_for_storage_migration`, `update_document_content_hash` | Both | Historical filesystem-layout utility; must not run during cutover because it writes SQLite. |
| Migration/audit tools | `scripts/audit_sqlite_readonly.py`, `scripts/migrate_sqlite_to_postgres.py` | read-only catalog / auxiliary domains | Read-only (audit) / migration tool | The current SQLite→PG migration tool deliberately excludes document tables. |

The cleanup row deserves an explicit compatibility note: `main.py` still builds
`CleanupService(store, ...)` with the legacy SQLite store.  Consequently its
`cleanup_expired_logs` and `cleanup_expired_ocr_runs` calls inspect old SQLite
tables, while the active auxiliary writer stores new logs/OCR runs in PostgreSQL.
This audit does not change that behavior, but Phase 7 must route those two
operations to their PostgreSQL lifecycle owner or remove the legacy calls; it
must not accidentally run both cleanup paths against the same logical data.

## 5. Dependency graph

```text
source artifact (data/documents/{id}/original.*)
        | content hash / filename / availability
        v
SQLite documents -- active_index_version --> SQLite document_ingestion_runs
        |                                      |
        |                                      v
        +--------------------------> document_chunk_versions
                                            |              \
                                            |               +--> legacy Qdrant payload: index_version
                                            v
                                  BM25 in-memory / legacy RetrievalService

PostgreSQL documents --> document_versions --> ingestion_runs / document_chunks
        |                 (currently staging)    (hashes match SQLite)
        +--> PostgresRetrievalService only after document-runtime cutover
```

The two graphs share IDs and source folders but have inconsistent activation
state and incompatible Qdrant payload version keys.  They are not yet a single
transactional source of truth.

## 6. Cleanup and cache decisions

### Cleanup state that must be retained/mapped

- Document `status`, `source_available`, `source_removed_at`, `pinned`,
  `retention_policy`, `last_accessed_at`, `content_hash`, current active version
  and active run are safety-critical.  Losing any can make a document
  unexpectedly retrievable, source-less, or eligible for deletion.
- Run `status`, `stage`, `cancel_requested`, error fields and completion/update
  timestamps are required to avoid removing a staging/failed version wrongly.
- Legacy inactive-run cleanup (`get_expired_inactive_ingestions`) deletes both
  Qdrant `index_version` points and SQLite chunks/runs.  It must be disabled for
  a document once Phase 5B begins, otherwise it can race the version mapping.

### Cache decisions

| Cache | Evidence | Decision |
|---|---|---|
| SQLite `embedding_cache` | 4 rows; key is only `(model_name, content_hash)` and vector JSON. | `REBUILD_FROM_POSTGRES`. Do not migrate because current PG cache schema requires model revision, dimensions and configuration/normalization fingerprint. |
| OCR cache | Auxiliary PG domain after Phase 4B. | Out of Phase 5A; no action. |
| BM25 | No storage table; rebuilt for each legacy search. | `REBUILD_FROM_POSTGRES` from active PG chunks in Phase 6. |
| Worker cache object | Workers instantiate SQLiteStore only for embedding cache. | `REBUILD_FROM_POSTGRES`; remove that dependency in Phase 7/8 after a PG cache adapter and cache-key policy are proven. |

## 7. Migration/rebuild/archive/drop classification

| Data / artifact | Classification | Reason and required guard |
|---|---|---|
| SQLite `documents` | `MIGRATE_WITH_MAPPING` | PG rows exist, but compare all mutable fields and reconcile status/active version explicitly. Do not overwrite the source-less document's PG hash without a policy. |
| SQLite `document_ingestion_runs` | `MIGRATE_WITH_MAPPING` | IDs already exist in PG; map integer version to verified version ID and reconcile timestamps/progress. |
| SQLite `document_chunk_versions` | `MIGRATE_WITH_MAPPING` | Contains canonical text and citation metadata; hash/metadata compare then backfill fields PG supports. Locations/heading path need a documented destination or archive. |
| SQLite `document_chunks` | `DROP_AFTER_CUTOVER` | Empty and superseded by versioned chunks. |
| Legacy Qdrant `index_version` points | `MIGRATE_WITH_MAPPING` | Re-upsert deterministic `version_id`/`chunk_id` payloads, validate counts, then only remove old points after PG retrieval is active. |
| Source files for two indexed docs | `ARCHIVE` plus live reuse | Preserve as original-source evidence/reindex input; do not delete by age. |
| Source-less uploaded document | `ARCHIVE` metadata | Cannot rebuild; preserve its metadata and source-unavailable status. |
| SQLite embedding vectors | `REBUILD_FROM_POSTGRES` | Four stale/under-keyed vectors are not compatible with the current cache key. |
| BM25 in-memory index | `REBUILD_FROM_POSTGRES` | No durable SQLite data. |
| OCR/image temporary artifacts | `ARCHIVE` until Phase 7 policy | Cleanup must not delete an artifact still referenced by an active legacy run. |

## 8. Tests that still create or depend on `.db`

| Test / fixture | SQLite dependency to replace or isolate |
|---|---|
| `tests/conftest.py` | Sets `DB_PATH` to `tests/test_local_ai_core.db`; legacy document test fixture. |
| `tests/test_storage_optimization.py` | Creates temporary `storage.db`; directly validates legacy chunk lookup, legacy dense retrieval, cache and cleanup. Replace with PostgreSQL document/retrieval/cleanup contracts in Phases 5C–7. |
| `tests/worker_integration_support.py`, `tests/test_rq_ingestion_integration.py`, `tests/test_versioned_ingestion.py`, `tests/test_postgres_cleanup_lifecycle.py` | Create temporary SQLite `cache.db` / `worker-cache.db` only for embedding cache while exercising PG document workers. Replace in Phase 7. |
| `tests/test_sqlite_to_postgres_migration.py` | Intentionally creates source fixture SQLite files for migration-tool tests. Retain until final SQLite migration/removal is verified. |
| `tests/test_postgres_auxiliary_store.py`, `tests/test_postgres_foundation.py` | Reference SQLite URLs/paths only to assert invalid PostgreSQL configuration or legacy document isolation; update expectations during final removal. |
| Root `tests/test_local_ai_core.db` and `backend/tests/test_local_ai_core.db` | Existing test database artifacts; audit only, do not delete in this phase. |

## 9. Risks, rollback boundary, and proposed order

### Main risks

1. **Activation split:** matching PG chunks/runs exist but PG documents are not
   active. Switching `DOCUMENT_DATABASE_BACKEND` now would make the two indexed
   documents disappear from retrieval.
2. **Qdrant payload split:** all audited legacy points use `index_version`; PG
   retrieval filters `version_id`, so a direct switch returns no legacy vectors.
3. **Metadata loss:** PG `document_chunks` lacks the legacy `locations_json` and
   `heading_path` fields. Phase 5B must choose a compatible schema extension or
   an archive/reparse strategy before final verification.
4. **Duplicate vectors:** the documents collection contains 57 legacy points,
   including many IDs not present in primary SQLite. Re-upsert must be scoped to
   verified document/version/chunk tuples and delete only after PG equivalence
   is proven.
5. **Source-less document:** it cannot be reparsed or reindexed from source.
   Migration must retain `source_available=false` and avoid fabricating a hash.

### Rollback boundary

Until Phase 5C activates the PG versions and changes
`DOCUMENT_DATABASE_BACKEND`, SQLite remains the live document/retrieval source
of truth.  A Phase 5B validation failure is therefore safe to roll back by
discarding only the validation-database changes and leaving the current selector
at `sqlite`.  Once PG receives new document writes after Phase 5C, rollback
requires a planned reverse migration/roll-forward; do not silently flip back to
SQLite.

### Minimal next phases

1. **Phase 5B — document metadata/version/ingestion migration tool:** read
   SQLite read-only; validate ID/content/source/hash relationships; reconcile
   PG documents, versions, runs and chunks in a dedicated validation database;
   create a deterministic mapping for legacy Qdrant payloads.  Do not activate
   runtime in this phase.
2. **Phase 5C — document runtime cutover:** freeze document writers, run final
   delta/verification, re-upsert versioned Qdrant points, atomically activate
   verified versions, switch `DOCUMENT_DATABASE_BACKEND=postgres`, and prove no
   new document writes reach SQLite.
3. **Phase 6 — BM25/retrieval rebuild and cutover:** implement sparse index
   construction from active PG chunks, then remove `RetrievalService`/`Bm25Service`
   reliance on SQLite after semantic/citation parity tests.
4. **Phase 7 — cleanup/cache cutover:** move remaining cleanup state and
   embedding-cache access to PG, with version-aware deletion guards and cache
   warm/rebuild; eliminate `SQLiteStore` from workers.
5. **Phase 8 — final SQLite code/test removal:** archive approved source DB
   backups, remove the selector and legacy implementation/tests only after all
   document/BM25/cleanup cutovers and retention verification pass.

## 10. Baseline checks run

| Command | Result |
|---|---|
| `python backend/scripts/audit_sqlite_readonly.py data/sqlite/local_ai_core.db` | Completed read-only inventory; confirmed the documented table counts. |
| Read-only SQLite/PG/Qdrant relationship queries | Completed; produced the ID/hash/version/state evidence in sections 3.1–3.4. |
| `cd backend && ..\\.venv\\Scripts\\python.exe -m pytest tests\\test_chunking.py tests\\test_hybrid_retrieval.py -q` | `3 passed`, `0 failed`, one existing Starlette deprecation warning. |

The first invocation of the same pytest command from repository root failed at
test collection because `app` is importable only when the working directory is
`backend`; rerunning from `backend` produced the passing result above.  No full
regression was run in this audit because the requested boundary is read-only and
the legacy full suite deliberately creates and mutates SQLite test databases.

## Phase 5A status

**COMPLETE — audit only.**  No data migration, runtime cutover, Alembic revision,
SQLite deletion, or auxiliary-domain change was performed.  Phase 5B may start
only after the team accepts the activation-state reconciliation policy, the
legacy-chunk metadata preservation policy (`locations_json`/`heading_path`),
and a controlled treatment for the source-less uploaded document and unrelated
legacy Qdrant points.
