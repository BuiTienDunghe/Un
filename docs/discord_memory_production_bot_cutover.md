# Controlled Production Bot Cutover

Initial activation: 2026-07-25  
Canary validation update: 2026-07-26 (Asia/Saigon)

Scope: run the primary Discord bot on the persistent shared-session/FIFO path
while retaining the legacy path for rollback. No message content, token,
credential, full database URL, or full Discord ID is included below.

## 1. Preflight

The original activation gates passed:

| Check | Result |
|---|---|
| Backend `/health` | HTTP 200, `status=ok` |
| Runtime revision | `20260725_13` |
| Resolver/enqueue/execute/complete/fail routes | Live |
| Discord sessions before activation | 0 |
| Discord turns before activation | 0 |
| Bot process before activation | Not running |
| Token/client ID configured | Yes, boolean checks only |
| Legacy RAM/per-user path | Retained |

Baseline:

```text
conversations                  6
messages                      30
memories                       0
jobs                           0
outbox_events                  0
discord_conversation_sessions  0
discord_session_turns           0
```

Git rollback point:

```text
branch: main
revision: d18c73221c1e8490a4e9fb32060526221c2ee4ee
working tree: already dirty with reviewed Sprint 1/Sprint 1B files
```

No schema migration or database backup was needed for the bot-only cutover.

## 2. Bot Command and PID

The Docker launcher was not used because it performs Compose build/up. The bot
was started directly through the project virtual environment:

```text
Working directory:
C:\Users\dungbt06\Ún promax\local-ai-core

dotenv -f .env run --no-override --
  .venv\Scripts\python.exe -m discord_bot.main
```

The command contains no token. `dotenv` loads the existing local credential
inside the bot process only.

Process-only configuration:

```text
DISCORD_PERSISTENT_SESSIONS_ENABLED=true
LOCAL_AGENT_BASE_URL=http://127.0.0.1:8000
POSTGRES_TEST_URL absent
```

Initial process tree:

```text
loader root PID 23480
active bot PID  25728
```

Restarted process tree:

```text
loader root PID 44764
active bot PID  37904
```

The restarted bot is connected and running with the persistent flag still
`true`. The production `.env` remains unchanged and does not contain the
feature flag.

## 3. Feature Flag

```text
production .env feature flag = unset
running bot feature flag     = true
rollback value               = false
```

Only the bot process tree has the true value. Backend, workers, PostgreSQL,
Redis, Qdrant, and Ollama were not restarted.

## 4. Session and Turn Evidence

Five real Discord canary turns were observed. Identifiers are represented only
by non-reversible short SHA-256 fingerprints:

```text
session fingerprint               03ed919c62
canonical location fingerprint    e6500a71db
backend conversation fingerprint  c9d6317449
location type                     text channel
```

Database evidence:

```text
active sessions for location      1
duplicate active locations        0
backend conversation exists       true
backend conversation message rows 10
turn count                        5
sequence numbers                  1, 2, 3, 4, 5
turn status                       completed x5
```

Every completed turn has a non-empty response, non-null completion timestamp,
`attempt_count=1`, and cleared worker, lease, and heartbeat fields.

No duplicate message key, duplicate sequence, running turn, stale lease,
orphan session, retrying turn, or stuck turn exists.

Current counts:

```text
conversations                  7
messages                      40
memories                       0
jobs                           0
outbox_events                  0
discord_conversation_sessions  1
discord_session_turns           5
```

## 5. Multi-User Result

Passed for the initial text-channel canary.

Discord REST GET inspection attributed the four inputs to two distinct
non-bot author fingerprints:

```text
author A: e25aff4dec
author B: d23ad604dc

sequence 1 -> A
sequence 2 -> B
sequence 3 -> B
sequence 4 -> A
```

All four turns use the same session and backend conversation fingerprints.
No user-specific session or backend conversation was created.

Author IDs were processed only in memory. Their full values and message
content were not written to logs or this report.

## 6. FIFO Result

Passed for five turns in one shared session.

PostgreSQL evidence:

- sequence is contiguous from 1 through 5;
- creation timestamps are monotonic by sequence;
- completion timestamps are monotonic by sequence;
- every N+1 start is after turn N reached terminal completion;
- at most one turn was running in the session;
- all ownership and lease state is cleared after completion;
- all attempts are 1;
- there are no duplicate message or sequence keys.

Discord read-only evidence:

- every turn maps to exactly one bot response;
- every Discord response matches the persisted response;
- Discord delivery order matches sequence order;
- delivery timestamps precede database completion timestamps;
- no duplicate response was detected.

The database and Discord evidence agree; the conclusion is not based only on
Discord display order.

