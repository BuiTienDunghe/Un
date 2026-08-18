# Phase 8B — PostgreSQL-only runtime acceptance and SQLite archive

Date: 2026-07-19

## Scope and safety boundary

This phase accepted the PostgreSQL-only runtime and retired the runtime SQLite
location.  It did **not** delete, update, or otherwise mutate legacy Qdrant
points.  SQLite remains available only as a controlled archive and through
explicit migration/audit CLIs.

## Pre-archive inventory and decisions

Source search confirmed that normal runtime code no longer consumes database
files.  The explicit consumers are `backend/scripts/audit_sqlite_readonly.py`,
`backend/scripts/migrate_sqlite_to_postgres.py`,
`backend/scripts/migrate_sqlite_documents_to_postgres.py`, and migration-only
tests that create temporary SQLite fixtures.  No normal test referred to
`tests/test_local_ai_core.db` or `backend/tests/test_local_ai_core.db`.

| Original file | Size | SHA-256 | Decision |
| --- | ---: | --- | --- |
| `data/sqlite/local_ai_core.db` | 192,512 | `10C4BE98120F12F8C38936F542F0E7173C2E1C91E37B7C495CC513229F48335D` | `ARCHIVE_REQUIRED` |
| `data/sqlite/local_ai_core.pre_postgres_20260716T175939Z.db` | 176,128 | `13FB9F81C81A5E2A721A414BDE28547B0B956F76CC7D917FDEC847DA41C5287C` | `ARCHIVE_REQUIRED` |
| `data/sqlite/local_ai_core.pre_postgres_20260716T180021Z.db` | 176,128 | same as above | `ARCHIVE_REQUIRED` |
| `data/sqlite/local_ai_core.pre_postgres_20260716T180024Z.db` | 176,128 | same as above | `ARCHIVE_REQUIRED` |
| `tests/test_local_ai_core.db` | test artifact | n/a | `DELETE_TEST_ARTIFACT` |
| `backend/tests/test_local_ai_core.db` | test artifact | n/a | `DELETE_TEST_ARTIFACT` |
| `data/backups/sqlite-phase0-20260718T030117Z/sqlite/*.db` | stable Phase-0 backup | retained in place | `KEEP_EXPLICIT_FIXTURE` |

The two test artifacts were removed only after confirming no source consumer.
Migration fixtures still use a temporary directory and are deliberately kept.

## PostgreSQL backup and restore drill

Backup command (exit code 0):

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m scripts.backup_postgres `
  --output-dir data\backups\postgres-phase8b --docker-service postgres
```

Backup: `data/backups/postgres-phase8b/local-ai-20260719-001749.dump`
(53,342 bytes; non-empty).  It was restored into the isolated database
`local_ai_phase8b_restore_validation`, never over the runtime database.

The runtime database was `local_ai_core`; the restored validation database was
`local_ai_phase8b_restore_validation`. Both were at Alembic revision
`20260718_09`.  Canonical summary checksum matched:
`c8f12ff5ba0a7225f19f9f97578533d385839b843df600ecae2302c744dfa1ac`.

| Table / summary | Runtime | Restored |
| --- | ---: | ---: |
| documents | 15 | 15 |
| document_versions | 15 | 15 |
| ingestion_runs | 15 | 15 |
| document_chunks | 9 | 9 |
| conversations | 30 | 30 |
| messages | 60 | 60 |
| ocr_runs | 18 | 18 |
| request_logs | 156 | 156 |
| jobs | 1 | 1 |
| outbox_events | 28 | 28 |
| deleted documents / pending-version cleanup | 1 / 0 | 1 / 0 |

Repository read validation against the restored database returned 6 active
versions and 30 readable conversations.  No worker wrote to the restored
database.

## Qdrant protection

A production collection snapshot was created with a 120-second client timeout
after the default short timeout timed out:

```text
collection: documents
snapshot: documents-7079489509187321-2026-07-18-17-19-14.snapshot
```

