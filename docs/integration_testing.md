# Phase 3 integration testing

Use a dedicated PostgreSQL database and Redis DB 15; never point tests at the
development database.

```powershell
$env:POSTGRES_TEST_URL='postgresql+psycopg://local_ai:change-me@127.0.0.1:5432/local_ai_core_test'
$env:REDIS_TEST_URL='redis://127.0.0.1:6379/15'
$env:DATABASE_URL=$env:POSTGRES_TEST_URL
.\.venv\Scripts\python.exe -m alembic upgrade head
cd backend
..\.venv\Scripts\python.exe -m pytest tests\ -q
```

Each worker integration test uses `local-ai:test:<uuid>:ocr` and `:index`, then
removes its PostgreSQL rows and Redis queue/registry keys. When a test times
out, inspect the PostgreSQL `jobs`/`ingestion_runs` rows and Redis queue plus
started, failed, scheduled and deferred registries for that prefix.

Smoke probes do not call Ollama or Qdrant:

```powershell
$env:DATABASE_URL=$env:POSTGRES_TEST_URL
$env:REDIS_URL=$env:REDIS_TEST_URL
$env:RQ_QUEUE_PREFIX='local-ai:test:smoke'
cd backend
..\.venv\Scripts\python.exe -m scripts.worker_smoke --role ocr
..\.venv\Scripts\python.exe -m scripts.worker_smoke --role index
```

For containers, first start PostgreSQL and Redis, then run the same probe with
`worker-ocr` or `worker-index` and the test `DATABASE_URL`, Redis DB 15, and a
test-only `RQ_QUEUE_PREFIX`. Production workers use `--with-scheduler` so RQ
transport retries can be released; PostgreSQL remains the job-state authority.
