# Sprint 1B Runtime Migration Gate

Date: 2026-07-25 (Asia/Saigon)  
Scope: apply Alembic revision `20260725_13` to runtime PostgreSQL and perform
read-only verification. Backend reload and Discord bot cutover were explicitly
out of scope.

## 1. Preflight

All required preflight guards passed before the recovery point and migration:

| Check | Result |
|---|---|
| Alembic heads | One head: `20260725_13` |
| Runtime database | `local_ai_core` |
| Runtime revision before | `20260725_12` |
| Test database | `local_ai_core_test` |
| Test revision | `20260725_13` |
| Runtime/test isolation | Different database names, confirmed |
| Runtime Discord tables | Both tables present |
| Runtime Discord sessions | 0 |
| Runtime Discord turns | 0 |
| Runtime feature flag | Unset; code default is `false` |
| Legacy RAM dictionary | Present |
| Legacy per-user key | Present |

`discord_bot/main.py` still contains the RAM conversation dictionary and
`conversation_key(guild_id, channel_id, user_id)`. The persistent-session path
remains protected by a default-false feature flag.

No resolver or turn mutation endpoint was called during this gate.

## 2. Git Revision and Status

Git state recorded before the migration:

```text
branch: main
revision: d18c73221c1e8490a4e9fb32060526221c2ee4ee
```

The working tree was already dirty with the reviewed Sprint 1/Sprint 1B
implementation and documents. Recorded paths included:

```text
M  .env.example
M  backend/app/main.py
M  backend/app/postgres/models.py
M  backend/app/stores/postgres_auxiliary_store.py
M  discord_bot/api_client.py
M  discord_bot/main.py
M  tests/test_discord_api_client.py
?? backend/alembic/versions/20260725_12_discord_persistent_sessions.py
?? backend/alembic/versions/20260725_13_discord_turn_leases.py
?? backend/app/postgres/discord_repositories.py
?? backend/app/routers/discord_sessions.py
?? backend/app/schemas/discord_schema.py
?? backend/app/services/discord_session_service.py
?? backend/app/services/discord_turn_service.py
?? backend/tests/test_discord_session_api.py
?? backend/tests/test_discord_session_schema.py
?? backend/tests/test_discord_session_service.py
?? backend/tests/test_discord_turn_service.py
?? discord_bot/session_location.py
?? tests/test_discord_feature_flag.py
?? tests/test_discord_session_location.py
```

Existing planning/audit documents were also untracked. This gate did not
modify source code or create a new Alembic revision.

## 3. Migration Review

Reviewed file:

```text
backend/alembic/versions/20260725_13_discord_turn_leases.py
```

Revision linkage is correct:

```text
revision = 20260725_13
down_revision = 20260725_12
```

`upgrade()` touches only `discord_session_turns` and adds:

```text
request_text
system_prompt
response_text
model_used
worker_id
lease_expires_at
heartbeat_at
attempt_count
max_attempts
```

It also adds:

```text
ck_discord_session_turns_attempt_count: attempt_count >= 0
ck_discord_session_turns_max_attempts: max_attempts > 0
ix_discord_session_turn_stale_lease:
  lease_expires_at WHERE status = 'running'
```

The revision contains a transitional:

```sql
UPDATE discord_session_turns SET request_text = '' WHERE request_text IS NULL
```

before making `request_text` non-null. The exact pre-migration snapshot had
zero Discord turns, so this statement affected zero rows and did not backfill
runtime data. The migration does not touch legacy conversations/messages,
does not create Discord rows, does not drop tables, and does not delete data.

`downgrade()` removes only the index, constraints, and columns introduced by
this revision. No runtime downgrade was run.

The reviewed migration matches the implemented Sprint 1B schema and the
zero-row runtime precondition.

## 4. Runtime Revision Before

Immediately before backup:

```text
20260725_12
```

The revision was checked again immediately before both Alembic invocations.

