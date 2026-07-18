# Phase 7C — PostgreSQL cleanup cutover

Date: 2026-07-18.

## Runtime state

Cleanup now uses PostgreSQL with the local, ignored selector
`CLEANUP_DATABASE_BACKEND=postgres`. The existing auxiliary, document,
retrieval, and embedding-cache backends remain PostgreSQL. The selector accepts
only `sqlite` or `postgres`, fails fast otherwise, and changes no other
backend. It remains until Phase 8.

No SQLite database, migration/audit tool, migration fixture, or legacy Qdrant
point was deleted in this phase.

## Retention policy executed

| Domain | Policy | Rule |
|---|---:|---|
| Request logs | 7 days | PostgreSQL rows strictly older than the cutoff are deleted in a short transaction. |
| OCR runs | 14 days | Only non-active PostgreSQL runs are eligible; filesystem removal is outside the transaction. |
| Superseded versions | 7-day grace | Must be non-active, unreferenced, and not busy. |
| Temporary sources | 0 days | Disabled; no source candidate is executed. |
| Inactive ingestion/cache | no PostgreSQL policy | Disabled. |

## Runtime wiring and executor

`app/main.py:lifespan` now constructs legacy `CleanupService` and its SQLite
startup/periodic task only when the cleanup selector is `sqlite`. In PostgreSQL
mode it does neither. `scripts.cleanup_worker` requires PostgreSQL for normal
`--once` or `--loop` execution and initializes `PostgresCleanupService`, not
`SQLiteStore`.

`PostgresCleanupService` executes:

```text
query candidate → lock/re-read/revalidate → deterministic Job claim
→ commit → Qdrant/filesystem side effect → short finalization transaction
```

It revalidates pinned/active-version/job/outbox/retention/source-path and
lifecycle guards immediately before side effects. Claims use a deterministic
key, row locking, and a lease. Qdrant deletion is limited to `version_id` or
`document_id`, never legacy `index_version`. Missing file or point is
idempotent success; Qdrant/filesystem failure creates a recoverable retry.

`create_document_delete_job` no longer creates an invalid generic RQ outbox
event; delete lifecycle remains owned by the cleanup worker.

## Backup and production dry-run

* PostgreSQL backup: `data/backups/postgres-phase7c/local-ai-20260718-210327.dump` (non-empty).
* Qdrant snapshot: `documents-7079489509187321-2026-07-18-14-03-58.snapshot`.
* Preflight found no dangerous OCR/index/delete job.
* The post-cutover production dry-run produced only blocked legacy-Qdrant inventory candidates and performed no destructive operation.

## Fixture destructive coverage

`test_postgres_cleanup_lifecycle.py` covers due/new logs and OCR runs, due
superseded version cleanup, active/pinned/busy/outbox guards, source cleanup,
source-less protection, missing artifacts, Qdrant retry/idempotency, document
delete, and competing executor claims. `test_document_backend_selectors.py`
proves that PostgreSQL cleanup selection does not construct `CleanupService`.

## SQLite no-runtime proof

The selector isolation test passes with all main backends PostgreSQL. Cleanup
plans/execution use PostgreSQL models only. SQLite cleanup-related counts did
not change across cutover: documents 3, ingestion runs 2, chunks 4, request
logs 19, OCR runs 1, embedding cache 5. Explicit migration/audit CLIs retain
intentional read-only SQLite access but are not runtime processes.

## Legacy Qdrant points deferred

No legacy `index_version` point was deleted or updated. The saved Phase 7B
inventory contains 67 point IDs and all 67 remain. Current production
inventory is 73 legacy and 7 versioned points (80 total), including legacy
IDs absent from that saved inventory. This is inventory drift, not a cleanup
failure; every legacy candidate remains blocked by
`DEFER_LEGACY_QDRANT_CLEANUP`. The earlier plan said 68 while the persisted
Phase 7B dry-run held 67; a verified mapping/disposition is required before
any later legacy-point deletion.

## Commands and results

| Check | Result |
|---|---|
| `alembic upgrade head` against isolated PostgreSQL test DB | exit 0 |
| cleanup planner/lifecycle/selector tests | 18 passed, 1 warning |
| `pytest backend/tests -q` with isolated `POSTGRES_TEST_URL` | 150 passed, 1 skipped, 1 warning |
| `docker compose config -q` | exit 0 |
| cleanup worker dry-run container | exit 0 |
| OCR worker smoke container | exit 0 |
| Index worker smoke container | exit 0 |
| FastAPI `/health` | HTTP 200 |

The one skip is an optional validation-collection path, not active cleanup,
document, or retrieval behavior.

## Files changed

* `.env.example`, `backend/app/config/settings.py`, `backend/app/main.py`.
* `backend/app/postgres/repositories.py`.
* `backend/app/services/postgres_cleanup_service.py`.
* `backend/scripts/cleanup_worker.py`, `docker-compose.yml`.
* `backend/tests/test_document_backend_selectors.py` and
  `backend/tests/test_postgres_cleanup_lifecycle.py`.

## Rollback and next condition

Rollback was not used. No production entity was destructively cleaned during
cutover. After PostgreSQL cleanup has deleted production data, do not
automatically switch back to SQLite; stop writers and roll forward or use a
controlled recovery plan.

Phase 8 requires preserving migration/audit fixtures, recording a verified
mapping for all current 73 legacy Qdrant points, and confirming no deployed
process selects SQLite cleanup.
