# Discord Memory Sprint 1 — Persistent Session Foundation

Implementation date: 2026-07-25

## Scope

Sprint 1 implements the backend-owned persistent Discord session foundation only. It does not implement rule filtering, raw Discord message storage, memory extraction, `qwen3.5:2b`, structured long-term memory, rolling summaries, Qdrant memory retrieval, or a model turn worker.

No legacy Discord conversation was identified, modified, deleted, or backfilled.

## Migration Revision

New Alembic revision:

```text
20260725_12
```

Migration file:

```text
backend/alembic/versions/20260725_12_discord_persistent_sessions.py
```

Parent revision:

```text
20260719_11
```

Alembic has one head:

```text
20260725_12 (head)
```

The migration was upgraded, downgraded, and upgraded again successfully on `local_ai_core_test`. Legacy table counts on the test database remained unchanged across both directions.

## Implemented Schema

### `discord_conversation_sessions`

Columns:

| Column | Type / nullability |
|---|---|
| `id` | UUID primary key |
| `guild_id` | TEXT NOT NULL |
| `channel_id` | TEXT NOT NULL |
| `thread_id` | TEXT NULL |
| `backend_conversation_id` | UUID NOT NULL |
| `origin` | TEXT NOT NULL, default `discord` |
| `visibility` | TEXT NOT NULL, default `internal` |
| `status` | TEXT NOT NULL, default `active` |
| `started_at` | TIMESTAMPTZ NOT NULL |
| `last_active_at` | TIMESTAMPTZ NOT NULL |
| `closed_at` | TIMESTAMPTZ NULL |
| `orphaned_at` | TIMESTAMPTZ NULL |
| `created_at` | TIMESTAMPTZ NOT NULL |
| `updated_at` | TIMESTAMPTZ NOT NULL |

CHECK constraints:

```text
status IN ('active','closed','expired','orphaned','deleted')
origin = 'discord'
visibility IN ('internal','admin')
```

Canonical active-session uniqueness uses two PostgreSQL partial unique indexes:

```text
uq_discord_active_channel_session
  UNIQUE (guild_id, channel_id)
  WHERE status = 'active' AND thread_id IS NULL

uq_discord_active_thread_session
  UNIQUE (guild_id, channel_id, thread_id)
  WHERE status = 'active' AND thread_id IS NOT NULL
```

This explicitly handles PostgreSQL NULL semantics for non-thread channels.

`conversations.id` remains `VARCHAR(128)` because it stores legacy opaque identifiers. The new mapping column follows the approved Sprint 1 contract and is UUID. A cross-type foreign key was not added. The service creates a UUID conversation as its canonical string and verifies its existence inside the resolver transaction. This deliberate absence of a hard FK also permits the required orphan detection and recovery flow.

### `discord_session_turns`

Columns:

| Column | Type / nullability |
|---|---|
| `id` | UUID primary key |
| `session_id` | UUID NOT NULL, FK to `discord_conversation_sessions.id` with `ON DELETE CASCADE` |
| `discord_message_id` | TEXT NOT NULL |
| `sequence_number` | BIGINT NOT NULL |
| `status` | TEXT NOT NULL, default `queued` |
| `available_at` | TIMESTAMPTZ NOT NULL |
| `started_at` | TIMESTAMPTZ NULL |
| `completed_at` | TIMESTAMPTZ NULL |
| `error` | TEXT NULL |
| `created_at` | TIMESTAMPTZ NOT NULL |
| `updated_at` | TIMESTAMPTZ NOT NULL |

FIFO foundation constraints:

```text
status IN ('queued','running','completed','failed','cancelled')
sequence_number > 0
UNIQUE (session_id, discord_message_id)
UNIQUE (session_id, sequence_number)
UNIQUE (session_id) WHERE status = 'running'
```

The last partial index prevents two running turns for one session. A dispatch index covers `status`, `available_at`, `session_id`, and `sequence_number`.

## Canonical Session Key

The backend normalizes leading/trailing whitespace and uses:

```text
guild_id + channel_id + thread_id
```

Rules:

- Text or announcement channel: current channel in `channel_id`, `thread_id = NULL`.
- Discord thread: parent channel in `channel_id`, current thread in `thread_id`.
- Forum post: forum channel in `channel_id`, forum post/thread in `thread_id`.
- Private thread: allowed as a conversation session; no long-term memory feature is enabled.
- DM: rejected with `DISCORD_DM_UNSUPPORTED`.
- `user_id` is not accepted by the endpoint and is not part of the key.