The post-smoke read-only inventory contains 73 legacy points and 8 versioned
points.  The additional versioned point was produced by the controlled Phase
8B document smoke; it is not a legacy-point mutation.  The legacy inventory
is unchanged: 4 `VERIFIED_REPLACED`, 69 `UNKNOWN_DO_NOT_DELETE`.  No legacy
point was deleted or updated.

## Archive

The four required files were copied, then SHA-256-verified before the original
runtime copies were removed.  Archive root:

```text
data/archives/sqlite-retired-20260719T002000Z/
```

It contains `manifest.json` and `README.md`; every before/after checksum in
the manifest was revalidated.  The manifest links the PostgreSQL backup above,
labels the pre-PostgreSQL snapshots as never-merge archives, and sets the
earliest permanent-deletion review date to 2027-07-19.  `data/archives/` is
ignored by Git.  `data/sqlite/` now contains only a redirect README, not a
runtime database.

Explicit archive-tool checks passed (exit code 0):

```powershell
python -m scripts.audit_sqlite_readonly <archive> 
python -m scripts.migrate_sqlite_to_postgres --source <archive> --domain memories --dry-run
python -m scripts.migrate_sqlite_documents_to_postgres --source <archive> --dry-run --qdrant-mode none
```

The tools accepted the explicit archive path.  The audit reported the expected
legacy tables, including 3 documents, 2 ingestion runs, 4 versioned chunks,
12 conversations, 24 messages, 1 OCR run, and 19 request logs.  They remain
explicit maintenance tools and are not imported by runtime processes.

## PostgreSQL-only runtime evidence

With `data/sqlite/local_ai_core.db` absent, a controlled Markdown upload was
indexed through PostgreSQL/RQ/Qdrant and then requested for lifecycle deletion:

```text
document: doc_2d032f2296ab49ac98fea8757eb70c29
run:      ing_8c9b49a9c6984635bbc61b6d9faace76
ingestion status: completed
health HTTP status: 200
delete HTTP status: 204
```

Container smoke checks all exited 0:

| Process | Queue / result |
| --- | --- |
| OCR worker | `local-ai:dev:ocr`; PostgreSQL, Redis and task import all `ok` |
| Index worker | `local-ai:dev:index`; PostgreSQL, Redis and task import all `ok` |
| Cleanup worker | PostgreSQL dry-run; zero eligible destructive candidates |
| Outbox dispatcher | completed one pass, published 0 pending events |

`/health` returned HTTP 200 and reported PostgreSQL, Redis, Qdrant, Ollama,
OCR worker, index worker, and cleanup worker as healthy.  The dispatcher was
reported `pending` because it had no recent heartbeat, not because it failed.
No SQLite database file was created during the smoke or regression run.

## Verification commands

| Command | Exit | Result |
| --- | ---: | --- |
| `alembic upgrade head` on fresh `local_ai_core_test` | 0 | migration completed |
| `pytest backend/tests -q` with isolated `POSTGRES_TEST_URL` | 0 | 142 passed, 1 skipped, 1 Starlette/httpx deprecation warning |
| `docker compose config -q` | 0 | valid Compose configuration |
| worker/cleanup/outbox container smoke commands | 0 | all completed as described above |

The initial regression invocation was rejected as a test-configuration error:
`POSTGRES_TEST_URL` had been pointed at the runtime database.  No failure was
attributed to runtime code.  A dedicated `local_ai_core_test` database was
created, migrated, and used for the passing run; known migration-test fixture
rows were removed from the runtime database before the isolated rerun.

## Recovery procedure

1. Keep the PostgreSQL backup and Qdrant snapshot intact.
2. If an audit or migration is required, pass the archive database path
   explicitly to the appropriate CLI; do not copy it back into `data/sqlite/`
   for runtime use.
3. Restore PostgreSQL only into a separate validation database first.
4. Do not merge any `pre_postgres_*` files.

## Remaining blocker before Phase 9

Phase 9 must use a separately approved mapping/deletion policy for the 69
`UNKNOWN_DO_NOT_DELETE` legacy Qdrant points.  They are not proven orphaned.
Phase 8B performed no Qdrant garbage collection.
