# Discord Memory Pre-Sprint 1 Readiness Gate

Audit date: 2026-07-24 (Asia/Saigon)

Scope: PostgreSQL test isolation, rerun of the previously skipped PostgreSQL tests, runtime recovery point, and restore drill only. No Discord Memory migration, runtime bot/API change, production schema change, Qdrant change, or model download was performed.

## 1. Current Database Configuration

### Runtime loading path

- `backend/app/config/settings.py:16` loads the repository-root `.env` through `SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")`.
- `backend/app/config/settings.py:44-46` requires `DATABASE_URL` and rejects a non-PostgreSQL runtime URL.
- `backend/alembic/env.py:18-20` reads `DATABASE_URL` directly from the process environment. Alembic does not load `.env` itself.
- `alembic.ini:2` points `script_location` to `backend/alembic`; `alembic.ini:4` leaves `sqlalchemy.url` empty.
- `.env` and `.env.*` are ignored by Git at `.gitignore:34-35`.

Verified runtime metadata, with credentials redacted:

| Item | Verified value |
|---|---|
| Driver | `postgresql+psycopg` |
| Host | `127.0.0.1` |
| Port | `5432` |
| Database | `local_ai_core` |
| PostgreSQL server | `16.14` |
| Current Alembic revision | `20260719_11 (head)` |
| Current revision file | `backend/alembic/versions/20260719_11_allow_keep_both_display_names.py` |

The database role used by the project was verified to have database-creation permission. No credential or full connection string is included here.

### Existing backup support

`backend/scripts/backup_postgres.py` already creates a PostgreSQL custom-format dump, using host `pg_dump` or `docker compose exec` when `--docker-service` is supplied. It does not create a SHA-256 sidecar, coordinate row counts with an exported snapshot, or perform a restore drill. No repository restore script was found.

The host PostgreSQL CLI tools were not on `PATH`. The already-running, healthy Compose `postgres` service was therefore used only with `docker compose exec -T` for `pg_dump` and `pg_restore`. No container was created, restarted, or recreated.

During an initial failed read-only connection preflight, a local terminal traceback reflected the configured database URL. The value is not reproduced in this report and was not written to a repository log or document.

## 2. POSTGRES_TEST_URL Status

Status: **READY**

- At the beginning of the gate, `POSTGRES_TEST_URL` was absent from the current process.
- A dedicated database named `local_ai_core_test` was created.
- Its normalized database name was explicitly compared with runtime database `local_ai_core` before every mutation-capable command.
- The URL was injected into `POSTGRES_TEST_URL` and `DATABASE_URL` only for Alembic/test subprocesses.
- After successful verification, `POSTGRES_TEST_URL` was stored at the current Windows-user environment scope so a real credential did not need to be committed to Git. The stored value was read back and verified by metadata only: host `127.0.0.1`, port `5432`, database `local_ai_core_test`.
- No `.env`, tracked config, password, or full connection string was changed or committed. A newly launched terminal/application may be required to inherit the user-level environment update.

Existing test behavior:

- `backend/tests/conftest.py:6-9` maps `POSTGRES_TEST_URL` to `DATABASE_URL` before importing the application.
- `backend/tests/conftest.py:25-30` skips integration tests unless the database name ends in `_test`.
- The current source guard checks the `_test` suffix but does not independently normalize and compare against runtime `DATABASE_URL`.

For this readiness run, an additional preflight rejected the command unless all of the following were true:

1. the target database was exactly `local_ai_core_test`;
2. the target ended in `_test`;
3. the target differed from runtime database `local_ai_core`; and
4. `SELECT current_database()` returned `local_ai_core_test`.

This preflight passed. The existing suffix guard also rejects the current runtime database name because `local_ai_core` does not end in `_test`.

## 3. Test Database Isolation Verification

| Check | Result |
|---|---|
| Runtime database | `local_ai_core` |
| Test database | `local_ai_core_test` |
| Names differ | Passed |
| Test target identity via `current_database()` | Passed |
| `alembic upgrade head` on test DB | Exit 0 |
| `alembic current` on test DB | `20260719_11 (head)` |
| Required tables | All present |
| Temporary table insert/read/rollback probe | Passed |
| Runtime Redis DB | DB 0 |
| Test Redis DB | DB 15 |
| Redis DB isolation | Passed |

Required test schema verified:

- `alembic_version`
- `conversations`
- `messages`
- `memories`
- `jobs`
- `outbox_events`

Cleanup/isolation evidence:

- `backend/tests/conftest.py:43` reserves Redis DB 15 by default.
- Worker cleanup uses unique queue/file prefixes and deletes only matching test records at `backend/tests/conftest.py:69`.
- The API `client` fixture deletes all `Document` rows at `backend/tests/conftest.py:77,81`; this is safe only because it ran against the dedicated test database.
- Runtime revision and requested runtime table counts were captured before backup and checked again after all test/restore work. They were unchanged.

