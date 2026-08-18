# Operations — PostgreSQL-only baseline

Date: 2026-07-19

## Health and runtime boundaries

`GET /health` must report PostgreSQL, Redis, Qdrant, Ollama, OCR/index worker
discovery, outbox state, the cleanup heartbeat, and the PostgreSQL backup
freshness (`backup`, `backup_age_hours`, `backup_worker`). SQLite is not a health
component and its appearance in the response is a release blocker.

`DATABASE_URL` must be PostgreSQL. FastAPI, RQ workers, the cleanup worker, and
the outbox dispatcher must not open a SQLite database or import `SQLiteStore`.
Run `pytest backend/tests/test_postgres_runtime_guard.py -q` after changing
runtime composition.

## Backup, restore and retention

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m scripts.backup_postgres --output-dir data\backups\postgres --docker-service postgres
```

Keep PostgreSQL backups, Qdrant snapshots, and the SQLite archive. Restore a
PostgreSQL backup only to an isolated validation database first, migrate it to
Alembic head, and validate repository reads before considering production
recovery. Never restore an archive into `data/sqlite/` or merge
`pre_postgres_*` files.

The retained Phase 8B recovery references are:

- PostgreSQL dump: `data/backups/postgres-phase8b/local-ai-20260719-001749.dump`
- SQLite archive: `data/archives/sqlite-retired-20260719T002000Z/`
- Latest Phase 9A Qdrant snapshot: recorded in
  `data/benchmarks/phase9a_legacy_qdrant_mapping.json`

## Qdrant operations

Qdrant is an index, not a source of truth. Production retrieval accepts only
points containing `version_id` and `chunk_id`, then verifies them against active
PostgreSQL chunks. Legacy `index_version`-only points are neither retrieved nor
considered by cleanup.

The legacy-point inventory is frozen at 73 points: 4 `VERIFIED_REPLACED` and
69 `UNKNOWN_DO_NOT_DELETE`. Cleanup is deferred indefinitely pending separate
approval. Do not run Phase 9B, delete legacy points, update their payloads, or
re-upsert them during normal operations.

## Safe checks

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m scripts.worker_smoke --role ocr
.\.venv\Scripts\python.exe -m scripts.worker_smoke --role index
.\.venv\Scripts\python.exe -m scripts.cleanup_worker --dry-run
.\.venv\Scripts\python.exe -m scripts.outbox_dispatcher --once
docker compose config -q
```

These checks must use the configured PostgreSQL runtime. The cleanup dry-run
plans PostgreSQL lifecycle records only; no legacy-Qdrant cleanup domain exists.
