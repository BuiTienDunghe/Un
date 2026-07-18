# SQLite → PostgreSQL Phase 4A — auxiliary runtime preparation

Date: 2026-07-18  
Status: **prepared; not cut over**.

This phase adds tested PostgreSQL adapters and a temporary selector for the
already-migrated auxiliary data. The default remains SQLite. No runtime service
was switched, no dual-write was introduced, no SQLite file was modified, and
no document/BM25/embedding-cache data was migrated or rebuilt.

## Audit: current SQLite consumers

| Domain | Runtime consumer | Existing SQLite method(s) | Phase 4A preparation |
|---|---|---|---|
| Conversations/messages | `services/chat_service.py:ChatService.respond/stream_response`; `routers/conversations.py` | `conversation_exists`, `create_conversation`, `add_message`, `get_messages`, `list_conversations`, `get_conversation`, `delete_conversation` | `PostgresAuxiliaryStore`; router now reads `app.state.auxiliary_store` |
| Memories | `services/memory_service.py`; `routers/memory.py` | `create_memory`, `get_memory`, `update_memory`, `delete_memory` | same adapter; vector/search remains `MemoryService` + Qdrant |
| OCR runs | `services/ocr_job_service.py`; `routers/ocr.py` | `save_ocr_run`, `list_ocr_runs`, `delete_ocr_run` | JSONB-preserving adapter used when selector is PostgreSQL |
| Request logs | `services/logging_service.py`, called by ChatService and MemoryService; chat route logs model errors | `log_request` | adapter inserts `RequestLog`; no global request-logging middleware was found |
| OCR cache | `services/ocr_service.py`, called by OCR console and parser/document flows | `get_ocr_cache`, `save_ocr_cache` | PostgreSQL only accepts the complete Phase-2 key; missing revision is a cache miss |

`main.py` still constructs `SQLiteStore` because document legacy, BM25,
legacy retrieval, cleanup and document-worker cache paths remain out of scope.
Other deliberately-unmigrated consumers include `workers/tasks.py`,
`CleanupService`, `DocumentService`, `Bm25Service`, `RetrievalService`,
`PostgresDocumentService`'s legacy cache argument, `migrate_document_storage.py`
and their SQLite-oriented tests. They remain unchanged.

`workers/tasks.py:_service` is the one non-HTTP auxiliary cache consumer. In
PostgreSQL auxiliary mode it now gives its `OCRService` and `LoggingService`
the PostgreSQL adapter, while retaining SQLite only for the explicitly deferred
document embedding cache.

## PostgreSQL adapter and behaviour contract

New files:

* `backend/app/stores/auxiliary_store.py` — structural service contract shared
  by the current SQLite store and the new adapter.
* `backend/app/stores/postgres_auxiliary_store.py` — transaction-scoped
  PostgreSQL implementation for the six Phase 4A domains.

Compatibility decisions:

* Conversations retain opaque string IDs. Message runtime inserts omit `id`,
  therefore PostgreSQL uses the reseeded identity. History fetches newest N by
  ID then reverses it, matching current SQLite chronological output.
* Deleting a conversation uses the existing `messages.conversation_id` FK with
  `ON DELETE CASCADE`.
* Memory CRUD mirrors existing metadata storage only. Qdrant vector writes and
  search remain in `MemoryService`; no memory-vector feature was added.
* OCR-run `result_json` is parsed to a JSON object and stored as JSONB. Update
  upserts the full object, preserving unknown fields structurally. JSONB does
  not preserve object-key order, which is an intentional PostgreSQL difference.
* Request-log writes retain current failure semantics: `LoggingService` does
  not swallow persistence errors. Phase 4A found no global middleware with a
  contrary best-effort policy.
* OCR cache requires `(input_hash, engine, model_name, model_revision,
  config_fingerprint)`. The runtime has no OCR `revision` in `models.yaml`; in
  PostgreSQL mode this safely becomes a cache miss rather than a guessed key.
  Supplying a real `ocr.revision` enables reads and writes. SQLite is unchanged.