No test mutation was executed against `local_ai_core`.

## 4. Previously Skipped Tests

The earlier audit command collected 25 tests and reported `10 passed, 15 skipped`. The 15 tests skipped because `POSTGRES_TEST_URL` was missing were identified and rerun:

### Chat API — 5

- `backend/tests/test_chat_api.py::test_chat_returns_response_and_model_used`
- `backend/tests/test_chat_api.py::test_chat_uses_per_request_system_prompt`
- `backend/tests/test_chat_api.py::test_chat_rejects_unknown_conversation`
- `backend/tests/test_chat_api.py::test_chat_uses_relevant_memory_when_requested`
- `backend/tests/test_chat_api.py::test_chat_streams_tokens_and_persists_completed_message`

### Conversation API — 1

- `backend/tests/test_conversations_api.py::test_conversation_list_detail_and_delete`

### Memory API — 1

- `backend/tests/test_memory_api.py::test_memory_add_search_update_and_delete`

### Transactional outbox — 3

- `backend/tests/test_transactional_outbox.py::test_job_and_outbox_are_atomic`
- `backend/tests/test_transactional_outbox.py::test_dispatch_success_retry_and_idempotency`
- `backend/tests/test_transactional_outbox.py::test_two_dispatchers_publish_event_once`

### Stale recovery — 5

- `backend/tests/test_stale_recovery.py::test_stale_running_job_moves_to_retrying`
- `backend/tests/test_stale_recovery.py::test_stale_job_exhausted_attempts_fails_staging_run`
- `backend/tests/test_stale_recovery.py::test_non_stale_job_is_not_recovered`
- `backend/tests/test_stale_recovery.py::test_old_worker_loses_ownership_after_recovery`
- `backend/tests/test_stale_recovery.py::test_deterministic_redis_id_after_stale_retry`

Result for these 15 tests: **15 passed, 0 failed, 0 skipped**.

## 5. Test Results

### Alembic and connection checks

| Command/check | Result |
|---|---|
| Test DB `alembic upgrade head` | Passed, exit 0 |
| Test DB `alembic current` | `20260719_11 (head)`, exit 0 |
| Test DB schema inspection | Passed |
| Test DB temporary read/write probe | Passed |
| Restore DB `alembic current` | `20260719_11 (head)`, exit 0 |

### Original audit selection

Sanitized command:

```text
pytest tests/test_discord_api_client.py backend/tests/test_chat_api.py backend/tests/test_conversations_api.py backend/tests/test_memory_api.py backend/tests/test_worker_hardening.py backend/tests/test_qdrant_store.py backend/tests/test_transactional_outbox.py backend/tests/test_stale_recovery.py -vv -rs
```

Result:

```text
25 passed, 0 failed, 0 skipped, 2 warnings
```

Warnings:

- Starlette `TestClient`/`httpx` deprecation warning.
- Python `audioop` deprecation warning from the Discord dependency.

### All PostgreSQL-dependent modules

All 16 test modules containing `POSTGRES_TEST_URL` were run against `local_ai_core_test`. Redis-dependent concurrency tests used DB 15.

Result:

```text
83 passed, 0 failed, 1 skipped, 1 setup error, 1 warning
```

The remaining skip is valid and unrelated to PostgreSQL readiness:

- `backend/tests/test_sqlite_document_migration.py:146` requires `PHASE5B_QDRANT_VALIDATION_COLLECTION`.
- Creating or changing a Qdrant validation collection was outside this gate and explicitly prohibited.

The setup error is an existing test-fixture compatibility issue, not a PostgreSQL/Alembic failure:

- Test: `backend/tests/test_upload_conflict_decisions.py::test_upload_conflict_decisions`
- `backend/tests/test_upload_conflict_decisions.py:25` defines `_Ocr` without a `router`.
- The fixture passes it to `PostgresDocumentService` at line 35.
- `backend/app/parsers/smart_parser.py:26` now reads `ocr_service.router.models`, causing setup to stop before the test performs its database scenario.

This error does not block the persistent-session migration foundation: the migration command, schema checks, all 15 required previously skipped cases, auxiliary PostgreSQL schema/store tests, outbox tests, recovery tests, and concurrency tests passed. The fixture should be repaired separately before claiming the complete PostgreSQL integration set is fully green; it was not modified in this gate.

## 6. Runtime Recovery Point

A consistent recovery snapshot was created from runtime database `local_ai_core`.

| Item | Value |
|---|---|
| Backup time (UTC) | `2026-07-24T09:13:26Z` |
| Backup time (Asia/Saigon) | `2026-07-24 16:13:26 +07:00` |
| PostgreSQL format | Custom format |
| PostgreSQL server | `16.14` |
| Alembic revision | `20260719_11` |
| Ownership/ACL portability | `--no-owner --no-privileges` |
| Snapshot consistency | Row counts and `pg_dump` used the same exported read-only snapshot |
| `pg_restore --list` | Exit 0, 82 catalog entries |

