# Phase 8A — remove SQLite compatibility from runtime

Date: 2026-07-18.  This phase removes SQLite from runtime and ordinary tests
only.  It does **not** delete, archive, or move SQLite databases and it does
not modify legacy Qdrant points.

## 1. SQLite reference inventory before edits

| Classification | Concrete locations before Phase 8A | Decision |
|---|---|---|
| `REMOVE_RUNTIME` | `app/main.py:lifespan`; `app/stores/sqlite_store.py:SQLiteStore`; `DocumentService`, `RetrievalService`, `Bm25Service`, `CleanupService` | Removed. |
| `REMOVE_LEGACY_TEST` | `tests/conftest.py` `DB_PATH`; `test_storage_optimization.py`; `test_hybrid_retrieval.py`; selector tests | Removed or replaced with PostgreSQL tests. |
| `KEEP_MIGRATION_TOOL` | `scripts/migrate_sqlite_to_postgres.py`; `migrate_sqlite_documents_to_postgres.py`; `migrate_document_storage.py` | Retained as explicitly invoked legacy migration utilities. |
| `KEEP_MIGRATION_TEST` | `test_sqlite_to_postgres_migration.py`; `test_sqlite_document_migration.py` | Retained; each creates a temporary legacy SQLite source fixture. |
| `KEEP_HISTORICAL_DOCUMENTATION` | Phase 0–7 migration reports and plan | Retained as historical evidence. |
| `UNRESOLVED` | Legacy Qdrant points with only `index_version` | Explicitly deferred to Phase 9. |

Post-edit source search confirms that `sqlite3` remains only in the three
explicit migration/audit utilities and the two migration-tool tests.  There is
no `SQLiteStore`, `aiosqlite`, `sqlite://`, `DB_PATH`, `DATABASE_PATH`,
`check_same_thread`, `StaticPool`, or temporary backend selector in `app/`,
Compose runtime wiring, or `.env.example`.

## 2. Runtime code and selectors removed

`Settings` now has one required `DATABASE_URL`; it must use a
`postgresql+` SQLAlchemy dialect.  Missing URL and `sqlite://` fail fast.
The temporary `AUXILIARY_DATABASE_BACKEND`, `DOCUMENT_DATABASE_BACKEND`,
`RETRIEVAL_DATABASE_BACKEND`, and `CLEANUP_DATABASE_BACKEND` selectors, the
SQLite path setting, and SQLite directory creation were removed.

`main.py` always constructs PostgreSQL sessions, `PostgresAuxiliaryStore`,
`PostgresDocumentService`, `PostgresEmbeddingCacheStore`,
`PostgresBm25Service`, and `PostgresRetrievalService`.  It no longer imports,
constructs, stores, or health-checks `SQLiteStore`.  Cleanup is owned only by
the PostgreSQL cleanup worker.  `RagService` uses a small retrieval protocol
instead of importing the deleted legacy retrieval implementation.

Deleted runtime files:

* `backend/app/stores/sqlite_store.py`
* `backend/app/services/document_service.py`
* `backend/app/services/retrieval_service.py`
* `backend/app/services/bm25_service.py`
* `backend/app/services/cleanup_service.py`

The OCR promotion path was completed on `PostgresDocumentService`; it creates
an OCR-derived Markdown source and indexes supplied OCR pages without a second
OCR call.  This replaces a dependency that had previously lived in the legacy
document service.

## 3. Config, health, dependency, and tests

`.env.example` now documents only `DATABASE_URL`, `CONTAINER_DATABASE_URL`,
and `POSTGRES_TEST_URL`-compatible PostgreSQL configuration.  Compose workers
receive the container PostgreSQL URL directly; no selector/fallback is passed.
No `aiosqlite` dependency existed in `requirements.txt`, so no dependency
removal was required.

`GET /health` no longer returns SQLite.  It reports PostgreSQL, Redis, Qdrant,
Ollama, OCR/index worker queue discovery, outbox state, and a cleanup-worker
heartbeat written into the shared data volume. SQLite metrics were removed with
the SQLite operational branch.

