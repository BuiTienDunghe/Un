# SQLite → PostgreSQL Phase 4B — auxiliary runtime cutover

Date: 2026-07-18  
Status: **COMPLETE for the six auxiliary runtime domains only**.

This cutover covers conversations, messages, memory metadata, OCR runs,
request logs and OCR cache. It does not remove SQLite or cut over document
legacy, BM25/retrieval legacy, cleanup legacy or embedding cache.

## 1. Preflight and configuration

The operator approved the local Docker Compose PostgreSQL database
`local_ai_core` as runtime target. The running PostgreSQL container's actual
user, password and database values were compared with resolved Compose defaults
without printing the password; all matched. `.env` is ignored by Git
(`.gitignore:34`) and was updated locally only with:

* a host `DATABASE_URL` using `127.0.0.1`;
* a container `CONTAINER_DATABASE_URL` using `postgres`; and
* `AUXILIARY_DATABASE_BACKEND=sqlite` during preflight/final migration.

Both URLs were tested without exposing credentials: host process connected to
database `local_ai_core`; an application container connected through hostname
`postgres`; both reached the same database. The observed Alembic head was
`20260718_07`; selector was `sqlite` before cutover.

The actual OCR model configuration has no verified `revision`. PostgreSQL OCR
cache therefore remains intentionally disabled for this model: every lookup is
a safe miss and no speculative cache key is stored. This has a performance cost
only; it does not affect OCR correctness.

## 2. Freeze

Before final migration, process inspection found no running local FastAPI/
Uvicorn process and no OCR/index worker container. PostgreSQL, Redis and Qdrant
were left running. Thus no process could write the six auxiliary SQLite tables
during the final migration window.

## 3. Backup, final delta migration and verification

A fresh, non-empty PostgreSQL custom-format backup was created before final
migration:

`data/backups/postgres/phase4b-runtime/local-ai-20260718-040651.dump`

Size: 40,409 bytes. Existing Phase 0 and Phase 3B backups were not changed.

Commands completed with exit code 0, while the selector was still `sqlite`:

```powershell
python backend/scripts/migrate_sqlite_to_postgres.py --source data/sqlite/local_ai_core.db --domain all --apply --batch-size 100 --resume
python backend/scripts/migrate_sqlite_to_postgres.py --source data/sqlite/local_ai_core.db --domain all --verify-only
# Repeat apply and verify for idempotency.
```

Both applies inserted zero rows and reported only existing-identical records:
12 conversations, 24 messages, 1 OCR run and 19 request logs. Both verification
runs reported zero mismatch, orphan messages, invalid JSON and failures.
Counts, UTC timestamps, foreign keys and canonical checksums for conversations,
messages and OCR runs matched. No OCR cache or embedding-cache legacy record was
copied.

## 4. Selector cutover and startup

After final verification, local `.env` changed to:

```text
AUXILIARY_DATABASE_BACKEND=postgres
```

The API was restarted. OCR and index worker containers were started/restarted
with Compose, which supplies `CONTAINER_DATABASE_URL`. Worker logs confirm they
listen on `local-ai:dev:ocr` and `local-ai:dev:index`.

One direct cutover defect was found by regression and fixed: merely creating a
PostgreSQL auxiliary session had selected `PostgresRetrievalService`. That would
have changed deferred document/RAG behavior. `main.py` now selects PostgreSQL
retrieval only when `DOCUMENT_DATABASE_BACKEND=postgres`; auxiliary cutover no
longer affects SQLite document retrieval.

## 5. Smoke tests and PostgreSQL evidence

