# Sprint 1B Controlled Backend Reload Gate

Date: 2026-07-25 (Asia/Saigon)  
Scope: reload only the directly running Windows Uvicorn backend so the
reviewed Sprint 1B source routes become live.

## 1. Runtime Mode

The backend was running directly on Windows with the project virtual
environment. It was not running as a Docker Compose API service.

```text
Working directory:
C:\Users\dungbt06\Ún promax\local-ai-core\backend

Command:
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The venv Python executable is a launcher whose child system Python process
owns the listening socket. Only this launcher/listener pair was reloaded.

PostgreSQL, Redis, Qdrant, OCR/index workers, cleanup worker, outbox
dispatcher, and Ollama remained separate existing processes/containers.
Neither the project launcher batch file nor a Docker lifecycle command was
used.

## 2. Preflight

| Check | Result |
|---|---|
| Runtime database | `local_ai_core` |
| Runtime Alembic revision | `20260725_13` |
| `discord_conversation_sessions` exists | Yes |
| `discord_session_turns` exists | Yes |
| Discord sessions | 0 |
| Discord turns | 0 |
| Feature flag | Unset; effective default `false` |
| Discord bot process | Not running |
| Legacy RAM dictionary source | Present |
| Legacy per-user key source | Present |
| Live resolver before reload | Present |
| Live turn enqueue route before reload | Absent |
| Source-generated turn routes | All present |
| Pre-reload `/health` | HTTP 200, `status=ok` |

Counts captured before reload:

```text
conversations                 6
messages                     30
memories                      0
jobs                          0
outbox_events                 0
discord_conversation_sessions 0
discord_session_turns          0
```

Source-generated OpenAPI was inspected without starting application lifespan
or calling a mutation endpoint. It contained all five required Discord
resolver/turn routes.

Git state before reload:

```text
branch: main
revision: d18c73221c1e8490a4e9fb32060526221c2ee4ee
```

The working tree was already dirty with the reviewed Sprint 1/Sprint 1B
implementation and documentation:

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

The planning/audit documents were also untracked. This gate did not modify
runtime source or create a migration.

## 3. Process/PID Audit

The listener was resolved from the exact socket:

```text
local address: 127.0.0.1
local port:    8000
state:         LISTEN
```

Before reload:

| Role | PID | Parent | Executable |
|---|---:|---:|---|
| Venv launcher | 19492 | 28136 | `.venv\Scripts\python.exe` |
| Uvicorn listener | 13576 | 19492 | system `python.exe` |

Both processes had:

```text
cwd = C:\Users\dungbt06\Ún promax\local-ai-core\backend
args = -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The listener/parent relationship and socket ownership were revalidated
immediately before stopping the API.

After reload:

| Role | PID | Parent | Start time UTC |
|---|---:|---:|---|
| Venv launcher | 40468 | 28120 | 2026-07-25 14:51:12.211332Z |
| Uvicorn listener | 39664 | 40468 | 2026-07-25 14:51:12.242618Z |

The new listener owns `127.0.0.1:8000` and uses the same cwd and arguments.

## 4. Reload Command

Old API stop began at:

```text
2026-07-25T14:50:38.256084Z
```

The exact listener PID `13576` was stopped. Its venv launcher `19492` exited
with the child. Verification then showed:

```text
old API processes remaining = 0
port 8000 listeners          = 0
```

The new API was started with:

