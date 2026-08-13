# Discord Memory Sprint 1B — Durable FIFO Turn Processing

Date: 2026-07-25  
Scope: code and isolated PostgreSQL test database only  
Production bot cutover: not performed

## 1. FIFO Architecture

Sprint 1B adds a durable execution lifecycle on top of the Sprint 1
`discord_conversation_sessions` and `discord_session_turns` tables.
PostgreSQL remains the correctness boundary.

The lifecycle is:

```text
queued -> running -> completed
queued -> cancelled
running -> queued     (retry)
running -> failed     (permanent or exhausted)
```

One partial unique index continues to enforce at most one `running` turn per
session. A turn remains `running` after the model response is stored and is
marked `completed` only after the bot acknowledges successful Discord
delivery. This prevents response N+1 from being delivered before response N.
Different session rows provide independent locking boundaries, so unrelated
sessions can run concurrently.

The execution boundary is:

```text
claim transaction -> commit
-> ChatService/model call outside a PostgreSQL transaction
-> persist response transaction -> commit
-> Discord delivery
-> completion transaction -> commit
```

No PostgreSQL transaction is held during HTTP/model inference or Discord
delivery.

## 2. Canonical Location Rules

`discord_bot/session_location.py` is the single bot-side canonicalization
function. It never accepts or uses a user ID.

| Discord location | `guild_id` | `channel_id` | `thread_id` |
|---|---|---|---|
| Text channel | guild | channel | `null` |
| Announcement channel | guild | channel | `null` |
| Public thread | guild | parent channel | thread |
| Private thread | guild | parent channel | thread |
| Forum post | guild | forum parent | post/thread |
| DM | unsupported | — | — |

A thread without a resolvable parent is rejected. Private-thread session
context is supported, but Sprint 1B does not enable long-term memory.

## 3. Schema and Revision

New Alembic revision:

```text
20260725_13
down_revision = 20260725_12
```

Revision `20260725_13_discord_turn_leases.py` only extends
`discord_session_turns` with FIFO execution fields:

```text
request_text TEXT NOT NULL
system_prompt TEXT NULL
response_text TEXT NULL
model_used VARCHAR(255) NULL
worker_id TEXT NULL
lease_expires_at TIMESTAMPTZ NULL
heartbeat_at TIMESTAMPTZ NULL
attempt_count INTEGER NOT NULL DEFAULT 0
max_attempts INTEGER NOT NULL DEFAULT 3
```

It also adds:

- `attempt_count >= 0` CHECK;
- `max_attempts > 0` CHECK;
- partial stale-lease index for `status = 'running'`.

The Sprint 1 unique constraints remain unchanged:

- unique `(session_id, discord_message_id)` for idempotent enqueue;
- unique `(session_id, sequence_number)`;
- partial unique `session_id` where `status = 'running'`;
- turn-to-session foreign key with `ON DELETE CASCADE`.

The migration contains no Discord legacy backfill, conversation update, or
data deletion. It was applied only to `local_ai_core_test`. Runtime remains at
`20260725_12`.

## 4. Enqueue Strategy

`DiscordTurnService.enqueue()` and
`DiscordSessionRepository.enqueue_turn()` accept server-controlled:

```text
session_id
discord_message_id
message
system_prompt (optional)
```

The repository locks the parent `discord_conversation_sessions` row with
`SELECT ... FOR UPDATE`, checks message idempotency, then allocates the next
sequence while holding that lock. `MAX(sequence_number) + 1` is therefore used
only inside per-session row serialization; it is not an unlocked calculation.
The database unique constraints remain the final guard.

The client cannot provide `sequence_number`, `status`, `worker_id`,
`attempt_count`, or lease data.

## 5. Claim and Locking Strategy

Claiming locks the parent session row, then selects the smallest unfinished
turn ordered by `sequence_number`.

A claim succeeds only when:

- the requested turn is that exact head turn;
- its status is `queued`;
- `available_at` has arrived;
- there is no earlier queued/running turn.

The claim sets `running`, a server-generated ownership token, timestamps,
lease expiry, and increments `attempt_count`. Competing workers for the same
session serialize on the parent row; the one-running partial index is an
additional database guard. The implementation does not use `asyncio.Lock`
and does not use `SKIP LOCKED` to skip a session head. Different sessions lock
different parent rows and remain parallel.

## 6. Lease, Heartbeat, and Recovery

An owner receives an opaque server-generated execution token. The client
cannot choose `worker_id`.

- heartbeat succeeds only for the current owner of an unexpired `running`
  lease;
- model execution runs a heartbeat loop at one third of the lease duration;
- completion, response persistence, and failure require current ownership;
- stale recovery locks expired running rows and revokes the old owner;
- a recoverable turn returns to `queued` with the same sequence;
- stored model output is retained, so a Discord delivery retry does not call
  the model again;
- exhausted turns become terminal `failed`.

`execute()` invokes stale recovery before claim. The recovery method is also
available as an explicit service operation for a future dedicated scheduler.

## 7. Failure Policy

The selected terminal-failure policy is:

```text
permanently failed turn
-> status = failed
-> error retained for audit
-> next sequence in the session may continue
```

A retryable failure keeps the same sequence and blocks later turns until it
succeeds or reaches `max_attempts`. A queued message may be `cancelled`.

Discord delivery is part of the ordering boundary. A deleted source message
or expired interaction is handled without crashing the bot: the current turn
is marked permanently failed with a bounded audit message, then the next turn
may proceed. Other delivery failures are retryable.

For an absent backend conversation:

1. the old turn remains running so later old-session turns cannot pass it;
2. the resolver marks the old session orphaned and resolves exactly one new
   active canonical session;
3. the turn is idempotently enqueued on the replacement session;
4. only then is the old turn marked failed.