| Domain | Smoke result |
|---|---|
| Chat/conversations | Two `POST /chat` calls returned 200 for one new conversation. `GET /conversations/{id}` returned four messages in chronological order; list contained it. `DELETE /conversations/{id}` returned 204; PostgreSQL confirmed conversation deletion and message FK cascade. |
| Memory metadata + Qdrant | `POST /memory/add` returned 201; update returned the changed content; delete returned 204. PostgreSQL memory row was removed after delete. |
| OCR runs | A named OCR run with an unknown nested JSON field was persisted through the PostgreSQL adapter and appeared in `GET /api/ocr/history`; JSON field was preserved. |
| Request logs | A named smoke log was inserted in PostgreSQL; chat and memory smoke operations also created request logs through the selected adapter. |
| OCR cache | No actual model revision is configured, so cache read/write correctly remained a safe miss; PostgreSQL cache count remained 0. |
| Health | `GET /health` returned 200 with SQLite, PostgreSQL, Redis, Qdrant, Ollama, OCR worker, index worker and outbox dispatcher all `ok`. |
| Worker startup | `python -m scripts.worker_smoke --role ocr` and `--role index` inside their containers each confirmed task import, PostgreSQL, Redis and expected queue. |

The memory smoke exposed an existing Qdrant incompatibility: public memory IDs
use `mem_...`, while Qdrant accepts UUID/integer point IDs. `QdrantStore` now
uses a deterministic UUID5 only for the internal point ID, retains the original
`memory_id` in payload, and derives the same ID for delete. The public API and
metadata contract are unchanged.

Post-smoke PostgreSQL evidence:

```text
conversations=12, messages=24, memories=0,
ocr_runs=2, request_logs=25, ocr_cache=0
```

The conversation and memory test records were deleted as part of their smoke
flows. The identifiable OCR-run and request-log evidence remains in PostgreSQL.

## 6. SQLite no-write proof

Before cutover, SQLite auxiliary counts were:

```text
conversations=12, messages=24, memories=0,
ocr_runs=1, request_logs=19, ocr_cache=0
```

After all PostgreSQL smoke writes, the exact same six SQLite counts remained.
The SQLite source file was 176,128 bytes with SHA-256
`EF3E0AB31A2E00A6C2C21E6C43BC566AAB4493992B074A0EA0FF59412EC1C764`
before cutover. This per-table comparison, rather than database file mtime,
proves that the six auxiliary domains stopped writing SQLite. Other legacy
document/BM25/cleanup paths may still access SQLite by design.

## 7. Regression and operational commands

| Command | Result |
|---|---|
| Auxiliary/migration/schema/API/worker subset | 26 passed, 0 failed, 1 existing Starlette warning |
| `pytest tests -q` | 111 passed, 0 failed, 1 warning |
| `docker compose config -q` | exit 0 |
| API lifespan + `/health` | exit 0; HTTP 200 |
| OCR worker smoke in container | exit 0; PostgreSQL/Redis/task import/queue confirmed |
| Index worker smoke in container | exit 0; PostgreSQL/Redis/task import/queue confirmed |

## 8. Files changed in this phase

* Local ignored `.env` — actual runtime URLs and PostgreSQL auxiliary selector;
  not committed.
* `backend/app/main.py` — isolate document retrieval selector from auxiliary
  selector.
* `backend/app/stores/qdrant_store.py` — deterministic valid point key for the
  existing opaque memory-ID contract.
* `docs/sqlite_to_postgres_phase4b_cutover.md` — this report.

## 9. Rollback

Rollback was not used. PostgreSQL accepted new auxiliary writes after cutover,
so automatic rollback to SQLite is no longer safe. Continue with PostgreSQL as
the source for these six domains; if rollback becomes unavoidable, stop writers
and prepare an explicit reverse migration rather than silently abandoning new
PostgreSQL data.

## 10. Remaining SQLite consumers and next conditions

SQLite remains intentionally in use by document legacy, document ingestion/
version/chunk legacy, BM25, legacy retrieval, cleanup metadata, document worker
embedding cache and their scripts/tests. No SQLite file, backup or temporary
selector was removed.

Before starting document/BM25/cleanup migration, retain the current backups,
confirm sustained PostgreSQL auxiliary writes in normal use, decide whether to
configure a real OCR model revision for cache performance, and create a
separate audited migration/cutover plan for each remaining legacy domain.
