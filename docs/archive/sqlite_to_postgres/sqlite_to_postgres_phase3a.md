# SQLite → PostgreSQL Phase 3A — migration tool

`backend/scripts/migrate_sqlite_to_postgres.py` supports only the auxiliary
domains: `conversations`, `messages`, `memories`, `ocr_runs`, `request_logs`,
and `ocr_cache`. Documents, ingestion runs, chunks, BM25 and embedding cache
are deliberately excluded.

## Safety boundaries

- CLI accepts only `data/sqlite/local_ai_core.db`; test and `pre_postgres_*`
  paths are rejected.
- SQLite uses `file:...?...mode=ro` plus `PRAGMA query_only=ON`.
- `--dry-run` never creates a PostgreSQL engine/session and cannot write it.
- Each domain batch is one PostgreSQL transaction. A failed batch rolls back;
  reports contain identifiers/reasons only, never message/memory/OCR content.
- `ocr_cache` legacy rows are skipped: old rows lack engine, model revision and
  config fingerprint. No key component is guessed.
- `embedding_cache` is not a migration domain; it will warm/rebuild after
  cutover.

## Commands

```powershell
# Safe Phase 3A inventory of production SQLite; no PostgreSQL writes.
python backend/scripts/migrate_sqlite_to_postgres.py --source data/sqlite/local_ai_core.db --domain all --dry-run --batch-size 100

# Read-only post-migration verification (Phase 3B, after an approved apply).
python backend/scripts/migrate_sqlite_to_postgres.py --source data/sqlite/local_ai_core.db --domain all --verify-only --batch-size 100

# Approved Phase 3B execution only; DATABASE_URL must target the approved
# PostgreSQL migration target, never an unverified runtime database.
python backend/scripts/migrate_sqlite_to_postgres.py --source data/sqlite/local_ai_core.db --domain all --apply --batch-size 100 --resume
```

## Idempotency and sequence handling

- Conversations, memories and OCR runs use legacy primary-key `ON CONFLICT DO
  NOTHING`.
- Messages and request logs retain legacy integer IDs and use the same rule.
- After a successful message import, `setval(pg_get_serial_sequence(...))`
  moves the identity sequence beyond the imported maximum, so new runtime
  messages cannot collide.
- Verification compares count/ID, timestamps, FK existence and canonical
  SHA-256 checksum for conversations, messages and OCR runs.
