# SQLite → PostgreSQL audit — Phase 0 and Phase 1

Date: 2026-07-18  
Scope: read-only inventory only. No runtime, Alembic revision, repository/service,
or SQLite database file was changed in these phases.

## Phase 0 — Safety snapshot

| Item | Result |
|---|---|
| Git branch | `sqlite-to-postgres-audit` created from commit `6306f59cf40c46d8b88e997e35f2df676e923b65` |
| Worktree before audit | Dirty; existing changes were preserved and not reset/reverted |
| PostgreSQL Alembic head | `20260718_06 (head)` on `local_ai_core_test` |
| SQLite snapshot | `data/backups/sqlite-phase0-20260718T030117Z/sqlite/` — byte-for-byte copy of `data/sqlite/` |
| Snapshot manifest | `data/backups/sqlite-phase0-20260718T030117Z/sqlite-file-manifest.json` |
| Read-only inventory | `backend/scripts/audit_sqlite_readonly.py`, output stored beside the snapshot |
| Baseline regression | `96 passed`, `0 failed`, one Starlette TestClient deprecation warning |

The audit script opens the source with SQLite URI `mode=ro`, executes
`PRAGMA query_only=ON`, and only executes catalog/schema/count/sample `SELECT`
statements. Its samples contain only numeric values or type/length/SHA-256
prefixes, never user text.

### SQLite file inventory

| File | Bytes | SHA-256 | Classification |
|---|---:|---|---|
| `data/sqlite/local_ai_core.db` | 176,128 | `EF3E0AB31A2E00A6C2C21E6C43BC566AAB4493992B074A0EA0FF59412EC1C764` | primary migration source |
| `data/sqlite/local_ai_core.pre_postgres_20260716T175939Z.db` | 176,128 | `13FB9F81C81A5E2A721A414BDE28547B0B956F76CC7D917FDEC847DA41C5287C` | archive only |
| `data/sqlite/local_ai_core.pre_postgres_20260716T180021Z.db` | 176,128 | same as above | archive only |
| `data/sqlite/local_ai_core.pre_postgres_20260716T180024Z.db` | 176,128 | same as above | archive only |
| `tests/test_local_ai_core.db` | 57,344 | `15D277BB7D64AD2493460CAC19235ECCE332E56CA7A0389800C5CA95ABF73646` | test fixture; do not migrate |
| `backend/tests/test_local_ai_core.db` | 929,792 | `B3C2B76BF27F3C70800B3B90ADDF93B6B974A63032E72569F17B8DCE4A06BCD2` | test/legacy fixture; do not migrate |

The three `pre_postgres_*` files have not been opened for migration, merged, or
modified. Equal checksums are an observation only, not evidence that merging is
safe.

## Phase 1 — primary SQLite schema

Source: `data/sqlite/local_ai_core.db`. The read-only audit found **12 tables,
0 views, and 0 triggers**.

| SQLite table | Rows | PK / FK / unique facts observed | Code consumer and operation | Current PostgreSQL equivalent | Decision |
|---|---:|---|---|---|---|
| `conversations` | 12 | PK `id`; no FK | `ChatService.respond/stream_response`; `routers/conversations.py` list/get/delete; `SQLiteStore` conversation methods | none | `MIGRATE_REQUIRED` |
| `messages` | 24 | PK `id`; FK `conversation_id → conversations.id`; no explicit index beyond rowid | `ChatService.respond/stream_response`, `SQLiteStore.add_message/get_messages` | none | `MIGRATE_REQUIRED`; migrate after conversations |
| `memories` | 0 | PK `id` | `MemoryService.add/_require/update/delete`; `SQLiteStore` memory methods | none; Qdrant has vectors only | `MIGRATE_REQUIRED` schema, zero production rows |
| `request_logs` | 19 | PK `id` | `LoggingService.log_request`; `CleanupService.cleanup_expired_logs` | none | `MIGRATE_SELECTIVE`; retention decision required |
| `ocr_runs` | 1 | PK `id`; JSON stored in `result_json` | `OcrJobService.view/list_history/delete/_save`; `CleanupService.cleanup_expired_ocr_runs` | none | `MIGRATE_REQUIRED` |
| `ocr_cache` | 0 | composite PK/unique `(model_name,image_hash)` | `OCRService.recognize_png` cache hit/save | none | `MIGRATE_SELECTIVE`; zero current rows |
| `embedding_cache` | 4 | composite PK/unique `(model_name,content_hash)` | `PostgresDocumentService._run_index/index_for_worker`; legacy `DocumentService`; `SQLiteStore` cache methods | none | `REBUILD` by default; decision depends on model/config compatibility |
| `documents` | 3 | PK `id`; no declared FK | legacy `DocumentService`; `CleanupService`; `migrate_document_storage.py` | `documents` (PostgreSQL) | `MIGRATE_REQUIRED` only after field-level verification; existing target differs |
| `document_ingestion_runs` | 2 | PK `id`, unique `(document_id,index_version)`; no declared FK | legacy `DocumentService`; `CleanupService` | `ingestion_runs` | `MIGRATE_REQUIRED` only after ID/version mapping is designed |
| `document_chunk_versions` | 4 | integer PK `id`, unique `(document_id,index_version,chunk_index)`; no declared FK | legacy `DocumentService`, `RetrievalService.get_chunks_by_keys`, `SQLiteStore` version methods | `document_chunks` plus `document_versions` | `MIGRATE_REQUIRED` for canonical text, subject to version mapping verification |
| `document_chunks` | 0 | integer PK `id`, FK `document_id → documents.id`, unique `(document_id,chunk_index)` | `Bm25Service.get_document_chunks`, legacy `RetrievalService` | no direct active equivalent; current PG uses versioned chunks | `REBUILD` or `DROP_AFTER_CUTOVER`; zero rows |
| legacy cleanup metadata | 0 separate table; it is derived from timestamps/status in `documents`, `document_ingestion_runs`, `ocr_runs`, `request_logs` | `CleanupService` methods named above | partial coverage in `PostgresCleanupService` for document lifecycle | `ARCHIVE` behavior until each relevant domain is cut over |