The backup used an exported `REPEATABLE READ, READ ONLY` PostgreSQL snapshot. The row counts below and `pg_dump --snapshot=...` therefore describe the same database snapshot even if runtime workers remain active.

No runtime migration or data write was performed.

## 7. Backup File and SHA-256

Backup file:

```text
data/backups/postgres/pre_discord_memory_sprint1/local-ai-pre-discord-memory-sprint1-20260724T091326Z.dump
```

Size:

```text
40,968 bytes
```

SHA-256:

```text
96b5b12b9760e2f5d5e79292cfe700245628b109eed3e076e57119495ec5ebc9
```

The checksum was recomputed and verified immediately before the restore drill. `.gitignore:47` ignores `data/backups/`, so the dump is not a Git candidate. The filename and report contain no credential.

## 8. Runtime Row Counts

Counts from the exact exported backup snapshot:

| Table | Rows |
|---|---:|
| `conversations` | 6 |
| `messages` | 30 |
| `memories` | 0 |
| `jobs` | 0 |
| `outbox_events` | 0 |

No table whose name starts with `discord` existed in the runtime `public` schema.

After the restore drill, runtime remained:

- Alembic revision: `20260719_11`
- `conversations`: 6
- `messages`: 30
- `memories`: 0
- `jobs`: 0
- `outbox_events`: 0

This confirms no observed runtime data or schema change during the gate.

## 9. Restore Drill Results

Restore target: `local_ai_core_restore_test`

Safety checks:

- The target name was fixed and verified to end in `_restore_test`.
- Runtime, test, and restore database names were required to be pairwise different.
- The restore target did not exist before the drill.
- The command refused to overwrite an existing database.
- No `--clean`, `DROP DATABASE`, or runtime target was used.

Results:

| Check | Result |
|---|---|
| Temporary restore database creation | Passed |
| `pg_restore --exit-on-error` | Exit 0 |
| Required tables present | Passed |
| Restored Alembic revision | `20260719_11 (head)` |
| Restored row counts | Exact match |
| `PostgresAuxiliaryStore.healthcheck()` | `true` |
| Read-only `list_conversations()` | 6 rows |
| Runtime revision/counts after restore | Unchanged |

Restored counts:

| Table | Backup snapshot | Restored |
|---|---:|---:|
| `conversations` | 6 | 6 |
| `messages` | 30 | 30 |
| `memories` | 0 | 0 |
| `jobs` | 0 | 0 |
| `outbox_events` | 0 | 0 |

The temporary restore database was retained for review. It was created during this gate and was not used by runtime.

## 10. Remaining Blockers

Blocking items for starting Sprint 1: **none**.

Non-blocking follow-ups:

1. Fix the `_Ocr` stub in `backend/tests/test_upload_conflict_decisions.py` before requiring the entire PostgreSQL-dependent suite to be fully green. Do not change runtime behavior merely to satisfy this stale fixture.
2. Run the optional Phase 5B Qdrant validation test only when a dedicated disposable validation collection and `PHASE5B_QDRANT_VALIDATION_COLLECTION` are available. It is not part of the PostgreSQL migration gate.
3. The repository test guard currently enforces only the `_test` suffix. This gate added an explicit normalized runtime/test equality preflight. Future mutation test commands must retain that preflight; adding the equality check to shared test configuration can be considered separately, but was prohibited in this documentation/readiness-only turn.
4. A newly launched shell/application may be needed to inherit the newly stored user-level `POSTGRES_TEST_URL`.

None of these items invalidates the completed test database migration, the 15 required test reruns, or the verified recovery/restore point.

## 11. Sprint 1 Readiness Decision

# READY FOR SPRINT 1

All mandatory readiness conditions are satisfied:

- `POSTGRES_TEST_URL` is configured for `local_ai_core_test`, verified, and different from runtime database `local_ai_core`.
- The isolated test database migrated successfully to `20260719_11 (head)`.
- All 15 tests previously skipped because `POSTGRES_TEST_URL` was missing were rerun and passed.
- No test failure blocks the persistent-session migration foundation.
- `pg_dump` completed successfully.
- A SHA-256 checksum was created and verified.
- Runtime row counts were recorded from the same exported snapshot used by `pg_dump`.
- Restore to `local_ai_core_restore_test` succeeded.
- Restored revision, required schema, row counts, and repository read checks all passed.
- Runtime revision and row counts remained unchanged.

This decision authorizes only the start of Sprint 1 persistent session foundation work described in the approved audit. Sprint 1 remains limited to the backend-owned persistent Discord session foundation, database uniqueness/concurrent resolution testing, and the documented FIFO foundation. It does not authorize rule filters, the `qwen3.5:2b` extractor, structured long-term memory, Qdrant memory retrieval, Discord bot runtime changes beyond the approved Sprint 1 scope, or any later sprint.

No Sprint 1 migration revision or runtime implementation was created during this readiness gate.