Ordinary API tests now set `DATABASE_URL` to isolated `POSTGRES_TEST_URL` and
clean PostgreSQL document fixtures.  Deleted SQLite-only tests were replaced
by PostgreSQL document/retrieval/cleanup coverage already present in the
suite.  SQLite fixtures remain only inside the migration-tool tests.

`test_postgres_runtime_guard.py` proves a missing/non-PostgreSQL URL fails,
FastAPI startup does not import `sqlite3` or `SQLiteStore`, and OCR/index
worker, cleanup worker, and outbox dispatcher modules contain no SQLite store
dependency.

## 4. Filesystem proof

The read-only inventory before/after the test and smoke runs found no newly
created SQLite file.  Existing files were retained unchanged, including:

* `data/sqlite/local_ai_core.db` (runtime legacy archive)
* three `data/sqlite/local_ai_core.pre_postgres_*.db` archives
* Phase-0 SQLite backup copies
* pre-existing `backend/tests/test_local_ai_core.db` and root `tests/` copy

The current primary archive has SHA-256
`10C4BE98120F12F8C38936F542F0E7173C2E1C91E37B7C495CC513229F48335D`.
No test outside the two migration-tool tests creates a SQLite database.

## 5. Legacy Qdrant inventory — no mutation

The read-only audit command:

```powershell
python -m scripts.inventory_legacy_qdrant `
  --output data/benchmarks/phase8a_legacy_qdrant_inventory.json
```

recorded **73 legacy** points and **7 versioned** points.  The JSON report
contains every point ID, document ID, legacy index version, chunk index,
content hash when present, PostgreSQL document/version/chunk mapping,
replacement point ID, and classification.

| Classification | Count | Action |
|---|---:|---|
| `VERIFIED_REPLACED` | 4 | Retain; eligible only for a later verified Phase-9 policy. |
| `UNKNOWN_DO_NOT_DELETE` | 69 | Retain; never infer orphan status. |

No Qdrant point was updated or deleted.

## 6. Commands and results

| Command/check | Actual result |
|---|---|
| targeted API/config guard tests | 15 passed |
| full `pytest backend/tests -q` with isolated `POSTGRES_TEST_URL` | 142 passed, 1 skipped, 0 failed |
| `docker compose config -q` | exit 0 |
| rebuild and start workers | exit 0; OCR/index/cleanup/outbox containers running |
| OCR worker smoke | exit 0; PostgreSQL, Redis, queue, task import OK |
| Index worker smoke | exit 0; PostgreSQL, Redis, queue, task import OK |
| cleanup worker dry-run | exit 0; zero eligible destructive candidate |
| FastAPI `/health` | HTTP 200; no `sqlite` component |

The sole skip is the optional validation-collection test and is not an active
runtime critical path.

## 7. Files changed

Core changes: `settings.py`, `main.py`, `operational_service.py`,
`routers/health.py`, `services/rag_service.py`,
`services/postgres_document_service.py`, `services/ocr_job_service.py`,
`routers/documents.py`, `routers/ocr.py`, `cleanup_worker.py`, Compose, and
`.env.example`.

Test changes: `conftest.py`, document/OCR/RAG/health/PostgreSQL tests, new
`test_postgres_runtime_guard.py`, and deletion of the two SQLite-only test
modules.  `scripts/inventory_legacy_qdrant.py` is a new read-only audit tool.
`migrate_document_storage.py` remains a legacy migration tool but now uses
direct `sqlite3`, not deleted runtime code.  The obsolete SQLite parity
benchmark was removed.

## 8. Blockers and Phase 8B checklist

Runtime is PostgreSQL-only, but the SQLite archive and migration/audit tools
remain intentionally.  Phase 8B must first decide retention/archive policy
for the listed `.db` files and preserve the two migration-test fixtures.
Phase 9 must establish a verified deletion policy for all 73 legacy Qdrant
points; 69 are explicitly unknown and must not be deleted based on this audit.