### Exact schema facts

The full column type/nullability/default/PK-position, all FK metadata, indexes,
and masked one-row samples are in
`data/backups/sqlite-phase0-20260718T030117Z/primary-audit.json`.

Notable dependency order, based on observed FKs and actual consumers:

```text
conversations → messages
documents → document_chunks (declared FK)
documents + document_ingestion_runs + document_chunk_versions → legacy cleanup/retrieval
ocr_runs → OCR console history/cleanup
request_logs → logging/cleanup
OCR and embedding cache → OCR/index execution
```

`document_chunk_versions` and `document_ingestion_runs` have no declared SQLite
foreign keys despite containing `document_id`; migration verification must test
those logical relationships explicitly.

## PostgreSQL comparison

Read-only query against `local_ai_core_test` found the current tables:

```text
alembic_version, documents, document_versions, ingestion_runs,
document_pages, document_chunks, jobs, outbox_events
```

They are defined by `backend/app/postgres/models.py` and migrations through
`backend/alembic/versions/20260718_06_cleanup_lifecycle.py`. There is currently
no PostgreSQL table/model for conversations, messages, memories, request logs,
OCR runs, OCR cache, or embedding cache. Therefore no runtime cutover conclusion
is made in this report.

## Test and legacy databases

The read-only audit also inspected both test databases; neither is a migration
source.

| Database | Non-zero tables |
|---|---|
| `tests/test_local_ai_core.db` | `documents=1`, `request_logs=2` |
| `backend/tests/test_local_ai_core.db` | `conversations=267`, `messages=532`, `documents=221`, `document_ingestion_runs=144`, `document_chunk_versions=184`, `document_chunks=40`, `embedding_cache=4`, `ocr_runs=107`, `request_logs=1452` |

Their complete read-only reports are `root-test-audit.json` and
`backend-test-audit.json` in the Phase 0 snapshot directory.

## Consumer inventory and remnant scope

`backend/app/stores/sqlite_store.py:SQLiteStore` is imported by
`main.py`, `workers/tasks.py`, `ChatService`, `MemoryService`,
`LoggingService`, `OCRService`, `OcrJobService`, legacy `DocumentService`,
legacy `RetrievalService`, `Bm25Service`, and `CleanupService`.

Concrete non-runtime consumers also include:

- `backend/scripts/migrate_sqlite_to_postgres.py` — existing document-only
  migration, imports `sqlite3`.
- `backend/scripts/migrate_document_storage.py` — reads `SQLiteStore` document
  metadata to move source files.
- `backend/tests/test_storage_optimization.py`, `test_postgres_foundation.py`,
  `test_versioned_ingestion.py`, `test_rq_ingestion_integration.py`,
  `test_postgres_cleanup_lifecycle.py`, and `worker_integration_support.py`.

The exact search and method-level evidence was recorded during this audit with
`rg` against `backend/app`, `backend/scripts`, and `backend/tests`.

## Risks and unresolved issues

1. `messages.conversation_id` and `document_chunks.document_id` are the only
   declared SQLite foreign keys. Logical document/version relationships must be
   verified during Phase 3, not inferred from names.
2. The existing document migration script is document-only and writes staging
   versions; it cannot migrate the seven auxiliary domains found here.
3. `embedding_cache` has four rows but no stored embedding model revision beyond
   `model_name`; a Phase 2/3 decision is required before migrating stale vectors.
4. `request_logs` needs an approved retention boundary before selective migration.
5. `OCRRun.result_json` needs a PostgreSQL JSONB schema/validation decision.
6. The worktree was already dirty before this audit; rollback is the newly-created
   branch plus the recorded starting commit, not a claim that the worktree is clean.

## Conditions before Phase 2

- Approve target PostgreSQL schemas for the seven missing auxiliary domains.
- Approve retention for request logs and migration-vs-rebuild policy for caches.
- Define legacy integer `index_version` to PostgreSQL `document_versions.id`
  mapping and verify document ownership.
- Keep the Phase 0 snapshot and do not modify/merge `pre_postgres_*` backups.
- Add an Alembic revision only after the above schema decisions are reviewed.

## Commands actually run

```powershell
git status --short
git switch -c sqlite-to-postgres-audit
.venv\Scripts\python.exe -m alembic current
.venv\Scripts\python.exe backend\scripts\audit_sqlite_readonly.py data\sqlite\local_ai_core.db ...
.venv\Scripts\python.exe backend\scripts\audit_sqlite_readonly.py tests\test_local_ai_core.db ...
.venv\Scripts\python.exe backend\scripts\audit_sqlite_readonly.py backend\tests\test_local_ai_core.db ...
cd backend; ..\.venv\Scripts\python.exe -m pytest tests -q
```