## 7. Restart Persistence

The bot process restart was completed after the four turns.

Before restart:

```text
session fingerprint               03ed919c62
backend conversation fingerprint  c9d6317449
latest sequence                   4
old loader PID                    23480
old active bot PID                25728
```

The complete old bot process tree was stopped. The backend and all persistence
services remained running.

After restart:

```text
new loader PID       44764
new active bot PID   37904
persistent flag      true
backend target       local runtime backend
Discord connection   successful
startup errors       0
```

After an initial pending observation window, a valid post-restart invocation
was received in the same channel. The final read-only snapshot found:

```text
session fingerprint               03ed919c62
backend conversation fingerprint  c9d6317449
active sessions                   1
turn count                        5
latest sequence                   5
conversations                     7
messages                         40
```

Turn 5 reused the pre-restart session and backend conversation. No additional
active session or backend conversation was created. The turn completed with a
non-empty response, non-null completion timestamp, `attempt_count=1`, and
cleared worker, lease, and heartbeat fields.

The process restart succeeded and created no duplicate session by itself.
Persistence reuse after restart is confirmed.

Discord REST inspection found the source invocation and exactly one bot reply.
The reply references the source message, and its content fingerprint matches
the persisted response fingerprint. No duplicate delivery was found.

## 8. Health Checks

After canary and restart:

| Check | Result |
|---|---|
| Backend `/health` | HTTP 200, `status=ok` |
| PostgreSQL | `ok` |
| Redis | `ok` |
| Qdrant | `ok` |
| Ollama | `ok` |
| Runtime revision | `20260725_13` |
| Legacy Web UI | HTTP 200 |
| Bot connection before restart | Successful |
| Bot connection after restart | Successful |
| Restarted bot stable | Yes |
| Active bot PID | `37904` |
| Running bot feature flag | `true` |
| Discord Gateway TCP connection | Established |

No memory or Qdrant behavior was changed.

## 9. Errors and Retries

```text
traceback/error/401/429/reconnect-loop patterns 0
duplicate active sessions                       0
duplicate backend conversation mappings         0
duplicate message keys                          0
duplicate sequence keys                         0
duplicate Discord responses                     0
FIFO violations                                 0
running turns                                   0
stale running turns                             0
orphan sessions                                 0
retry turns                                     0
maximum attempt_count                           1
```

No rollback condition was detected.

Two operational command issues did not affect runtime:

1. An initial combined `Start-Process` command was rejected by command policy
   before activation; the bot had not started.
2. The first restart-stop PowerShell command used a reserved variable name and
   exited before stopping any process. The corrected exact-PID command then
   stopped the tree and restart succeeded.

Neither issue changed database state or exposed a credential.

## 10. Rollback Status

```text
rollback invoked         no
rollback readiness       prepared
rollback reason detected none
```

Rollback procedure:

```text
1. Stop the bot process tree rooted at PID 44764.
2. Start the replacement bot with DISCORD_PERSISTENT_SESSIONS_ENABLED=false.
3. Keep LOCAL_AGENT_BASE_URL=http://127.0.0.1:8000.
4. Use the same dotenv --no-override command.
5. Do not delete persistent sessions, turns, or backend conversations.
```

The legacy RAM/per-user path remains available when the flag is false.

## 11. Remaining Follow-Up

All mandatory production cutover acceptance items are satisfied. The final
read-only validation observed:

```text
runtime revision                20260725_13
backend health                  ok
bot PID 37904                   running
persistent feature flag         true
Discord Gateway connection      established
active sessions                 1
turns                           5
latest sequence                 5
running turns                   0
duplicate active locations      0
orphan sessions                 0
FIFO violations                 0
duplicate Discord responses     0
retry turns                     0
```

No restart, database mutation, Discord send, or rollback was performed during
this final validation attempt.

Thread, forum-post, private-thread, and DM checks remain optional follow-up for
this first production cutover.

If a duplicate, stuck lease, retry loop, out-of-order response, orphan loop, or
bot crash/reconnect loop appears, execute the prepared rollback and retain all
persistent rows for diagnosis.

## 12. Final Decision

```text
PRODUCTION BOT CUTOVER PASSED
```

Initial same-channel reuse, two-user sharing, five-turn FIFO, response
ordering, ownership cleanup, duplicate prevention, and health checks passed.
The bot also restarted successfully with the persistent flag still enabled.

The valid post-restart invocation reused session fingerprint `03ed919c62` and
backend conversation fingerprint `c9d6317449`, advanced sequence from 4 to 5,
completed successfully, and produced exactly one Discord response. No rollback
condition was detected.