The endpoint cannot infer Discord channel type from IDs alone. The future bot cutover must supply parent/thread identifiers according to this contract.

## API Contract

Endpoint:

```text
POST /api/discord/sessions/resolve
```

Request:

```json
{
  "guild_id": "123",
  "channel_id": "456",
  "thread_id": null
}
```

Response:

```json
{
  "session_id": "UUID",
  "backend_conversation_id": "UUID",
  "created": false,
  "status": "active"
}
```

Validation:

- identifiers are trimmed and cannot be empty;
- maximum identifier length is 64 characters;
- extra fields, including `user_id`, are rejected;
- `guild_id = null` returns HTTP 400 with `DISCORD_DM_UNSUPPORTED`;
- callers cannot select `origin`, `visibility`, or a non-Discord source.

## Repository and Service

Implemented files:

- `backend/app/postgres/discord_repositories.py`
- `backend/app/services/discord_session_service.py`
- `backend/app/schemas/discord_schema.py`
- `backend/app/routers/discord_sessions.py`

`DiscordSessionRepository` provides:

- canonical active-session lookup with optional `FOR UPDATE`;
- backend conversation existence checks;
- atomic conversation/session creation primitives;
- `last_active_at` updates;
- orphan transition;
- idempotent FIFO turn enqueue with per-session sequence allocation.

`DiscordSessionService.resolve()` provides:

1. normalize and validate the canonical location;
2. lock and read the active mapping in a short transaction;
3. return and touch an existing valid session;
4. otherwise create the UUID backend conversation row and Discord mapping in the same transaction;
5. on a partial-unique conflict, roll back the losing conversation and read the committed winner;
6. retry only bounded concurrent state changes.

PostgreSQL is the source of truth. No process lock or dictionary is used by the backend resolver.

## Transaction and Concurrency Strategy

Conversation creation and session mapping insertion share one `sessionmaker.begin()` transaction. A loser in a concurrent insert receives the partial unique-index conflict; rollback removes both its mapping and newly created backend conversation. It then reads the winner in a new short transaction.

Existing rows are selected with `FOR UPDATE` before `last_active_at` or orphan state changes. The database partial indexes remain the final correctness boundary across processes and restarts.

No PostgreSQL transaction is held during model inference. No `asyncio.Lock` is used for correctness.

The concurrency test starts eight threads at a barrier and resolves the same location simultaneously. All eight calls return one `session_id` and one `backend_conversation_id`; exactly one call reports `created=true`, and PostgreSQL contains one active mapping and one valid conversation.

## Orphan Handling

When an active mapping exists but `conversations` no longer contains its UUID string:

1. lock the active mapping;
2. set it to `orphaned`;
3. set `orphaned_at`;
4. create a new UUID backend conversation;
5. create the replacement active mapping in the same transaction;
6. return the replacement.

The old ID is not retried indefinitely. No summary or legacy-history transfer is attempted in Sprint 1.

## Web UI Isolation

`PostgresAuxiliaryStore.list_conversations()` now excludes conversations referenced by any `origin='discord'` session using a PostgreSQL `NOT EXISTS` query.

Consequences:

- new Discord backend conversations do not appear in `GET /conversations`;
- existing Web UI conversations remain listable, readable, and deletable;
- existing `/chat` and `/memory` behavior is unchanged;
- no column or data backfill was added to legacy `conversations`.

If a Discord backend conversation is deleted through another path, the next resolver call exercises the orphan transition.

## Discord Client and Runtime Cutover Status

`discord_bot/api_client.py` now provides:

```text
LocalAgentClient.resolve_discord_session(guild_id, channel_id, thread_id)
```

It validates identifiers, posts the resolver contract, preserves existing JWT refresh behavior, and validates the response.

The Discord bot runtime was intentionally not cut over in Sprint 1. `discord_bot/main.py` still uses the existing RAM/per-user mapping until durable turn processing can safely serialize shared-session chat. Calling the resolver and immediately sending shared `/chat` requests without consuming `discord_session_turns` would create a half-migrated concurrent-history behavior.

Therefore:

- the persistent backend source of truth and client method are ready;
- no mixed old/new runtime path was introduced;
- bot parent-channel/thread normalization, resolver use, turn enqueue/claim, and removal of the RAM mapping remain cutover work.

## FIFO Foundation

`DiscordSessionRepository.enqueue_turn()`:

