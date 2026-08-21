# Current architecture — PostgreSQL-only baseline

Date: 2026-08-19 (original 2026-07-19; refreshed after P0 and P1-1..P1-3)

## Source-of-truth boundary

PostgreSQL is the sole runtime source of truth. `DATABASE_URL` is required and
must use a `postgresql+` SQLAlchemy dialect; SQLite URLs fail at startup.
SQLite databases are not mounted, opened, or created by FastAPI, workers,
cleanup, or ordinary tests.

The retired SQLite data is an explicit read-only archive, not a fallback:

```text
data/archives/sqlite-retired-20260719T002000Z/
```

Only migration/audit CLIs and their migration-specific tests may use `sqlite3`,
and they must receive the archive path explicitly. `pre_postgres_*` archives
are historical evidence only and must never be merged or used as a runtime
database.

## Runtime components

```text
FastAPI APIs (layer-1 X-API-Key guard on every mutating route)
  -> PostgreSQL: documents, versions, pages, chunks, jobs, outbox,
     conversations + message_sources (persisted citations), Discord sessions/memory
  -> Redis/RQ: OCR, indexing and Discord-memory transport only
       -> OCR worker / index worker / memory worker
            -> PostgreSQL canonical state + Qdrant versioned vectors
  -> host workers started by the launcher: cleanup, backup,
     outbox dispatcher + memory worker (when memory proposal mode is enabled)
```

`backend/app/main.py` composes PostgreSQL repositories and document/retrieval
services. Redis carries job IDs; PostgreSQL owns lifecycle state, idempotency,
outbox records, active-version state, citations, and canonical chunk content.
Ollama provides embeddings and model inference; it is not a persistence source.

The current Alembic head is pinned in README ("Alembic head hiện tại"); do not duplicate it here.

## Qdrant contract

The production `documents` collection is a vector index, never the canonical
content source. A runtime retrieval candidate is accepted only when it has both
`version_id` and `chunk_id`; PostgreSQL then confirms that the chunk belongs to
the requested document's active version before returning its content/citation.

Points that only contain legacy `index_version` are deliberately ignored by
retrieval. Cleanup planning and execution also exclude legacy Qdrant points;
there is no `legacy-qdrant` cleanup domain. Legacy-point audit is a separate,
read-only Phase 9A command and no automatic cleanup policy exists.

## Retention and recovery

- PostgreSQL backups and Qdrant snapshots are retained recovery artifacts.
- The SQLite archive remains retained and checksum-verified; it is not restored
  into `data/sqlite/` or any runtime path.
- Source cleanup applies only to explicitly temporary, unpinned PostgreSQL
  documents after configured TTL and lifecycle guards.
- Superseded version cleanup uses PostgreSQL guards and only deletes Qdrant
  points addressed by a PostgreSQL `version_id`; it cannot select legacy points.

For recovery, restore a PostgreSQL dump into a separate validation database,
validate its Alembic revision and repository reads, then use the retained
Qdrant snapshot according to an approved recovery procedure. Never merge
SQLite archives or use one as a runtime replacement.

## Operational evidence

`GET /health` reports PostgreSQL, Redis, Qdrant, Ollama, worker discovery,
outbox state, cleanup heartbeat, PostgreSQL backup freshness (`backup`,
`backup_age_hours`, `backup_worker`) and, when enabled, the memory pipeline
(`memory_ingestion`, `worker_memory`). It has no SQLite component. The runtime
guard tests prove FastAPI and worker modules do not import `SQLiteStore` or
`sqlite3`.

The Phase 9A inventory is the authoritative legacy-point status report:
`data/benchmarks/phase9a_legacy_qdrant_mapping.json`. Legacy cleanup is deferred
indefinitely until a separately approved policy explicitly authorizes it.
