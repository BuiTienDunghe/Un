# Phase 7B — PostgreSQL cleanup preparation (dry-run only)

Date: 2026-07-18.  This phase does not change the cleanup runtime selector and
does not invoke any cleanup executor.  The active selectors remain:

```text
AUXILIARY_DATABASE_BACKEND=postgres
DOCUMENT_DATABASE_BACKEND=postgres
RETRIEVAL_DATABASE_BACKEND=postgres
```

## Cleanup consumer audit

| Operation | Actual implementation | Data source / current side effect | Retention / guard | Classification |
|---|---|---|---|---|
| Startup + scheduled cleanup | `app/main.py:lifespan`, `CleanupService.run_all` | SQLite store, filesystem, legacy Qdrant | Config values below | `REMOVE_OBSOLETE_SQLITE_CLEANUP` in 7C; unchanged in 7B |
| Temporary source cleanup | `CleanupService.cleanup_expired_documents` | SQLite `get_expired_temporary_sources`, deletes folder/flat file, marks source unavailable | temporary + unpinned; legacy service does not understand PG active version/outbox | `IMPLEMENT_POSTGRES` |
| OCR run cleanup | `CleanupService.cleanup_expired_ocr_runs` | SQLite `ocr_runs`, deletes run folder and SQLite row | 14 days | `KEEP_POSTGRES`; new runtime OCR runs are PostgreSQL |
| Request log cleanup | `CleanupService.cleanup_expired_logs` | SQLite `request_logs` delete | 7 days configured | `KEEP_POSTGRES`; SQLite historical rows are archive only |
| Legacy inactive ingestion | `CleanupService.cleanup_expired_inactive_ingestions` | SQLite runs/chunks plus Qdrant `index_version` delete | 7 days | `REMOVE_OBSOLETE_SQLITE_CLEANUP`; unsafe for PG versioned data |
| PostgreSQL superseded version cleanup | `PostgresCleanupService.cleanup_superseded` | Deletes Qdrant version points, PG pages/chunks, marks version deleted | 7-day grace and no busy job | `IMPLEMENT_POSTGRES` executor must be replaced by revalidated 7C execution |
| PostgreSQL deleting document cleanup | `PostgresCleanupService.cleanup_deleting_documents` | Deletes Qdrant document points and source folder, then PG rows/state | `documents.status=deleting` | `IMPLEMENT_POSTGRES` executor must revalidate guard/claim |
| Cleanup process | `scripts.cleanup_worker`, Compose `cleanup-worker` | currently invokes `PostgresCleanupService` for normal `--once/--loop` | no selector; PostgreSQL/Qdrant | `KEEP_POSTGRES` for its new `--dry-run` mode; do not run apply in 7B |
| Delete lifecycle request | `PostgresDocumentService.delete_document`, `PostgresDocumentRepository.create_document_delete_job` | PG document `deleting` + durable `delete_document` job/outbox | retrieval immediately excludes deleting doc | `KEEP_POSTGRES` |
| Outbox/reconciliation | `OutboxDispatcherService`, `JobRecoveryService` | PostgreSQL jobs/outbox + Redis transport | pending/busy job is a planner guard | `KEEP_POSTGRES` |
| Embedding cache | `PostgresEmbeddingCacheStore` | PostgreSQL only after 7A | no expiry policy/table field exists | `ARCHIVE_ONLY` until explicit cache TTL policy |
| Legacy Qdrant points | `QdrantStore`, collection `documents` | read-only inventory in 7B | payload only has `index_version` | `DEFER_LEGACY_QDRANT_CLEANUP` |

The planner and CLI do not import `SQLiteStore`.  `CleanupService` remains the
only runtime SQLite cleanup consumer and is deliberately untouched until
cutover.  Migration/audit tools retain read-only SQLite access by design.

## Retention policy actually configured

`app/config/models.yaml:storage` currently declares:

| Policy | Actual value | Phase 7B action |
|---|---:|---|
| temporary sources | `0` days | disabled; planner reports a blocking guard |
| OCR runs | `14` days | PostgreSQL candidate cutoff |
| request logs | `7` days | PostgreSQL candidate cutoff |
| inactive ingestion | `7` days | legacy-only; no PG planner deletion based on it |
| superseded versions | `7` days | PostgreSQL candidate cutoff |

The Phase-2 schema design mentioned a possible 90-day request-log retention,
but the runtime configuration is **7 days**.  Phase 7C must explicitly confirm
the product policy before enabling deletion; this phase preserves the observed
configuration and deletes nothing.

## Planner model and safety guards

`app/services/postgres_cleanup_planner.py` adds the read-only pipeline:

```text
PostgreSQL read query
→ CleanupCandidate
→ blocking-guard evaluation
→ JSON dry-run report
→ (Phase 7C only) fresh claim/revalidation/executor
```

Every `CleanupCandidate` has an operation/entity identity, reason, cutoff,
document/version/run/job context, expected PG rows, expected Qdrant count,
expected filesystem path, blocking guards and deterministic idempotency key.

Guards prevent a candidate from being eligible when it is an active version,
has an active version, is indexed/processing/deleting/deleted, pinned,
source-less, has a queued/running/retrying/cancel-requested job, has a busy
ingestion run, or has a pending outbox event.  A superseded version must have
`superseded_at` older than grace and must not equal `active_version_id`.

Source cleanup is deliberately more conservative than legacy cleanup: it never
selects the source of an active/indexed document, never treats a source-less
metadata document as an orphan, and is blocked entirely while temporary source
TTL is disabled.

