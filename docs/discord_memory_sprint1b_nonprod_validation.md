# Non-Production Discord FIFO Validation Gate

Date: 2026-07-25 (Asia/Saigon)  
Gate status: stopped during non-production identity preflight

## 1. Test Environment

The live backend environment was available and healthy:

```text
Backend: http://127.0.0.1:8000
Runtime PostgreSQL database: local_ai_core
Runtime Alembic revision: 20260725_13
```

No dedicated non-production Discord bot, guild, or allowed channel set could
be identified from repository configuration or process/user/machine
environment variable names.

The repository `.env` contains only the generic Discord keys:

```text
DISCORD_TOKEN
DISCORD_CLIENT_ID
DISCORD_INVITE_URL
```

There is no separately named test token, test guild ID, text-channel ID,
thread ID, forum-post ID, or test allowlist. The generic token was not read,
printed, classified, or used because it cannot safely be assumed to be a
non-production credential.

Consequently, no Discord test environment was used in this gate.

## 2. Isolation and Token Handling

The required isolation could not be established.

Verified facts:

- no `DISCORD_TEST_*` source configuration exists;
- no `DISCORD_TEST_*` process, user, or machine environment variable exists;
- source has no guild/channel allowlist;
- only the generic `.env` token key exists;
- production feature flag remains unset;
- no Discord bot process is running.

No token or credential value was printed or written to this document. The
generic token was not passed to a process. No bot process was started.

Because source has no temporary allowlist, a future validation bot must be
isolated through a dedicated Discord application installed only in a test
guild, with Discord permissions restricted to the approved test channels.

## 3. Runtime Preflight

Read-only preflight passed:

| Check | Result |
|---|---|
| Runtime database | `local_ai_core` |
| Runtime revision | `20260725_13` |
| `GET /health` | HTTP 200, `status=ok` |
| PostgreSQL | `ok` |
| Redis | `ok` |
| Qdrant | `ok` |
| Ollama | `ok` |
| Production persistent-session flag | Unset; effective default `false` |
| Discord bot process count | 0 |
| Git revision | `d18c73221c1e8490a4e9fb32060526221c2ee4ee` |

Live OpenAPI contains all required routes:

```text
POST /api/discord/sessions/resolve
POST /api/discord/sessions/{session_id}/turns
POST /api/discord/sessions/turns/{turn_id}/execute
POST /api/discord/sessions/turns/{turn_id}/complete
POST /api/discord/sessions/turns/{turn_id}/fail
```

Runtime baseline:

| Table | Rows before gate |
|---|---:|
| `conversations` | 6 |
| `messages` | 30 |
| `memories` | 0 |
| `jobs` | 0 |
| `outbox_events` | 0 |
| `discord_conversation_sessions` | 0 |
| `discord_session_turns` | 0 |

No Discord POST endpoint was called during preflight.

## 4. Session Resolution Results

Not executed.

Blocker:

```text
No verified dedicated test bot token + test guild + approved channel.
```

No session, backend conversation, or turn was created.

## 5. Canonical Location Results

Live Discord validation was not executed for:

- text channel;
- public thread;
- forum post;
- private thread;
- DM rejection.

The automated canonicalization results from Sprint 1B remain prior evidence,
but they do not replace the required Discord test-environment validation in
this gate.

## 6. FIFO Same-Session Results

Not executed. No three-message, two-user Discord sequence was sent.

Therefore this gate did not collect database and Discord-delivery evidence for:

- sequence 1/2/3;
- one running turn per session;
- completion/delivery ordering;
- shared backend conversation;
- absence of duplicate active sessions.

## 7. Parallel-Session Results

Not executed. No two-channel or two-thread non-production test target was
available.

## 8. Idempotency Results

Not executed against the live non-production path. No runtime API harness was
used because a test session could not first be established through an approved
Discord test environment.

## 9. Retry, Lease, and Recovery Results

No live fault injection was performed.

