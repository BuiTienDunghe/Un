# Phase 2: Versioned ingestion

## Runtime switch and rollback

Document metadata, versions, runs, pages, chunks, and document retrieval use
PostgreSQL only when `DOCUMENT_DATABASE_BACKEND=postgres` and `DATABASE_URL`
is configured. The default remains `sqlite`, so rollback is a configuration
change and application restart; SQLite and its migration scripts are retained.
There is no dual-write mode.

Before enabling PostgreSQL, run Alembic through revision `20260717_02` and
verify the Phase 1 SQLite copy as described in `postgres_migration.md`.

## State machines

- Document: `uploaded -> processing -> indexed`; a first-version failure becomes
  `failed`. A reindex failure keeps the document `indexed` because its active
  version remains usable.
- Version: `staging -> active|failed|deleted`, `active -> superseded|deleted`,
  `superseded -> deleted`, and `failed -> staging|deleted` for an explicit retry.
  A failed version cannot become active directly.
- Run stage: `queued -> parsing -> ocr? -> chunking -> embedding ->
  qdrant_upsert -> activating -> completed`, with terminal `failed` or
  `cancelled` states.

The repository owns stage changes and refuses a transition out of a terminal
run. PostgreSQL row locking on the document during reindex/activation prevents
two active versions for one document.

## Upload, first index, and reindex

Upload validates bytes, calculates SHA-256, creates the source directory, then
creates `documents`, version 1 (`staging`), and its queued ingestion run in one
short PostgreSQL transaction. If that transaction fails, the newly-written
source directory is removed. A duplicate hash returns the existing document.

The existing index endpoint continues to run synchronously in a background
thread during Phase 2. It performs parse/OCR, page writes, chunk writes,
embedding, and Qdrant calls outside PostgreSQL transactions. Each persistence
or state update is a short transaction. No transaction remains open while
PyMuPDF, OCR/Ollama, embedding/Ollama, or Qdrant is called.

For reindex, a new `staging` version and run are created. Its pages and chunks
are replaced only inside that staging version, so an old active version remains
queryable. If any stage fails, the staging version/run become failed; the old
active version is unchanged. Retrying a failed run resets that same staging
version and replaces only its own pages/chunks, making retries idempotent.

## Activation and Qdrant

After deterministic Qdrant upsert succeeds, a short activation transaction
locks the document row, verifies a staging version/run and at least one chunk,
marks the prior active version `superseded`, marks the new version `active`,
sets `documents.active_version_id`, and completes the run.

Qdrant point IDs are UUID5 values derived from `document_id + version_id +
chunk_index`. Payloads include `document_id`, `version_id`, `chunk_id`, chunk
index, page range, extraction method, and lightweight citation metadata. Retry
deletes/re-upserts the same version filter and cannot create duplicate points.
Superseded vectors are deliberately retained until the later cleanup worker.

## Retrieval

PostgreSQL is the active-version authority. Phase 2 first obtains the active
version IDs from PostgreSQL, filters Qdrant by those `version_id` payloads, then
batch-loads only `(document_id, version_id, chunk_index)` records that still
match PostgreSQL `active_version_id`. It never trusts a Qdrant active flag.
PostgreSQL FTS remains deferred to a later phase.

## Not in this phase

There is no Redis, RQ, separate worker process, outbox dispatcher, MinIO, or
cleanup worker lifecycle implementation. OCR and embedding models are unchanged;
the current shared `OCRService` and current configured models are reused.

## Phase 3 execution mode

When `INGESTION_EXECUTION_BACKEND=rq`, this document's extraction and indexing
steps run in separate RQ worker processes rather than the FastAPI thread. Their
state transitions, version activation, and retrieval semantics are unchanged;
see `worker_architecture.md` for queue/recovery details. `thread` remains a
temporary rollback mode only.