## 5. Backup Path

Fresh backup:

```text
data/backups/postgres/pre_discord_fifo_runtime_migration/local-ai-pre-discord-fifo-runtime-20260724T200624Z.dump
```

Backup time:

```text
UTC:          2026-07-24 20:06:24Z
Asia/Saigon:  2026-07-25 03:06:24+07:00
```

Properties:

| Item | Value |
|---|---|
| PostgreSQL format | Custom |
| PostgreSQL tools | 16.14 |
| Ownership | Excluded with `--no-owner` |
| Privileges | Excluded with `--no-privileges` |
| Size | 48,552 bytes |
| Snapshot mode | Exported `REPEATABLE READ, READ ONLY` snapshot |
| Snapshot revision | `20260725_12` |

The row counts below and `pg_dump --snapshot` used the same exported
PostgreSQL snapshot. The archive is under the existing `data/backups/`
gitignore rule.

## 6. SHA-256

```text
3bf7aea28ab522913a7c8271cadfb96f7a5c0cc75d2533f634bb87d14a29ce0b
```

The checksum was calculated after dump completion and independently
recomputed before migration. Both values matched.

## 7. `pg_restore --list`

`pg_restore --list` was run twice against the fresh archive:

| Check | Result |
|---|---|
| Initial catalog inspection | Exit 0 |
| Independent catalog recheck | Exit 0 |
| Catalog entries | 97 |

An initial PowerShell-only recheck attempted to use an unsupported
`Get-Content -AsByteStream` parameter and did not inspect the archive. It did
not alter the backup or database. The recheck was immediately repeated with
binary-safe streaming and succeeded with the same 97-entry result.

## 8. Row Counts Before

Counts from the exact exported backup snapshot:

| Table | Before |
|---|---:|
| `conversations` | 6 |
| `messages` | 30 |
| `memories` | 0 |
| `jobs` | 0 |
| `outbox_events` | 0 |
| `discord_conversation_sessions` | 0 |
| `discord_session_turns` | 0 |

No natural runtime count drift occurred before migration, so the expected
historical values and the fresh snapshot baseline were identical.

## 9. Migration Command and Result

Required command:

```text
python -m alembic upgrade 20260725_13
```

Guard behavior:

- runtime database name had to equal `local_ai_core`;
- revision immediately before migration had to equal `20260725_12`;
- `POSTGRES_TEST_URL` was removed from the subprocess environment;
- the test database was never passed to the migration subprocess.

The first invocation exited 1 before opening an Alembic database connection:

```text
RuntimeError: DATABASE_URL is required for online Alembic migrations
```

`backend/alembic/env.py` requires `DATABASE_URL` directly in the process
environment. Post-failure verification confirmed:

```text
revision = 20260725_12
new FIFO/lease columns present = none
```

No partial DDL existed and no rollback/restore action was needed.

The guarded runtime URL was then loaded without printing it, set only for the
Alembic subprocess, and the same command was retried:

```text
target database: local_ai_core
revision immediately before retry: 20260725_12
POSTGRES_TEST_URL present: no
exit code: 0
```

No downgrade was run.

## 10. Runtime Revision After

```text
20260725_13 (head)
```

Both direct `alembic_version` inspection and `alembic current` confirmed the
new head.

## 11. Column, Index, and Constraint Verification

New columns:

| Column | PostgreSQL type | Nullable | Default |
|---|---|---:|---|
| `request_text` | TEXT | No | None |
| `system_prompt` | TEXT | Yes | None |
| `response_text` | TEXT | Yes | None |
| `model_used` | VARCHAR(255) | Yes | None |
| `worker_id` | TEXT | Yes | None |
| `lease_expires_at` | TIMESTAMPTZ | Yes | None |
| `heartbeat_at` | TIMESTAMPTZ | Yes | None |
| `attempt_count` | INTEGER | No | 0 |
| `max_attempts` | INTEGER | No | 3 |