This ordering prevents a later old-session turn from acquiring an earlier
sequence in the replacement session. No rolling summary is restored in this
sprint.

## 8. Bot Feature Flag

The new configuration is:

```text
DISCORD_PERSISTENT_SESSIONS_ENABLED=false
```

It is documented in `.env.example`. The environment parser defaults to
`false`, and the runtime `.env` does not set it.

When false, `DiscordConversationGateway` uses the unchanged legacy RAM
dictionary and per-user `conversation_key()`. It does not call the resolver or
turn endpoints.

When true, the new code path performs:

```text
canonical location
-> resolve session
-> idempotent enqueue
-> execute/poll FIFO turn
-> send Discord response
-> acknowledge completion
```

The legacy path remains present for cutover rollback. The production bot was
not restarted and was not cut over during Sprint 1B.

## 9. API Contract

Resolver:

```text
POST /api/discord/sessions/resolve
```

`guild_id` and `channel_id` are required non-null strings with length 1–64.
`thread_id` is either null or a string with length 1–64. Identifier strings are
trimmed before validation; null/empty/whitespace-only guild IDs receive HTTP
422. DM support was not added.

Enqueue:

```text
POST /api/discord/sessions/{session_id}/turns
```

Request:

```json
{
  "discord_message_id": "string",
  "message": "string",
  "system_prompt": "optional string"
}
```

Response:

```json
{
  "turn_id": "uuid",
  "session_id": "uuid",
  "sequence_number": 1,
  "status": "queued",
  "created": true
}
```

Internal bot execution endpoints:

```text
POST /api/discord/sessions/turns/{turn_id}/execute
POST /api/discord/sessions/turns/{turn_id}/complete
POST /api/discord/sessions/turns/{turn_id}/fail
```

`execute` atomically claims when eligible and runs chat outside the claim
transaction. `complete` and `fail` require the server-issued execution token.
Heartbeat and raw claim operations are not exposed as client-controlled HTTP
contracts.

## 10. Test Results

Database isolation was checked before mutation:

```text
POSTGRES_TEST_URL database = local_ai_core_test
runtime database          = local_ai_core
```

Migration test:

```text
20260725_12 -> 20260725_13: passed
20260725_13 -> 20260725_12: passed
20260725_12 -> 20260725_13: passed
alembic current: 20260725_13 (head)
```

Focused bot/client tests:

```text
21 passed, 0 failed, 0 skipped, 1 warning
```

Backend Sprint 1/Sprint 1B and related regression:

```text
47 passed, 0 failed, 0 skipped, 1 warning
```

Covered behavior includes:

- resolver null/empty/whitespace validation and non-null OpenAPI schema;
- channel, announcement, public/private thread, forum post, DM, missing parent;
- idempotent and concurrent enqueue with per-session sequence allocation;
- competing claims with one winner and head-of-line blocking;
- concurrent claims in separate sessions;
- delivery acknowledgement ordering;
- heartbeat ownership, stale recovery, retry, max attempts, cancellation;
- permanent-failure continuation policy;
- orphan replacement and preserved replacement ordering;
- feature flag false/true paths and default false;
- legacy chat/conversation API;
- Web UI conversation-list isolation;
- transactional outbox, job stale recovery, and worker concurrency.

Warnings were existing dependency deprecations:

- Starlette TestClient/httpx compatibility warning;
- Python `audioop` deprecation emitted by discord.py.

No test invoked or downloaded `qwen3.5:2b`; chat execution tests used mocks.

## 11. Runtime Activation Status

Read-only verification after tests:

```text
runtime database revision             = 20260725_12
discord_conversation_sessions rows    = 0
discord_session_turns rows             = 0
legacy conversations/messages          = 6 / 30
memories/jobs/outbox_events             = 0 / 0 / 0
runtime feature flag                    = unset (default false)
```

Revision `20260725_13` was not applied to runtime. The live backend was not
reloaded. The production bot was not restarted and remains on the legacy path.
No runtime resolver/turn endpoint was called, and no runtime Discord row was
created.

## 12. Rollback and Cutover Plan

A separate controlled operational gate must:

1. create and verify a fresh runtime PostgreSQL recovery point;
2. apply `20260725_13` to runtime and verify the added fields/index/checks;
3. reload only the backend API and verify the new OpenAPI turn contracts;
4. keep the production flag false while performing read-only health checks;
5. validate the true path in a non-production Discord environment;
6. enable the flag in a controlled production bot cutover;
7. monitor FIFO backlog, stale leases, terminal failures, and orphan events.

Rollback during the observation window is to set the feature flag back to
false and restart only the bot. The legacy dictionary path remains available.
Runtime downgrade is not part of the bot rollback plan, and persistent rows
must not be deleted casually.

## 13. Remaining Work

- Runtime migration gate for `20260725_13`.
- Controlled backend reload gate for the new turn routes.
- Non-production end-to-end Discord validation.
- Dedicated production bot cutover and rollback gate.
- Operational metrics/alerts and, if needed, a standalone periodic stale-turn
  recovery scheduler.
- Legacy-path removal only after the rollback window.

Rule filtering, Qwen3.5:2b extraction, structured long-term memory, rolling
summary, and Qdrant memory retrieval remain explicitly outside Sprint 1B.

## 14. Sprint 1B Completion Decision

```text
SPRINT 1B CODE AND ISOLATED-DATABASE FOUNDATION COMPLETE
PRODUCTION BOT NOT CUT OVER
```

The resolver contract is strict, FIFO concurrency and stale recovery tests
pass, the feature flag defaults to false, and the legacy path remains
operational. Sprint 1B is complete at the code/test-foundation boundary.
Runtime activation is not complete and requires the separate gates listed
above.
