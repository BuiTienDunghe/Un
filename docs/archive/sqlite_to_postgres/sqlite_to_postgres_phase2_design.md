# SQLite → PostgreSQL Phase 2 — schema design

Revision: `20260718_07_auxiliary_postgres_domains`  
Scope: schema only. No SQLite row was read for migration, no runtime consumer,
API, worker, repository, or feature flag was changed.

## New tables

| Table | Compatibility and operational rationale |
|---|---|
| `conversations` | `id VARCHAR(128)` preserves opaque legacy `TEXT` IDs; timezone `created_at`, `updated_at`; index on `updated_at` supports `SQLiteStore.list_conversations()` ordering. |
| `messages` | `BIGINT IDENTITY` allows explicit legacy integer IDs; `conversation_id` FK with `ON DELETE CASCADE`; role/content/model/timestamp mirror `SQLiteStore.add_message()`. Index on `conversation_id` supports `get_messages()` and `get_conversation()`. |
| `memories` | Legacy id/content/type/importance/timestamps plus non-null `metadata_json JSONB`. No content uniqueness was added: `MemoryService.add()` has no duplicate rule. |
| `request_logs` | Legacy request fields and `BIGINT IDENTITY`; `created_at TIMESTAMPTZ` index is the evidence-based retention query path from `CleanupService.delete_expired_logs()`. Retention policy is 90 days for Phase 3 migration/cutover planning; no cleanup runtime was implemented here. |
| `ocr_runs` | Legacy id/filename/status/model/timestamps; `result_json JSONB` preserves the complete legacy JSON payload used by `OcrJobService.view()`, `list_history()` and `_save()`. Index on `updated_at` supports history/cleanup ordering. |
| `ocr_cache` | New cache identity: `(input_hash, engine, model_name, model_revision, config_fingerprint)`. This derives from `OCRService.recognize_png()`: input hash is currently image hash; engine is Ollama; model comes from `models.yaml`; current config hash covers model, temperature, context, prompt and DPI. |
| `embedding_cache` | Required because `PostgresDocumentService._run_index()` and `index_for_worker()` call `get_embedding_cache()`/`save_embedding_cache()`. New unique identity includes content hash, model, model revision, dimensions, config fingerprint and normalization fingerprint. The vector is `JSONB`. The four legacy rows are **not** migration input; they will be rebuilt. |

All timestamps are `TIMESTAMPTZ`. `String(128)` is intentionally used for
legacy opaque IDs rather than PostgreSQL UUID: Phase 1 proved only that the
legacy columns are `TEXT`, not that every historical value validates as UUID.

## Constraints and indexes

- `messages.conversation_id → conversations.id ON DELETE CASCADE`.
- `uq_ocr_cache_key` and `uq_embedding_cache_key` prevent duplicate cache
  entries for materially different execution configurations.
- Indexes are only on existing query/order paths: conversation `updated_at`,
  message `conversation_id`, request-log `created_at`, OCR-run `updated_at`.
  No speculative GIN metadata index was created because no current consumer
  queries `Memory.metadata_json`.

## Document mapping design for Phase 3

No document row is migrated in this phase.

1. `SQLite documents.id` maps to `PostgreSQL documents.id` only after verifying
   the source ID, content hash and source file relationship.
2. For each `(SQLite document_id, index_version)`, Phase 3 must create or find
   one `document_versions` row with `version_number=index_version`; its generated
   `document_versions.id` is the authoritative `version_id` mapping.
3. `document_ingestion_runs.id` may be preserved as `ingestion_runs.id` only
   after validating that its mapped document/version exists. Legacy `stage`
   maps to `current_stage`; counts map to their corresponding PostgreSQL count
   fields.
4. `document_chunk_versions` maps to `document_chunks` using the established
   version mapping and its `(document_id,index_version,chunk_index)` uniqueness.
   Legacy integer chunk IDs are not used as PostgreSQL chunk IDs; the migration
   must keep an explicit mapping/checkpoint if traceability is required.
5. Empty legacy `document_chunks` is not migrated; it was the legacy BM25
   representation and current PostgreSQL retrieval uses versioned chunks.

## Explicitly deferred

- Data migration, verification report and idempotent migration tool changes
  (Phase 3).
- Runtime repository/service cutover and dual-write (later cutover phases).
- SQLite deletion, config removal and test conversion.
- Request-log cleanup implementation.
