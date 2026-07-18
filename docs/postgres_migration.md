# PostgreSQL Foundation Migration

## Scope and safety boundary

Phase 1 introduces PostgreSQL schema, Alembic migrations, and a one-way copy
tool.  The running application still reads and writes SQLite in this phase.
`DATABASE_URL` is intentionally not wired into the FastAPI runtime yet.  This
allows PostgreSQL to be checked independently without changing production
behaviour or deleting any current documents.

The SQLite source database is never deleted by this procedure.  The execute
step also creates a timestamped `*.pre_postgres_*.db` copy alongside it.

## Start the local PostgreSQL container

1. Set a non-placeholder `POSTGRES_PASSWORD` and matching `DATABASE_URL` in
   the local `.env` file.  Do not commit `.env`.
2. Start only the opt-in PostgreSQL profile:

   ```powershell
   docker compose --profile postgres up -d postgres
   ```

3. Apply the schema before any migration:

   ```powershell
   $env:DATABASE_URL = 'postgresql+psycopg://local_ai:YOUR_PASSWORD@127.0.0.1:5432/local_ai_core'
   .\.venv\Scripts\python.exe -m alembic -c alembic.ini upgrade head
   ```

`alembic upgrade head --sql` can be used without `DATABASE_URL` to inspect the
PostgreSQL DDL; it does not contact a server.

## Copy and verify SQLite data

Run these commands from the repository root, in order:

```powershell
.\.venv\Scripts\python.exe backend\scripts\migrate_sqlite_to_postgres.py --dry-run
.\.venv\Scripts\python.exe backend\scripts\migrate_sqlite_to_postgres.py --execute --database-url $env:DATABASE_URL
.\.venv\Scripts\python.exe backend\scripts\migrate_sqlite_to_postgres.py --verify --database-url $env:DATABASE_URL
```

The migration preserves document IDs and derives deterministic chunk IDs from
document ID, index version, and chunk index.  Re-running it is safe: existing
document, version, run, and chunk identifiers are checked before insert.

For safety, all copied document versions are `staging`; documents that were
`indexed` in SQLite are copied as `uploaded`.  The migration does **not** mark
them active because Phase 1 has not yet reconciled the matching Qdrant vector
set.  SQLite remains the live source until a later cutover phase validates
that mapping.

SQLite has no normalized page table, so historical page-level native/OCR text
cannot be reconstructed in this phase.  Historical chunks retain their
available page, section, block, extraction, and content metadata.

## Rollback and recovery

If dry-run, schema creation, copy, or verification fails, leave the FastAPI
application on SQLite and do not perform a cutover.  The source database and
the automatically-created backup remain intact.  In a disposable development
PostgreSQL instance only, remove the Phase 1 schema with:

```powershell
.\.venv\Scripts\python.exe -m alembic -c alembic.ini downgrade base
```

Do not run this downgrade against a PostgreSQL database that contains data you
need to keep.

## Phase 2 runtime cutover

After the copy verification and `alembic upgrade head` (now including revision
`20260717_02`) succeed, enable only the document pipeline with:

```env
DOCUMENT_DATABASE_BACKEND=postgres
DATABASE_URL=postgresql+psycopg://local_ai:YOUR_PASSWORD@127.0.0.1:5432/local_ai_core
```

Restart FastAPI. Conversations, memory, request logs, OCR-run console metadata,
and caches remain in SQLite in Phase 2. To roll document runtime back, set
`DOCUMENT_DATABASE_BACKEND=sqlite` and restart. Do not run both backends as a
dual-write system; data created while PostgreSQL is active is intentionally not
copied back to SQLite.
