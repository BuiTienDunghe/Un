# Worker architecture — PostgreSQL-only baseline

*For documents this path applies only with `INGESTION_EXECUTION_BACKEND=rq`. The default is
`thread`: OCR and indexing run in a background thread of the API, and `run-local-ai-core.bat`
starts no OCR or index worker (`current_architecture.md`). The Discord memory worker always
uses RQ.*

## Execution path

```text
FastAPI -> PostgreSQL job + outbox transaction -> Redis/RQ queue
                                                  -> OCR worker
                                                  -> index worker
Workers -> PostgreSQL pages/chunks/version lifecycle + Qdrant versioned vectors
```

PostgreSQL is authoritative for job ownership, idempotency, state transitions,
active version activation and outbox publication. Redis only transports job IDs.
Workers claim PostgreSQL jobs before doing work and are safe against duplicate
RQ delivery.

## Qdrant boundary

The index worker writes only deterministic versioned point IDs for PostgreSQL
chunks. Runtime retrieval accepts only candidates with `version_id` and
`chunk_id`, validates them against an active PostgreSQL version, and loads
canonical content/citations from PostgreSQL.

Legacy `index_version`-only points are not worker input, not retrieval
candidates and not cleanup candidates. The legacy-point audit remains a
separate read-only Phase 9A operation; cleanup is deferred indefinitely pending
separate approval.

## Operational probes

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m scripts.worker_smoke --role ocr
.\.venv\Scripts\python.exe -m scripts.worker_smoke --role index
.\.venv\Scripts\python.exe -m scripts.outbox_dispatcher --once
```

The probes verify PostgreSQL connectivity, Redis connectivity, queue naming and
task imports without OCR, embedding, Qdrant writes, or SQLite access.