```text
Working directory:
C:\Users\dungbt06\Ún promax\local-ai-core\backend

Command:
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Before `Start-Process`:

```text
POSTGRES_TEST_URL removed
DISCORD_PERSISTENT_SESSIONS_ENABLED removed
DATABASE_URL process override removed
```

The backend therefore loaded the existing runtime configuration from the
project `.env`. The runtime database guard had already confirmed that this
configuration targets `local_ai_core`.

The process was started hidden with stdout/stderr redirected to:

```text
data/logs/sprint1b-backend-reload.stdout.log
data/logs/sprint1b-backend-reload.stderr.log
```

No aggregate launcher, dependency installer, Docker Compose start/down,
model-download command, or Discord bot command was used.

## 5. Reload Result

```text
spawn result:             success
application startup:      complete
new launcher PID:         40468
new listener PID:         39664
health verification UTC:  2026-07-25T14:51:30.187166Z
```

Uvicorn reported:

```text
Started server process [39664]
Application startup complete
Uvicorn running on http://127.0.0.1:8000
```

One initial combined start-and-verification PowerShell command was rejected by
command policy before execution. At that point port 8000 remained closed. The
same audited start and verification were then performed as smaller commands
and succeeded; no alternate process or configuration was used.

## 6. Health Checks

Post-reload read-only checks:

| Check | Result |
|---|---|
| `GET /health` | HTTP 200, `status=ok` |
| PostgreSQL | `ok` |
| Redis | `ok` |
| Qdrant | `ok` |
| Ollama | `ok` |
| Outbox dispatcher | `ok` |
| Cleanup worker | `ok` |
| `GET /conversations` | HTTP 200, 6 rows |
| `GET /ui/` | HTTP 200 |
| `GET /openapi.json` | HTTP 200 |
| Model/repository import | `ok` |

`worker_ocr` and `worker_index` remained `unavailable` in the application
health payload both before and after reload, matching the previously
documented state. This gate did not restart either worker.

Container/process start times predate the reload:

| Component | Existing start time UTC |
|---|---|
| PostgreSQL | 2026-07-19 04:31:53Z |
| Redis | 2026-07-19 04:31:53Z |
| Qdrant | 2026-07-19 04:31:53Z |
| OCR/index and supporting workers | 2026-07-19 04:31:54Z |
| Ollama | 2026-07-15 03:47:39Z |

This verifies the API-only reload did not restart these components.

## 7. Live OpenAPI Routes

Live OpenAPI now exposes:

```text
POST /api/discord/sessions/resolve
POST /api/discord/sessions/{session_id}/turns
POST /api/discord/sessions/turns/{turn_id}/execute
POST /api/discord/sessions/turns/{turn_id}/complete
POST /api/discord/sessions/turns/{turn_id}/fail
```

No raw claim or heartbeat HTTP route is exposed.

## 8. Request/Response Contract Verification

Resolver request:

- `guild_id` is required, non-null, `minLength=1`, `maxLength=64`;
- `channel_id` is required, non-null, `minLength=1`, `maxLength=64`;
- `thread_id` is null or a non-empty string up to 64 characters;
- `user_id` is absent;
- additional properties are forbidden.

Enqueue request properties are exactly:

```text
discord_message_id
message
system_prompt
```

`discord_message_id` and `message` are required. Additional properties are
forbidden, so clients cannot provide:

```text
sequence_number
status
worker_id
lease_expires_at
attempt_count
```

Enqueue response requires:

```text
turn_id
session_id
sequence_number
status
created
```

Execute:

- accepts no request body;
- response includes the backend-issued `execution_token`, answer, model,
  sequence, session, status, and optional replacement turn;
- service source generates the ownership token with `uuid4().hex`.

Complete requires only a non-empty `execution_token`. Fail requires
`execution_token` and an error, with optional `retryable`. Complete/fail return
the turn ID and resulting state.

All verification used OpenAPI/source inspection only. No Discord POST endpoint
was called.

## 9. Revision Verification

Post-reload direct database inspection:

```text
database: local_ai_core
revision: 20260725_13
```

No Alembic command was run during this reload gate.

## 10. Row Counts Before/After

| Table | Before | After | Changed |
|---|---:|---:|---|
| `conversations` | 6 | 6 | No |
| `messages` | 30 | 30 | No |
| `memories` | 0 | 0 | No |
| `jobs` | 0 | 0 | No |
| `outbox_events` | 0 | 0 | No |
| `discord_conversation_sessions` | 0 | 0 | No |
| `discord_session_turns` | 0 | 0 | No |

The new API log contains only GET health/conversation/UI/OpenAPI checks and no
Discord mutation request. No backend conversation, session, or turn was
created by the reload.

## 11. Feature Flag Status

```text
runtime .env:                         unset
new API process environment:          unset
effective bot default:                false
POSTGRES_TEST_URL in new API process: absent
```

The runtime `.env` was not modified and the feature flag was not enabled.

## 12. Bot Status

```text
Discord bot Python process count: 0
production bot cutover:           not performed
```

The bot was not started or restarted. The source retains:

- the legacy RAM conversation dictionary;
- the legacy per-user `conversation_key`;
- the default-false persistent-session feature flag.

No resolver or turn call originated from a production bot, and Discord runtime
tables remained empty.

## 13. Remaining Work

The next operations require separate gates:

1. validate resolver/FIFO behavior in a non-production Discord environment;
2. prepare an explicit production bot cutover and rollback window;
3. enable the feature flag only during that controlled bot gate;
4. monitor session/turn creation, FIFO backlog, lease recovery, retries,
   permanent failures, and orphan transitions.

Rule filtering, Qwen3.5:2b extraction, structured memory, rolling summary, and
Qdrant memory retrieval remain outside Sprint 1B.

## 14. Final Decision

```text
SPRINT 1B BACKEND ROUTES LIVE — FEATURE FLAG OFF
```

The API-only reload succeeded; health is `ok`; live OpenAPI exposes every
reviewed Sprint 1B route with the expected contracts; runtime revision and row
counts are unchanged; Discord session/turn tables remain empty; the feature
flag remains off; and no Discord bot restart, cutover, or mutation endpoint
call occurred.
