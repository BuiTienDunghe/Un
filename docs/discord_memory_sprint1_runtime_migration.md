# Sprint 1 Runtime Migration Gate

Execution time: 2026-07-25 Asia/Saigon  
Target: runtime PostgreSQL schema only

## 1. Preflight

Repository state:

| Item | Value |
|---|---|
| Branch | `main` |
| Git commit | `d18c73221c1e8490a4e9fb32060526221c2ee4ee` |
| Working tree | Dirty with the reviewed Sprint 1 implementation and pre-existing untracked planning/audit documents |
| Alembic heads | One head: `20260725_12` |

The exact Git status was captured before migration. No source, migration, test, bot, config, or Qdrant file was modified during this runtime migration gate.

Database preflight:

| Check | Result |
|---|---|
| Runtime database | `local_ai_core` |
| Runtime revision | `20260719_11` |
| Test database | `local_ai_core_test` |
| Test database revision | `20260725_12` |
| Runtime/test names differ | Passed |
| Runtime already has Discord session tables | No |

Migration review:

- `revision = 20260725_12`
- `down_revision = 20260719_11`
- `upgrade()` contains only table, index, CHECK, unique, primary-key, and foreign-key creation.
- `upgrade()` contains no `INSERT`, `UPDATE`, `DELETE`, backfill, legacy-row conversion, table drop, or column drop.
- The destructive operations exist only in `downgrade()`. No runtime downgrade was run.

Required source documents and the migration file were read and hashed before execution. No credential or full connection string was printed or stored in this report.

## 2. Runtime Revision Before

```text
20260719_11
```

Runtime did not contain:

```text
discord_conversation_sessions
discord_session_turns
```

## 3. Fresh Backup Path

Fresh backup created immediately before migration:

```text
data/backups/postgres/pre_discord_session_runtime_migration/local-ai-pre-discord-session-runtime-20260724T181023Z.dump
```

Properties:

| Item | Value |
|---|---|
| Format | PostgreSQL custom format |
| Size | 40,968 bytes |
| Ownership | Excluded with `--no-owner` |
| Privileges | Excluded with `--no-privileges` |
| Snapshot | Exported `REPEATABLE READ, READ ONLY` snapshot |
| Snapshot revision | `20260719_11` |
| `pg_restore --list` | Exit 0 |
| Catalog entries | 82 |

The dump and row counts used the same exported PostgreSQL snapshot.

The previous restore drill remains valid and the pre-migration runtime revision, required schema, and row counts had not changed since that drill. The fresh backup also passed `pg_restore --list`. Therefore a second restore drill was not required by this gate.

The backup directory is covered by the existing `data/backups/` Git ignore rule. The dump is not committed.

## 4. SHA-256

```text
26a3a4ee5a89b0f9d937fb98fcf7b8e26de8a5bf84f38ddb2fff4df9e3a993ff
```

Backup, checksum generation, non-empty-file validation, and catalog inspection all succeeded before migration began.

## 5. Row Counts Before

Counts from the exact backup snapshot:

| Table | Rows |
|---|---:|
| `conversations` | 6 |
| `messages` | 30 |
| `memories` | 0 |
| `jobs` | 0 |
| `outbox_events` | 0 |

## 6. Migration Command and Result

Command:

```text
python -m alembic upgrade 20260725_12
```

Execution guard:

- `DATABASE_URL` was supplied to the migration subprocess from the existing runtime configuration without printing it.
- The normalized target database was required to be exactly `local_ai_core`.
- The runtime revision was rechecked as `20260719_11` immediately before the command.
- `POSTGRES_TEST_URL` was removed from the migration subprocess environment.

Result:

```text
Exit code: 0
stdout: empty
stderr: empty
```

No downgrade, drop, clean, backfill, or restore command was run on runtime.

## 7. Runtime Revision After

Direct `alembic_version` query:

```text
20260725_12
```

Alembic CLI:

```text
20260725_12 (head)
```

## 8. Schema, Index, and Constraint Verification

Tables present:

- `discord_conversation_sessions`
- `discord_session_turns`

Verified on `discord_conversation_sessions`:

- exact Sprint 1 column set;
- UUID primary key;
- UUID, non-null `backend_conversation_id`;
- nullable `thread_id`;
- TIMESTAMPTZ lifecycle columns;
- `ck_discord_conversation_sessions_status`;
- `ck_discord_conversation_sessions_origin`;
- `ck_discord_conversation_sessions_visibility`;
- partial unique `uq_discord_active_channel_session`;
- partial unique `uq_discord_active_thread_session`;
- canonical lookup index;
- backend-conversation lookup index.

