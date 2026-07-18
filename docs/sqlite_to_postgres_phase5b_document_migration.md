# Phase 5B — Document Migration Preparation

## Status

**Complete for schema, document-data preparation, verification and isolated Qdrant mapping.** This phase did not change `DOCUMENT_DATABASE_BACKEND`, activate any document version, cut over document runtime/retrieval/BM25, delete SQLite, remove legacy Qdrant points, or change the auxiliary PostgreSQL cutover.

The new `backend/scripts/migrate_sqlite_documents_to_postgres.py` is deliberately separate from the auxiliary-domain migration. It accepts only the audited primary database, opens it with SQLite URI `mode=ro` and `PRAGMA query_only=ON`, and rejects test and `pre_postgres_*` files.

## Alembic

- `20260718_08_document_chunk_citation_metadata` adds nullable JSONB `document_chunks.locations` and `document_chunks.heading_path`.
  - `locations` preserves legacy `locations_json` as its ordered location-object array.
  - Audited legacy `heading_path` values are scalar strings, so they are preserved as a one-item JSONB string array.
- `20260718_09_allow_source_less_document_hash` makes `documents.content_hash` nullable. The audited source-less document has no trustworthy hash; preserving `NULL` is required and no hash was fabricated. Downgrade refuses to restore NOT NULL when source-less rows remain.

No prior Alembic revision was edited or squashed.

## Mapping and idempotency

| Legacy | PostgreSQL | Rule |
|---|---|---|
| `documents.id` | `documents.id` | Preserve opaque ID; compare filename, stored filename, MIME, known content hash, source lifecycle and retention. |
| `active_index_version=1` | `ver_{document_id}_1`, version 1 | Verify deterministic convention; keep target version `staging`. |
| `document_ingestion_runs.id` | `ingestion_runs.id` | Preserve ID, document/version, stage/status, counters, errors, cancellation and timestamps. |
| `document_chunk_versions` tuple | `document_chunks` tuple | Canonical text/hash are hard fail-closed checks; citation metadata backfills only after they match. |

SQLite remains lifecycle authority until Phase 5C. Therefore `source_removed_at` and `last_accessed_at` are reconciled from SQLite instead of being silently ignored. IDs, canonical text, hashes and version mapping remain fail-closed. Each domain batch is transactional; a mismatch rolls back that batch. Re-run is idempotent.

The source-less uploaded document is stored with `content_hash=NULL`, `source_available=false`, no active version and no fabricated source. It is not reparsed, reindexed or activated.

CLI:

```text
--source <sqlite-path>
--dry-run | --apply | --verify-only
--batch-size <number>
--resume
--document-id <optional>
--qdrant-mode none|validate|validation-upsert
--qdrant-validation-collection <name>
```

## Qdrant

A legacy point is selected only after all of these agree:

```text
document_id + index_version + chunk_index + deterministic legacy UUID5
```

Its mapped PostgreSQL chunk must also match canonical content hash. Target ID is a deterministic UUID5 of `document_id + PostgreSQL version_id + chunk_index`; payload has `document_id`, `version_id`, `chunk_id`, `chunk_index`, `content_hash`, page range and citation metadata.

The isolated collection `documents_phase5b_validation_20260718` contains exactly four target points: three for `doc_8eea844701b041b980e8142a2793f3ee` v1, and one for `doc_e002fbb8408c4d419531b15e1491e1e1` v1. The other 53 production points were not selected, changed or removed.

A validation test uses that collection and the validation PostgreSQL database. It injects the verified active-version map only inside the test, then proves `PostgresRetrievalService` filters Qdrant by `version_id` and batch-loads the mapped PostgreSQL chunk. No migration record becomes active.

## Tier 1 validation

- Separate database: `local_ai_document_phase5b_validation_20260718`, upgraded to Alembic head `20260718_09`.
- Source count: 3 documents, 2 versions, 2 runs, 4 chunks.
- Dry-run made no writes.
- Apply, verify-only, second `--resume` apply and final verify all returned zero canonical mismatch.
- Second apply inserted zero records.
- Validation records remain inactive.

## Tier 2 runtime preparation

Before runtime preparation:

- PostgreSQL backup was created and checked non-empty: `data/backups/postgres-phase5b/local-ai-20260718-043640.dump` (42,813 bytes).
- Qdrant snapshot was created: `documents-7079489509187321-2026-07-17-21-37-11.snapshot`.

Runtime PostgreSQL was upgraded to `20260718_09`. The tool applied verified metadata, then `--resume` and `--verify-only` completed successfully with zero mismatch. It backfilled JSONB citation fields on the four verified chunks. Production Qdrant was only snapshot/read; only the separate validation collection received versioned payloads.

## Tests

| Command/check | Result |
|---|---|
| Python compile: tool, model, revisions | passed |
| Alembic upgrade head on validation DB | exit code 0 |
| Validation dry-run/apply/verify/apply--resume/verify | all exit code 0; rerun inserted 0 |
| `pytest tests/test_sqlite_document_migration.py` with validation PostgreSQL | 7 passed, one existing warning |
| New migration test plus foundation without explicit test URL | 3 passed, 6 skipped, one warning |
| Full `pytest -q` from `backend` | 54 passed, 63 skipped, 0 failed, one warning |
| `docker compose config -q` | exit code 0 |
| Offline Alembic render | includes JSONB fields and `content_hash DROP NOT NULL` |

The skipped suite portions require an explicit `POSTGRES_TEST_URL`; the default environment has none. The Phase 5B migration tests were run against the isolated validation database.

## Files

- `backend/alembic/versions/20260718_08_document_chunk_citation_metadata.py`
- `backend/alembic/versions/20260718_09_allow_source_less_document_hash.py`
- `backend/app/postgres/models.py`
- `backend/scripts/migrate_sqlite_documents_to_postgres.py`
- `backend/tests/test_sqlite_document_migration.py`
- `docs/sqlite_to_postgres_phase5b_document_migration.md`

## Phase 5C gates

1. PostgreSQL rows are intentionally inactive; changing the document selector now would hide legacy indexed documents.
2. Production Qdrant still has legacy `index_version` payloads; Phase 5C needs verified versioned re-upsert while retaining legacy points until smoke tests pass.
3. SQLite has no `document_pages` source rows. The migrated chunk citation metadata is preserved, but page text cannot be invented.
4. Freeze document writers and run a final SQLite delta migration before cutover.
5. Embedding cache, BM25/retrieval runtime and cleanup remain out of Phase 5B.