The Sprint 1B PostgreSQL tests previously verified retry, lease expiry, stale
recovery, ownership loss, terminal failure, and response reuse. Those remain
code/test-database evidence only and are not counted as this gate's required
non-production result.

## 10. Orphan Recovery Result

Not executed. No conversation was deleted or modified.

In particular, no legacy or production conversation was used for orphan
testing.

## 11. Restart Persistence Result

Not executed because no dedicated test bot process could be safely started.

No production bot was started or restarted.

## 12. Multi-User Shared-Context Result

Not executed. Two authorized non-production Discord participants and an
approved shared channel were not identified.

## 13. Database Evidence Summary

Only read-only baseline evidence was collected:

```text
revision                      20260725_13
conversations                 6
messages                     30
memories                      0
jobs                          0
outbox_events                 0
discord_conversation_sessions 0
discord_session_turns          0
```

Because no test rows exist, there are no test session IDs, conversation IDs,
sequences, attempts, leases, response fields, or completion timestamps to
report.

## 14. Cleanup Result

No cleanup was required:

- no bot was started;
- no resolver/turn endpoint was called;
- no test conversation/session/turn was created;
- no runtime row was modified or deleted.

## 15. Automated Test Results

No automated test suite was run in this gate after the mandatory stop
condition was reached. This follows the instruction to stop when a dedicated
test bot/server/channel cannot be identified.

The earlier Sprint 1B document records passing PostgreSQL and bot/client unit
tests, but those historical results are not substituted for a current
non-production Discord validation.

## 16. Production Status

Production safety remained intact:

```text
DISCORD_PERSISTENT_SESSIONS_ENABLED = unset
effective default                  = false
production bot process             = not running
production bot restart             = no
production bot cutover             = no
```

No source, migration, `.env`, backend process, PostgreSQL data, Redis, Qdrant,
Ollama model, or legacy bot path was changed.

## 17. Remaining Blockers

Prepare the following before resuming this gate:

1. A dedicated non-production Discord application and bot token. Supply it
   only to the test bot process as:

   ```text
   DISCORD_TOKEN=<dedicated test bot token>
   DISCORD_CLIENT_ID=<dedicated test application ID>
   DISCORD_PERSISTENT_SESSIONS_ENABLED=true
   LOCAL_AGENT_BASE_URL=http://127.0.0.1:8000
   ```

   Do not add the token to Git or replace the generic production `.env` value.

2. A dedicated test guild where that bot application is installed. The bot
   must not be installed in a production guild for this gate.

3. Explicit approved IDs, communicated without placing credentials in Git:

   ```text
   test guild ID
   text channel ID
   second channel ID for parallel validation
   public thread ID and parent channel ID
   forum post/thread ID and forum parent ID
   optional private thread ID and parent ID
   ```

4. At least two authorized non-production users for shared-session and
   multi-user context validation.

5. Discord permissions restricted to the approved test guild/channels:
   view channel, read message history, send messages, use application
   commands, and thread permissions needed by the selected cases.

6. An agreed test-data prefix and cleanup window so every created session,
   turn, and backend conversation can be identified exactly before deletion.

The current source does not consume `DISCORD_TEST_GUILD_ID` or
`DISCORD_TEST_CHANNEL_ID`. Until an allowlist is implemented in a separately
authorized source change, isolation must be enforced by using a dedicated bot
application installed only in the test guild with restricted Discord
permissions.

After these blockers are closed, rerun this gate from the beginning,
including automated tests on `POSTGRES_TEST_URL`, live restart persistence,
multi-user/FIFO checks, guarded fault injection, database evidence, and
guarded cleanup.

## 18. Final Decision

```text
NON-PRODUCTION FIFO VALIDATION NOT READY
```

The backend and runtime schema are ready, but the required non-production
Discord identity and approved guild/channel targets are absent. Persistent
session behavior was therefore not exercised through a bot, and none of the
live FIFO, parallelism, idempotency, recovery, orphan, restart, or multi-user
acceptance conditions can be claimed.