Verified on `discord_session_turns`:

- exact Sprint 1 FIFO column set;
- UUID primary key;
- UUID `session_id`;
- FK to `discord_conversation_sessions.id`;
- `ON DELETE CASCADE` from session to turns;
- `ck_discord_session_turns_status`;
- `ck_discord_session_turns_positive_sequence`;
- unique `(session_id, discord_message_id)`;
- unique `(session_id, sequence_number)`;
- partial unique one-running-turn index;
- dispatch index.

One verification wrapper initially exited non-zero after printing all checks as true because it mistakenly treated the valid CLI exit code integer `0` as a false boolean. No database write occurred in that wrapper. The same catalog checks were immediately rerun with the corrected assertion and passed with exit 0.

Rows after migration:

```text
discord_conversation_sessions = 0
discord_session_turns = 0
```

The migration did not synthesize a Discord session, turn, or backend conversation.

## 9. Row Counts After

| Table | Before | After | Changed |
|---|---:|---:|---|
| `conversations` | 6 | 6 | No |
| `messages` | 30 | 30 | No |
| `memories` | 0 | 0 | No |
| `jobs` | 0 | 0 | No |
| `outbox_events` | 0 | 0 | No |

All required legacy counts are unchanged.

## 10. Health and Regression Checks

Live read-only checks:

| Check | Result |
|---|---|
| `GET /health` | HTTP success, `status=ok` |
| PostgreSQL health | `ok` |
| Redis health | `ok` |
| Qdrant health | `ok` |
| Ollama health | `ok` |
| Outbox dispatcher health | `ok` |
| Cleanup worker health | `ok` |
| `GET /conversations` | HTTP success, 6 conversations |
| `GET /ui/` | HTTP 200, HTML UI served |
| `PostgresAuxiliaryStore.healthcheck()` | `true` |
| Repository/model imports | Passed |
| Runtime Discord session count | 0 |
| Runtime Discord turn count | 0 |

The health payload reported the OCR/index workers as unavailable, but the service's required components were all `ok` and the top-level health status was `ok`. This worker observation is unrelated to the additive session schema migration.

OpenAPI checks:

- `app.openapi()` generated from the current reviewed source contains `POST /api/discord/sessions/resolve`.
- The already-running live API process does not yet expose that route in its cached/live OpenAPI document, showing that it has not reloaded/deployed the Sprint 1 backend source.
- The API process was not restarted in this schema-only gate.
- The resolver endpoint was not called on runtime, so no cleanup transaction was necessary.

No Qdrant mutation, Redis mutation, model generation, model download, test-data insertion, or runtime conversation mutation was performed. `/health` only used component health/ping checks.

## 11. Bot Cutover Status

Bot cutover: **not performed**.

Verified source state:

- `discord_bot/main.py` still defines the in-memory `conversations: dict[str, str]`.
- The current bot path still uses the legacy `conversation_key(guild_id, channel_id, user_id)`.
- `discord_bot/main.py` does not call `resolve_discord_session()`.
- Only the previously implemented client method exists in `discord_bot/api_client.py`.

No bot process, bot configuration, token, mapping dictionary, thread handling, or message flow was changed during this gate.

## 12. Remaining Work

The runtime database schema is ready, but the following are deliberately outside this gate:

1. controlled reload/deployment of the reviewed Sprint 1 backend source so the live API process exposes the resolver route;
2. durable FIFO consumer/lease/retry implementation;
3. Discord parent-channel/thread/forum canonicalization in the bot;
4. bot cutover from the RAM/per-user mapping;
5. rule filtering, extraction, `qwen3.5:2b`, structured memory, rolling summaries, and Qdrant memory retrieval.

Backend source deployment must not be confused with bot cutover. The resolver can be exposed without calling it from the bot, but any later operational step must keep the approved scope separation.

## 13. Final Decision

# SPRINT 1 RUNTIME SCHEMA READY

Decision basis:

- fresh backup and SHA-256 succeeded;
- backup catalog validation succeeded;
- runtime migration to `20260725_12` succeeded;
- Alembic reports the new head;
- required tables, columns, CHECK constraints, partial unique indexes, FIFO constraints, FK, and cascade are present;
- new Discord tables remain empty;
- all legacy row counts are unchanged;
- live health, conversation API, and Web UI checks passed;
- the bot was not cut over;
- no Discord Memory feature beyond the Sprint 1 schema was activated.

This decision applies only to the Sprint 1 runtime database schema. It does not claim that the complete Discord Memory workflow or bot cutover is active.