The planner has no database mutations, filesystem calls, Redis calls, Qdrant
delete calls, timestamp touches, or model calls.  Phase 7C must claim/mark in
a short PostgreSQL transaction; commit; delete Qdrant/filesystem outside the
transaction; then finalize in a second short transaction.  It must re-read all
guards immediately before each external action, not trust an old dry-run.

## Dry-run CLI

```powershell
cd backend
..\.venv\Scripts\python.exe -m scripts.cleanup_worker --dry-run --domain all --limit 100
```

Supported options are `--dry-run`, `--domain`
(`all|documents|versions|sources|logs|ocr-runs|caches|legacy-qdrant`),
`--limit`, `--as-of <ISO-8601 timestamp>`, and `--document-id`.
The command emits one structured JSON object with candidate, eligible and
blocked counts.  `--dry-run` is the only Phase 7B command used operationally.
Normal `--once`/`--loop` remains an existing executor and was not run.

## Runtime dry-run result and zero-side-effect evidence

The current runtime command produced:

```text
candidate_count=68
eligible_count=0
blocked_count=68
inventory_legacy_qdrant_point=68
```

All 68 candidates are legacy Qdrant inventory records.  They are marked
`DEFER_LEGACY_QDRANT_CLEANUP`; no production point was called orphan merely
because active PostgreSQL retrieval ignores it.  A verified replacement is
only recognized when document ID, legacy version number, chunk index **and**
payload content hash match a PostgreSQL version/chunk tuple.

A separate before/after dry-run comparison was identical:

| Store/table | Before | After |
|---|---:|---:|
| PostgreSQL documents / versions / chunks / pages | 14 / 13 / 8 / 4 | 14 / 13 / 8 / 4 |
| PostgreSQL jobs / outbox | 1 / 28 | 1 / 28 |
| PostgreSQL request logs / OCR runs / embedding cache | 154 / 18 / 0 | 154 / 18 / 0 |
| SQLite documents / request logs | 3 / 19 | 3 / 19 |
| Qdrant document points | 74 | 74 |

This demonstrates the dry-run did not change PostgreSQL, SQLite, Qdrant,
filesystem, Redis jobs or outbox events.  No active document/version/chunk,
source-less document, or smoke document was selected.  No pending job/outbox
was selected as a deletion target.

## Failure and idempotency design for Phase 7C

| Failure or race | 7C required behavior |
|---|---|
| Qdrant unavailable | retain PG lifecycle candidate, set durable delete job retrying; do not finalize |
| Missing Qdrant point or source path | treat that individual external deletion as idempotent success after guard revalidation |
| PG row already deleted | no-op success; never recreate metadata |
| Qdrant succeeds, filesystem fails | durable job stays retrying; version/document remains non-active/deleting |
| filesystem succeeds, PG finalize fails | retry finalization only; paths remain absent and are idempotent |
| worker crash | stale job recovery/reconciliation chooses a durable job; no stale dry-run list is executed blindly |
| job/outbox changes after planning | executor revalidates and refuses candidate when busy/pending |
| version becomes active or document becomes pinned | executor rejects before Qdrant/filesystem action |

## Tests

`tests/test_postgres_cleanup_planner.py` covers dry-run zero side effects,
active/pinned/busy guards, grace-period behavior, source-less safety,
PostgreSQL request-log/OCR-run retention candidates, legacy-Qdrant inventory
only, and absence of `SQLiteStore` from the dry-run worker module.

Commands run:

| Command | Result |
|---|---|
| `pytest test_postgres_cleanup_planner.py test_postgres_cleanup_lifecycle.py -q` | 10 passed |
| cleanup/outbox/reconciliation/cache focus suite | 27 passed |
| full `pytest backend/tests -q` with isolated `POSTGRES_TEST_URL` | 145 passed, 1 skipped, 1 warning |
| `docker compose config -q` | exit 0 |
| `GET /health` | HTTP 200 |
| `docker compose --profile workers run --rm cleanup-worker ... --dry-run` | exit 0; 68 blocked inventory candidates |
| runtime dry-run twice plus before/after database/Qdrant snapshots | exit 0; identical snapshots |

## Files changed

* `app/services/postgres_cleanup_planner.py` — read-only candidate planner.
* `scripts/cleanup_worker.py` — structured `--dry-run` CLI; existing executor
  remains available but was not run.
* `tests/test_postgres_cleanup_planner.py` — planner and no-SQLite dependency
  tests.

## Phase 7C checklist

1. Resolve and record request-log retention policy (7 versus 90 days).
2. Freeze cleanup writers and disable the SQLite startup/scheduled cleanup path
   only inside the approved cutover window.
3. Backup PostgreSQL and snapshot Qdrant; record legacy-point inventory.
4. Replace direct `PostgresCleanupService` deletion with durable, atomic
   claim/revalidation/finalization logic.
5. Revalidate document/version/job/run/outbox/pin/source guards before every
   Qdrant or filesystem action.
6. Enable PostgreSQL executor in a controlled smoke environment; verify retry
   and idempotency without touching unrelated legacy points.
7. Only then stop duplicate SQLite cleanup for PostgreSQL-owned OCR runs and
   request logs.  Keep historical SQLite data/archive and all migration tools.
8. Handle legacy Qdrant points in a separately approved mapping-based batch;
   do not bulk delete them merely because retrieval ignores them.