New constraints and index:

```text
ck_discord_session_turns_attempt_count: attempt_count >= 0
ck_discord_session_turns_max_attempts: max_attempts > 0
ix_discord_session_turn_stale_lease:
  columns = lease_expires_at
  unique = false
  predicate = status = 'running'
```

Sprint 1 constraints retained:

| Invariant | Verification |
|---|---|
| Unique message per session | `uq_discord_session_turn_message(session_id, discord_message_id)` |
| Unique sequence per session | `uq_discord_session_turn_sequence(session_id, sequence_number)` |
| One running turn per session | Partial unique index predicate `status = 'running'` |
| Positive sequence | CHECK retained |
| Valid turn status | CHECK retained |
| Turn → session FK | Present |
| Session delete behavior | `ON DELETE CASCADE` |

Runtime model and repository imports succeeded against the migrated schema.

## 12. Row Counts After

| Table | Before | After | Changed |
|---|---:|---:|---|
| `conversations` | 6 | 6 | No |
| `messages` | 30 | 30 | No |
| `memories` | 0 | 0 | No |
| `jobs` | 0 | 0 | No |
| `outbox_events` | 0 | 0 | No |
| `discord_conversation_sessions` | 0 | 0 | No |
| `discord_session_turns` | 0 | 0 | No |

No Discord session/turn was generated and no legacy data count changed.

## 13. Health Checks

Read-only post-migration checks:

| Check | Result |
|---|---|
| `GET /health` | HTTP 200, `status=ok` |
| PostgreSQL component | `ok` |
| Redis component | `ok`; direct `PING` = `PONG` |
| Qdrant component | `ok`; `/healthz` HTTP 200 |
| Ollama component | `ok`; `/api/tags` HTTP 200 |
| `GET /conversations` | HTTP 200, 6 conversations |
| `GET /ui/` | HTTP 200 |
| Model/repository import | `ok` |
| Runtime Discord count query | sessions 0, turns 0 |

`worker_ocr` and `worker_index` remained `unavailable` in the health payload,
matching the already documented state from the previous backend reload gate.
Core health remained `status=ok`; neither worker was restarted.

The live API process IDs remained the previously recorded:

```text
launcher: 19492
listener: 13576
```

Live OpenAPI still exposes the Sprint 1 resolver but not the Sprint 1B turn
enqueue route. This confirms the backend process was not reloaded with Sprint
1B source during this gate.

Only GET/health and database read operations were used. None of the resolver,
enqueue, execute, complete, or fail endpoints was called.

## 14. Feature Flag Status

```text
DISCORD_PERSISTENT_SESSIONS_ENABLED = unset
effective default = false
```

The runtime `.env` was not modified.

## 15. Bot Cutover Status

```text
PRODUCTION BOT NOT CUT OVER
```

No Discord bot Python process was detected during final verification. No bot
was restarted. The source retains the default-false feature flag, legacy RAM
dictionary, and legacy per-user key. No runtime Discord session, turn, or
backend conversation was created.

## 16. Remaining Work

The next work must use separate controlled gates:

1. reload only the backend API so the Sprint 1B turn routes become live;
2. verify live OpenAPI and health without calling mutation endpoints;
3. validate the persistent/FIFO path in a non-production Discord environment;
4. perform a dedicated production bot cutover and rollback gate;
5. monitor turn backlog, leases, retries, failures, and orphan recovery.

Rule filtering, Qwen3.5:2b extraction, structured memory, rolling summary, and
Qdrant memory retrieval remain outside this gate.

## 17. Final Decision

```text
SPRINT 1B RUNTIME SCHEMA READY
```

The fresh backup, checksum, and archive catalog inspection passed. Runtime
migrated to `20260725_13`; all new and retained constraints were verified;
legacy and Discord row counts were unchanged; core health passed; the feature
flag remained false/unset; backend Sprint 1B source was not reloaded; and the
Discord bot was not cut over.