- locks the parent session row;
- returns the existing turn for a duplicate Discord message ID;
- allocates `max(sequence_number) + 1` within the locked session;
- starts each session at sequence 1 independently;
- creates only `queued` rows.

The schema prevents duplicate sequence numbers, duplicate Discord message IDs, invalid statuses, non-positive sequences, and two `running` turns in one session.

The worker that claims queued turns, invokes `/chat`, handles leases/retries, and transitions completion is not implemented in Sprint 1.

## Tests Run

All mutation tests used `POSTGRES_TEST_URL` targeting `local_ai_core_test`, not runtime database `local_ai_core`.

Migration checks:

- test DB revision before upgrade: `20260719_11`;
- `alembic upgrade head`: passed;
- `alembic current`: `20260725_12 (head)`;
- legacy counts unchanged;
- safe downgrade to `20260719_11`: passed with new tables absent;
- re-upgrade to `20260725_12`: passed with new tables present;
- legacy counts unchanged across downgrade/re-upgrade.

Sprint 1 focused tests cover:

- schema types, nullability, CHECK/FK/unique/partial indexes;
- same-channel idempotency and defaults;
- channel/guild/thread/forum/private-thread boundaries;
- DM and invalid input rejection;
- orphan transition and replacement;
- duplicate active channel and thread constraints;
- real multithreaded concurrent resolution;
- Web UI list isolation;
- FIFO sequence independence/idempotency/status/one-running constraints;
- HTTP resolver contract;
- Discord API client resolver method.

Results:

```text
Sprint 1 focused tests: 27 passed, 0 failed, 0 skipped, 2 warnings
Required regression selection: 46 passed, 0 failed, 0 skipped, 2 warnings
Final combined Sprint 1 + regression run: 49 passed, 0 failed, 0 skipped, 2 warnings
```

Warnings are the existing Starlette/httpx TestClient deprecation and Python `audioop` deprecation from the Discord dependency.

The known `_Ocr` fixture incompatibility and optional Qdrant validation test documented in the readiness report were not modified because Sprint 1 did not cause them.

## Runtime Migration Status

Runtime migration was **not applied**.

Read-only verification after implementation:

| Item | Runtime value |
|---|---|
| Database | `local_ai_core` |
| Alembic revision | `20260719_11` |
| Discord tables | none |
| `conversations` | 6 |
| `messages` | 30 |
| `memories` | 0 |
| `jobs` | 0 |
| `outbox_events` | 0 |

The readiness backup remains present and its SHA-256 still matches:

```text
96b5b12b9760e2f5d5e79292cfe700245628b109eed3e076e57119495ec5ebc9
```

Runtime migration requires an explicit operational step with the approved runtime `DATABASE_URL`:

```text
python -m alembic current
python -m alembic upgrade head
python -m alembic current
```

After applying, verify the two new tables/indexes, confirm the five legacy row counts remain `6/30/0/0/0`, and run the runtime health check. Do not deploy the modified backend code before its required schema is present.

## Differences from Workflow V5

The following differences are intentional Sprint 1 scope reductions or consequences of the current legacy schema:

1. Only `discord_conversation_sessions` and `discord_session_turns` are added. Guild/channel policy tables, raw messages, summaries, structured memories, proposals, sources, jobs, and Qdrant indexing remain later work.
2. `backend_conversation_id` is UUID per the final Sprint 1 request, while legacy `conversations.id` remains `VARCHAR(128)`; therefore no incompatible cross-type FK was added.
3. FIFO durable schema/repository constraints are implemented, but no model turn worker is implemented.
4. The Discord client resolver method is implemented, but bot runtime cutover is deferred to avoid unsafe shared-session inference before FIFO consumption exists.
5. No legacy Discord conversation is backfilled or treated as Workflow V5 data.

## Remaining Work

Before the Discord runtime cutover:

1. derive canonical parent channel/thread/forum identifiers in `discord_bot/main.py`;
2. reject DM commands/messages before resolver calls;
3. enqueue each Discord message into `discord_session_turns`;
4. implement durable claim/lease/retry/completion transitions and strict per-session FIFO consumption;
5. connect the claimed turn to `/chat` using `backend_conversation_id`;
6. handle a conversation-not-found response by re-resolving once;
7. remove the in-memory per-user dictionary and legacy hash key only when the new path is complete;
8. add restart/multi-instance end-to-end tests for the full bot cutover.

These items do not include rule filtering, extraction, structured memory, rolling summary, or Qdrant memory retrieval.
