# SQLite → PostgreSQL Phase 3B — auxiliary-domain migration verification

Date: 2026-07-18  
Status: **completed for the auxiliary-domain data copy and verification only**.
This is not a runtime cutover and does not complete the overall SQLite removal.

## Scope and safety boundary

Imported from the audited read-only source `data/sqlite/local_ai_core.db`:
`conversations`, `messages`, `memories`, `ocr_runs`, `request_logs`, and
`ocr_cache`. The tool opens that source with `mode=ro` and `PRAGMA query_only`.

Not imported: document tables/runs/chunks, BM25 data, legacy embedding cache,
or any `pre_postgres_*` archive. SQLite files were neither modified nor
deleted. Runtime services, repositories, API routes, and their SQLite runtime
paths were not switched in this phase.

## Tool hardening applied before migration

`backend/scripts/migrate_sqlite_to_postgres.py` now compares canonical business
fields per legacy primary key after every import. `ON CONFLICT DO NOTHING` is
therefore only accepted as idempotent when verification finds the target row
identical. Timestamp comparison normalizes both source and target to UTC;
`ocr_runs.result_json` compares as parsed JSON objects. A mismatch causes
`--verify-only` to exit non-zero.

Both PostgreSQL tables that receive explicit legacy integer IDs are reseeded:

* `messages`
* `request_logs`

The tool resolves the actual PostgreSQL identity sequence using
`pg_get_serial_sequence` and advances it with `setval` beyond the imported
maximum.

## Tier 1 — isolated validation database

Database: `local_ai_migration_validation` on the local PostgreSQL host. It was
recreated empty, upgraded with `alembic upgrade head` to `20260718_07`, and had
no auxiliary rows before import. A pre-import custom-format checkpoint was
created at:

`data/backups/postgres/phase3b-validation/local-ai-20260718-033531.dump`

Commands, each exit code `0`:

```powershell
$env:DATABASE_URL='<validation URL>'; python -m alembic -c alembic.ini upgrade head
python backend/scripts/backup_postgres.py --output-dir data/backups/postgres/phase3b-validation --docker-service postgres
python backend/scripts/migrate_sqlite_to_postgres.py --source data/sqlite/local_ai_core.db --domain all --apply --batch-size 100 --resume
python backend/scripts/migrate_sqlite_to_postgres.py --source data/sqlite/local_ai_core.db --domain all --verify-only
python backend/scripts/migrate_sqlite_to_postgres.py --source data/sqlite/local_ai_core.db --domain all --apply --batch-size 100 --resume
python backend/scripts/migrate_sqlite_to_postgres.py --source data/sqlite/local_ai_core.db --domain all --verify-only
```

| Domain | Source / target rows | First apply | Second apply | Verification |
|---|---:|---:|---:|---|
| conversations | 12 / 12 | 12 inserted | 12 existing-identical | IDs, UTC timestamps and checksum match |
| messages | 24 / 24 | 24 inserted | 24 existing-identical | IDs, FK, UTC timestamps and checksum match; 0 orphan |
| memories | 0 / 0 | 0 | 0 | valid empty domain |
| ocr_runs | 1 / 1 | 1 inserted | 1 existing-identical | IDs, UTC timestamps, JSONB and checksum match |
| request_logs | 19 / 19 | 19 inserted | 19 existing-identical | IDs and UTC timestamps match |
| ocr_cache | 0 / 0 | 0 | 0 | valid empty domain; no key fields invented |

All domains reported `failed=0`, `mismatch=0`, `invalid_json=0`; no embedding
cache row was copied. The checksums for conversations, messages and OCR runs
matched the Phase 3A source values.

An uncommitted identity check inserted trial runtime rows then rolled the
transaction back: `messages` maximum 24 produced 25; `request_logs` maximum
21 produced 22. No trial row was persisted.

## Tier 2 — approved current runtime PostgreSQL database

The project `.env` did not set `DATABASE_URL`. The approved local Compose
default documented in `.env.example` and `docker-compose.yml` was used for this
one migration execution: host `127.0.0.1`, database `local_ai_core`, Alembic
head after schema upgrade `20260718_07`. Credentials are intentionally omitted.

Before changing schema/data, the existing backup script created and checked the
non-empty custom-format backup:

`data/backups/postgres/phase3b-runtime/local-ai-20260718-033640.dump` (24,819 bytes)

The runtime database was at `20260717_04`; it was upgraded to
`20260718_07` after the backup. Auxiliary table counts before import were all
zero. No reset, truncate, or deletion was performed.

The same apply → verify → apply → verify command sequence as Tier 1 completed
with exit code `0` for every command. Counts and results were identical to the
Tier 1 table above. The second apply inserted zero records and reported:

* 12 existing-identical conversations
* 24 existing-identical messages
* 1 existing-identical OCR run
* 19 existing-identical request logs

The runtime identity probe was rolled back and produced message ID 25 after
maximum 24 and request-log ID 22 after maximum 21. This verifies both sequence
reseeds without leaving test rows.

## Tests and operational checks

| Command | Result |
|---|---|
| `pytest tests/test_sqlite_to_postgres_migration.py -q` | 7 passed, 0 failed, 1 existing Starlette deprecation warning |
| `pytest tests/test_auxiliary_postgres_schema.py tests/test_sqlite_to_postgres_migration.py -q` | 8 passed, 0 failed, 1 warning |
| `pytest tests -q` final regression | 104 passed, 0 failed, 1 warning |
| `docker compose config -q` | exit 0; Compose warns that local `.env` does not set `DATABASE_URL` |
| FastAPI `TestClient` lifespan smoke, `GET /health` | exit 0; HTTP 200, status `ok` |

The new migration-tool tests cover explicit message and request-log identity
inserts/reseeding, empty domains, JSON validation, orphan detection, batch
rollback, idempotency, unavailable PostgreSQL, and a same-primary-key content
mismatch which causes `--verify-only` to return non-zero.

## Files changed in Phase 3B

* `backend/scripts/migrate_sqlite_to_postgres.py` — canonical per-row verify,
  mismatch reporting/failure, UTC normalization, and identity reseeding for
  messages plus request logs.
* `backend/scripts/backup_postgres.py` — uses host `pg_dump` when available or
  the existing Compose PostgreSQL container when explicitly requested; validates
  that the resulting backup is non-empty.
* `backend/tests/test_sqlite_to_postgres_migration.py` — request-log reseed and
  conflicting-ID/verify-exit tests.
* `docs/sqlite_to_postgres_phase3b_verification.md` — this verification report.

## Remaining risks and conditions before runtime cutover

1. Auxiliary runtime consumers still read/write SQLite; this phase only copied
   and verified data. No dual-write is enabled.
2. Document legacy migration, embedding-cache rebuild, BM25/cleanup handling,
   and the archive/deletion of SQLite are explicitly deferred.
3. Add an explicit production `DATABASE_URL` before container/runtime cutover;
   the current local `.env` omission is a configuration risk despite the
   documented Compose default used for this controlled local migration.
4. Before starting runtime cutover, implement PostgreSQL repositories per
   domain, migrate their tests, verify service/API behavior against PostgreSQL,
   and retain the recorded SQLite and PostgreSQL backups for rollback.