## Dependency injection and configuration

`main.py` still sets `app.state.store` to SQLite for legacy document paths. It
now sets a separate `app.state.auxiliary_store`:

```text
AUXILIARY_DATABASE_BACKEND=sqlite   → SQLiteStore (default)
AUXILIARY_DATABASE_BACKEND=postgres → PostgresAuxiliaryStore
```

Chat, memory, logging, OCR service/job service and conversation routes receive
the auxiliary store. This is a selector, not dual-write. It is temporary and
must be removed after all auxiliary domains are cut over.

`Settings` rejects invalid selector values. If either document or auxiliary
backend is PostgreSQL, startup fails before application wiring when
`DATABASE_URL` is missing or does not use a PostgreSQL SQLAlchemy dialect.
There is no fallback from selected PostgreSQL mode to SQLite.

`.env.example` documents `DATABASE_URL` for Windows host scripts (`127.0.0.1`)
and `CONTAINER_DATABASE_URL` for Compose containers (`postgres`). Compose sends
the container URL to worker/dispatcher/cleanup containers, falling back only to
`DATABASE_URL` when an explicit container URL is absent. Values are placeholders,
not committed secrets.

The local `.env` still lacks an explicit `DATABASE_URL`. This is acceptable
only while auxiliary mode stays SQLite; it blocks Phase 4B.

## Tests executed

| Command | Result |
|---|---|
| `pytest tests/test_postgres_auxiliary_store.py -q` | 7 passed, 0 failed, 1 pre-existing warning |
| `pytest tests/test_postgres_auxiliary_store.py tests/test_rq_ingestion_integration.py tests/test_auxiliary_postgres_schema.py tests/test_sqlite_to_postgres_migration.py -q` | 16 passed, 0 failed, 1 warning |
| `pytest tests -q` | 111 passed, 0 failed, 1 warning |
| `docker compose config -q` with separate host/container URLs | exit 0 |

The PostgreSQL adapter tests use the real isolated `POSTGRES_TEST_URL` target.
They cover conversation/message ordering and FK cascade; memory CRUD; OCR run
JSONB update/read; OCR-cache hit/miss; request-log insertion; transaction
rollback; PostgreSQL-unavailable handling; invalid configuration; and the
`/conversations/{id}` API with the PostgreSQL selector. Existing SQLite
API/service tests remain in full regression.

## Files changed

* `backend/app/config/settings.py`
* `backend/app/main.py`
* `backend/app/routers/conversations.py`
* `backend/app/services/chat_service.py`
* `backend/app/services/memory_service.py`
* `backend/app/services/logging_service.py`
* `backend/app/services/ocr_job_service.py`
* `backend/app/services/ocr_service.py`
* `backend/app/workers/tasks.py`
* `backend/app/stores/auxiliary_store.py`
* `backend/app/stores/postgres_auxiliary_store.py`
* `backend/tests/test_postgres_auxiliary_store.py`
* `.env.example`
* `docker-compose.yml`

## Phase 4B checklist — do not execute in Phase 4A

1. Set/review a real host `DATABASE_URL` and container
   `CONTAINER_DATABASE_URL`; do not commit secrets.
2. Pause auxiliary writes: stop API writers and OCR-console activity.
3. Back up PostgreSQL, then run `migrate_sqlite_to_postgres.py --apply --domain
   all --batch-size 100 --resume` against the approved runtime database.
4. Run `--verify-only --domain all`; require zero mismatch, orphan and JSON
   failures.
5. Set `AUXILIARY_DATABASE_BACKEND=postgres`, restart API, then smoke-test
   chat, conversations, memory, OCR-console/cache and request logs.
6. Verify SQLite auxiliary tables no longer receive writes; never dual-write.
7. If failure occurs before new writes are accepted, set selector back to
   `sqlite` and restart. Keep PostgreSQL data and backups for diagnosis.

Document legacy, embedding-cache rebuild, BM25/cleanup migration, SQLite
archival and SQLite removal remain later phases.
