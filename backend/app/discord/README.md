# app.discord — the Discord package

Everything here exists only because of Discord. The core (agent loop, RAG, documents,
web memory, dashboard) imports nothing from this package; the package imports the core
and plugs into it. Ticket 22 moved it here, with no table or migration change.

## What is in it

| Area | Modules |
| --- | --- |
| Sessions and turns (the bot's conversations with the API) | `session_service`, `turn_service`, `speaker_context`, `schema`, `routers/sessions` |
| Channel history (sổ gốc) and the agent's `search_history` backend | `history_service`, `history_schema`, `routers/history` |
| Condensation (tier 3 recaps) | `condensation_service`, `routers/condensations` |
| Memory pipeline | `memory_extractor`, `memory_verifier`, `memory_rule_filter`, `memory_guard`, `memory_worker_service`, `memory_completion_service`, `memory_recovery_service`, `memory_review_service`, `memory_tasks` (RQ task), `routers/memory_review` |
| Persistence | `repositories`, `memory_repositories`, `memory_job_repository` (models stay in `app/postgres/models.py`) |
| Forgetting a member | `member_redaction` (used by `scripts/forget_member.py`) |
| Bot process control from the dashboard | `bot_control_service`, `routers/bot` |

## How it plugs in

`main.py` calls two functions from `__init__.py`:

- `register_routes(app, admin_guard=...)` when the app object is built, so the five routers
  exist whether or not the lifespan runs. Their prefixes (`/api/bot`, `/api/condensations`,
  `/api/memory-review`, `/api/discord/sessions`, `/api/discord/history`) overlap no core route.
- `register_services(app, settings, postgres_sessions, project_root=...)` as the last step of
  the lifespan, because it builds on `app.state.memory_service`, `chat_service` and
  `agent_service`.

Both import lazily, so importing one module of the package does not load the rest.

## Rules

- The core never imports `app.discord`. `backend/tests/test_discord_boundary.py` enforces it,
  from the source and at runtime. The agent's `search_history` tool lives here
  (`agent_tools.py`) and `register_services()` plugs it into the running agent's
  `ToolRegistry` at the place it always had in the tool list (ticket 22 C4).
- Models, `discord_memory_constants` and the `discord_*` settings stay in the core: one
  metadata for Alembic, no migration. Moving them is a separate decision.
- Web memory is the core's. An approved Discord fact is projected into it under a
  `mem_dc_<uuid>` id through `MemoryService.upsert_with_id` / `remove_with_id`, and the core
  infers nothing from that prefix.
- Imports are always absolute (`from app.discord import ...`). The bot uses the `discord`
  library from pip, a different package; a script run with `cwd=backend/app` would import
  this directory under that name instead.
