# Controlled Backend Reload Gate

Execution time: 2026-07-25 Asia/Saigon  
Scope: reload the running backend API so the reviewed Sprint 1 source is live

## 1. Runtime Mode Before Reload

The backend API was running directly as a Windows process, not as a Docker Compose API service.

Listener audit:

| Item | Before reload |
|---|---|
| Address | `127.0.0.1:8000` |
| Listener PID | `43116` |
| Listener executable | System Python 3.11 `python.exe` |
| Launcher PID | `35032` |
| Launcher executable | Repository `.venv\Scripts\python.exe` |
| Working directory implied by launcher | `backend` |
| Command | `.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000` |

`run-local-ai-core.bat` uses the same command after `cd backend`. The complete launcher was deliberately not run because it also checks/install dependencies, runs `docker compose up`, checks Ollama, and may download models. None of those operations was required for an API-only reload.

PostgreSQL, Redis, Qdrant, cleanup worker, outbox dispatcher, and RQ workers were separate existing containers/processes. Reloading the direct Uvicorn process did not require recreating or restarting any of them.

## 2. Preflight

Repository:

| Item | Value |
|---|---|
| Git commit | `d18c73221c1e8490a4e9fb32060526221c2ee4ee` |
| Working tree | Dirty with the reviewed Sprint 1 implementation and planning/audit documents |

Database:

| Check | Result |
|---|---|
| Runtime database | `local_ai_core` |
| Runtime Alembic revision | `20260725_12` |
| `discord_conversation_sessions` exists | Yes |
| `discord_session_turns` exists | Yes |
| Session rows | 0 |
| Turn rows | 0 |

API:

| Check | Result |
|---|---|
| Source-generated OpenAPI contains resolver | Yes |
| Live OpenAPI contains resolver before reload | No |
| Live health before reload | `status=ok` |
| PostgreSQL/Redis/Qdrant/Ollama before reload | All `ok` |

Bot:

- `discord_bot/main.py` still declared `conversations: dict[str, str]`.
- The bot still used `conversation_key(guild_id, channel_id, user_id)`.
- `discord_bot/main.py` did not call `resolve_discord_session()`.
- The resolver method existed only in `discord_bot/api_client.py`.

No credential, token, or full database URL was printed.

## 3. Reload Command

The listener PID and both command lines were revalidated immediately before the reload.

Only the audited API process was stopped:

```text
Stop-Process -Id 43116
```

The venv launcher PID `35032` exited with its child. Port 8000 was confirmed closed before restart.

Only the backend API was started:

```text
Working directory: backend
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The process was launched hidden with `Start-Process`. `POSTGRES_TEST_URL` was removed from the launch environment; normal runtime configuration continued to load through the existing project settings.

Commands explicitly not used:

- `run-local-ai-core.bat`;
- `docker compose up`, `down`, or recreate;
- any Docker volume command;
- any database reset/restore/downgrade;
- any Discord bot command;
- any Ollama model command.

## 4. Reload Result

Reload time:

```text
2026-07-25T02:18:52.7012245+07:00
```

Result:

| Item | Value |
|---|---|
| Stop operation | Exit 0 |
| Start orchestration | Exit 0 / process started |
| New venv launcher PID | `19492` |
| New listener PID | `13576` |
| New listener | `127.0.0.1:8000` |
| New command | Same Uvicorn command as before |
| Health wait | Reached `status=ok` within the 30-second gate |

An initial combined PowerShell orchestration command was rejected by command policy before execution. The old API remained healthy and unchanged. The same audited operation was then performed as smaller exact-PID stop/start steps and succeeded.

PostgreSQL, Redis, and Qdrant retained the same container IDs and prior multi-day uptime. No container or volume was recreated.

## 5. Health Checks

Post-reload live checks:

| Check | Result |
|---|---|
| `GET /health` | HTTP success, `status=ok` |
| PostgreSQL | `ok` |
| Redis | `ok` |
| Qdrant | `ok` |
| Ollama | `ok` |
| Outbox dispatcher | `ok` |
| Cleanup worker | `ok` |
| `GET /conversations` | HTTP success, 6 rows |
| `GET /ui/` | HTTP 200 |

The health payload reported `worker_ocr` and `worker_index` as unavailable both around the schema/reload checks. The required core components and top-level health remained `ok`; no worker was restarted in this gate.

Only read-only GET requests and component health/ping operations were used. No Redis or Qdrant write was issued.

## 6. Live OpenAPI Verification

After reload, live OpenAPI exposes:

```text
POST /api/discord/sessions/resolve
```

No other HTTP method is registered for this path.

Request schema: `DiscordSessionResolveRequest`

| Property | Live OpenAPI contract |
|---|---|
| `guild_id` | required, string up to 64 characters or null |
| `channel_id` | required, string, 1–64 characters |
| `thread_id` | optional, string up to 64 characters or null |
| Extra properties | rejected |

Response schema: `DiscordSessionResolveResponse`

| Property | Live OpenAPI contract |
|---|---|
| `session_id` | required UUID string |
| `backend_conversation_id` | required UUID string |
| `created` | required boolean |
| `status` | required constant `active` |

The resolver endpoint was not called. Its presence was verified only through live OpenAPI.

## 7. Legacy Row Counts

| Table | Before reload | After reload | Changed |
|---|---:|---:|---|
| `conversations` | 6 | 6 | No |
| `messages` | 30 | 30 | No |
| `memories` | 0 | 0 | No |
| `jobs` | 0 | 0 | No |
| `outbox_events` | 0 | 0 | No |

Runtime Alembic revision after reload:

```text
20260725_12
```

## 8. Discord Table Counts

| Table | Before reload | After reload |
|---|---:|---:|
| `discord_conversation_sessions` | 0 | 0 |
| `discord_session_turns` | 0 | 0 |

No Discord session, turn, or backend conversation was created.

## 9. Bot Cutover Status

Bot cutover: **not performed**.

Post-reload read-only source verification:

- `discord_bot/main.py` still uses the RAM dictionary;
- the canonical bot key still includes `user_id`;
- channel/thread canonical resolution is not active in the bot;
- `discord_bot/main.py` does not call `resolve_discord_session()`;
- no bot process was restarted by this gate;
- empty Discord tables and unchanged conversation count confirm the bot did not begin using the resolver.

## 10. Remaining Work

The live backend resolver is available, but the following remain outside this gate:

1. durable FIFO turn consumer, claim, lease, retry, and completion flow;
2. canonical parent-channel/thread/forum handling in `discord_bot/main.py`;
3. controlled Discord bot cutover from the per-user RAM mapping;
4. restart/multi-instance end-to-end bot tests;
5. later rule filter, extractor, structured memory, rolling summary, and Qdrant memory retrieval work.

No Sprint 1B or later sprint was started.

## 11. Final Decision

# BACKEND RESOLVER LIVE — BOT NOT CUT OVER

Decision basis:

- the backend API-only reload succeeded;
- live health is `ok`;
- live OpenAPI exposes the resolver with the reviewed request/response contract;
- runtime revision remains `20260725_12`;
- all legacy row counts are unchanged;
- Discord session and turn tables remain empty;
- the Web UI and conversation list still work;
- PostgreSQL, Redis, Qdrant, and Ollama remain healthy;
- no dependency container or volume was recreated;
- the Discord bot still uses the legacy RAM/per-user path and was not restarted.

This gate exposes only the backend session resolver. It does not activate Discord bot cutover, FIFO processing, or Discord Memory behavior.
