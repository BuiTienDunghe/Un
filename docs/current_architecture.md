# Current architecture — PostgreSQL-only baseline

Date: 2026-08-19 (original 2026-07-19; refreshed after P0 and P1-1..P1-3; model version registry 2026-09-07; Discord package 2026-10-28; checked against main 2026-10-30, ticket 29)

## Source-of-truth boundary

PostgreSQL is the sole runtime source of truth. `DATABASE_URL` is required and
must use a `postgresql+` SQLAlchemy dialect; SQLite URLs fail at startup.
SQLite databases are not mounted, opened, or created by FastAPI, workers,
cleanup, or ordinary tests.

The retired SQLite data is an explicit read-only archive, not a fallback:

```text
data/archives/sqlite-retired-20260719T002000Z/
```

Only migration/audit CLIs and their migration-specific tests may use `sqlite3`,
and they must receive the archive path explicitly. `pre_postgres_*` archives
are historical evidence only and must never be merged or used as a runtime
database.

## Runtime components

```text
FastAPI APIs (layer-1 X-API-Key guard on every mutating route)
  -> PostgreSQL: documents, versions, pages, chunks, jobs, outbox,
     conversations + message_sources (persisted citations), Discord sessions/memory
  -> OCR + indexing: a background thread of the API process (default,
     INGESTION_EXECUTION_BACKEND=thread)
       -> PostgreSQL canonical state + Qdrant versioned vectors
  -> Redis/RQ: Discord-memory transport (memory worker); OCR/index jobs
     only when INGESTION_EXECUTION_BACKEND=rq (compose worker-ocr / worker-index)
  -> host workers started by the launcher: cleanup, backup,
     outbox dispatcher + memory worker (when memory proposal mode is enabled),
     condensation worker (when DISCORD_CONDENSATION_ENABLED=true)
```

`backend/app/main.py` composes PostgreSQL repositories and document/retrieval
services. With the default `thread` backend it builds no job queue: an index request, a source
replacement or a retry starts `_run_index` in a daemon thread of the API
(`PostgresDocumentService.enqueue_index` / `_replace_content` / `retry_ingestion`), so
no RQ job, outbox event or OCR/index worker is involved, and `/health` reports
`worker_ocr` / `worker_index` as `unavailable` without that affecting `status`. The
launcher starts only the `redis` container of the `workers` profile, never the OCR/index
worker containers. With `rq`, Redis carries job IDs; in both modes PostgreSQL owns
lifecycle state, idempotency, outbox records, active-version state, citations, and
canonical chunk content.
Ollama provides embeddings and model inference; it is not a persistence source.
Which model serves each role is decided once per process by the model version
registry (next section).

The current Alembic head is pinned in README ("Alembic head hiện tại"); do not duplicate it here.

## Discord is a package the core does not import

`backend/app/discord/` holds what exists only because of Discord: the bot's sessions and
turns, channel history, condensation, the memory pipeline (extractor, verifier, guard,
review, completion, recovery, the RQ ingest task), member redaction, bot start/stop, and
the five admin routers (`/api/bot`, `/api/condensations`, `/api/memory-review`,
`/api/discord/sessions`, `/api/discord/history`). The core — agent loop, RAG, documents,
web memory, dashboard — imports nothing from it. `main.py` plugs it in twice:
`discord.register_routes()` when the app object is built, and
`discord.register_services()` as the last step of the lifespan, after the chat, memory
and agent services it builds on. `backend/tests/test_discord_boundary.py` holds the rule
(no core module imports `app.discord`; importing the agent, chat, RAG, web-memory or
grounding modules loads no Discord module). Package notes: `backend/app/discord/README.md`.

The split is soft, on purpose (ticket 22):

- Discord's 10 tables keep their models in `app/postgres/models.py` (one metadata for
  Alembic, no migration), and the dashboard and `/health` count rows in them.
- The 23 `discord_*` fields stay in `Settings`; `jobs/routing.py` names the memory
  ingest task by its string path.
- The agent's `search_history` tool is the package's (`app/discord/agent_tools.py`):
  `register_services()` plugs it into the running agent's `ToolRegistry` (ticket 22 C4).

Web memory and Discord memory meet at one contract. The `memories` table and the Qdrant
`memories` collection belong to the core (`MemoryService`); an approved Discord fact is
projected into them under a `mem_dc_<uuid>` id through `upsert_with_id` / `remove_with_id`,
and the core infers nothing from that prefix.

## Agent (tool mode)

A web turn goes through `AgentService` only when the request sets `use_tools` (default
false, `chat_schema.py`); a Discord turn does when `DISCORD_AGENT_TOOLS_ENABLED` (default
true) and its guild is in `DISCORD_AGENT_TOOLS_GUILD_ALLOWLIST` (default empty = no guild,
`*` = every guild). Every other turn is plain chat. Beyond documents and history, the tools are `system_status`, `current_time`, `calculate`, `remember` (Discord only), and `web_search` / `read_webpage` when `AGENT_WEB_TOOLS_ENABLED=true`. The bot's `/docs` command reads the same
variable itself and refuses a guild outside it, and any DM, before calling `/rag/chat`; the
backend does not check, so `/rag/chat` stays open to any holder of the API key. The tools sit in one `ToolRegistry`:
the core registers `search_documents`, `read_document` and `system_status`; the Discord
package adds `search_history`. `read_document` reads up to three consecutive chunks whole
per call (at most `agent.read_result_max_chars`, 6 000), and only a document that the same
turn's search returned or a paste of the same conversation. A turn is bounded by
`agent.max_steps` (3 tool rounds) and `agent.turn_budget_seconds` (90 s, with
`final_reserve_seconds` 20 s kept for the answer). An answer with a figure of two or more
digits the turn saw nowhere gets one more round with tools while that reserve is free
(`answer_figures.py`); a tool call Ollama cannot parse gets one re-prompt. Steps persist in
`agent_traces`, and a content-free summary of each in `agent_trace_summaries`, which
outlives the conversation.

Long pastes (`services/pastes.py`): tool mode accepts a message up to 100 000 characters,
plain chat refuses more than 10 000 (422 `INPUT_TOO_LONG`). A paste stays a message of its
conversation and never enters the document library. The paste the user just sent reaches
the model whole while the whole prompt, estimated as 1 253 + characters / 3.3 tokens, fits
16 384 − 4 096; otherwise, and for any paste further up the history, the model sees a slip
(the first and last 600 characters and a `paste_<hash>` id) and opens the rest with
`read_document`.

## Model versions

`backend/app/config/model_versions.yaml` lists every model role (general, condenser,
embedding, vision, ocr, reranker, extractor, verifier) as an ordered list of version
records with one `active` pointer per role; `models.yaml` keeps only policy (`rag.*`,
`agent.*`, `storage.*`). Each process resolves the pointer once at start
(`Settings.resolve_models()`): one `GET /api/tags`, one probe embed for the embedding
pointer, one width + count check per embedding collection, one PostgreSQL count pair —
bounded, single-attempt, never a download. `Settings.load_models()` returns the active
version's `config:` block verbatim, so `ModelRouter`, `/models.models`, the OCR cache and
the embedding-cache fingerprint see the same flat dicts as before the registry existed.

If the active version fails its probe, the resolver serves the nearest earlier version
that passes (`status: fallback`); the reranker chain is walked by
`RerankerService.warmup()` and ends in `disabled` rather than a refused boot. The
embedding role never falls back: a verified contradiction between the version and its
collections is `degraded`, and `ModelRouter.embed` refuses before Ollama. Every deviation
is one predicate, surfaced as `/health.model_fallback`, `/models.registry`,
`data/logs/ATTENTION_model_fallback.txt` and the `model_version_fallback` log event; the
eval writers and the nightly refuse to treat a deviating process as the shipped
configuration. `MODEL_VERSION_<ROLE>` pins a version per machine (shell only, never
`.env`). Runbook: `docs/model_registry.md`; decision:
`docs/adr/0001-model-version-registry.md`.

## Qdrant contract

Each embedding version owns one pair of collections — `documents` / `memories` for
`embedding-v0`, `<base>_<collection_suffix>` for any later version — chosen by the same
registry pointer that chooses the query model, so a same-width model swap can never write
into the wrong collection. They are vector indexes, never the canonical content source.
Deletes sweep every registered collection and raise before the PostgreSQL row flips when
an existing collection cannot be reached; an inactive collection is frozen at its last
rebuild, not mirrored, so re-promotion starts with `rebuild_qdrant --missing-only`.
A runtime retrieval candidate is accepted only when it has both
`version_id` and `chunk_id`; PostgreSQL then confirms that the chunk belongs to
the requested document's active version before returning its content/citation.

Points that only contain legacy `index_version` are deliberately ignored by
retrieval. Cleanup planning and execution also exclude legacy Qdrant points;
there is no `legacy-qdrant` cleanup domain. Legacy-point audit is a separate,
read-only Phase 9A command and no automatic cleanup policy exists.

## Retention and recovery

- PostgreSQL backups and Qdrant snapshots are retained recovery artifacts.
- The SQLite archive remains retained and checksum-verified; it is not restored
  into `data/sqlite/` or any runtime path.
- Source cleanup applies only to explicitly temporary, unpinned PostgreSQL
  documents after configured TTL and lifecycle guards.
- Superseded version cleanup uses PostgreSQL guards and only deletes Qdrant
  points addressed by a PostgreSQL `version_id`; it cannot select legacy points.

For recovery, restore a PostgreSQL dump into a separate validation database,
validate its Alembic revision and repository reads, then use the retained
Qdrant snapshot according to an approved recovery procedure. Never merge
SQLite archives or use one as a runtime replacement.

## Operational evidence

`GET /health` reports PostgreSQL, Redis, Qdrant, Ollama, worker discovery,
outbox state, cleanup heartbeat, PostgreSQL backup freshness (`backup`,
`backup_age_hours`, `backup_worker`), the model registry (`model_fallback`: `ok` or
`fallback`; the per-role rows are `GET /models` → `registry`) and, when enabled, the
memory pipeline (`memory_ingestion`, `worker_memory`). It has no SQLite component. The runtime
guard tests prove FastAPI and worker modules do not import `SQLiteStore` or
`sqlite3`.

The Phase 9A inventory is the authoritative legacy-point status report:
`data/benchmarks/phase9a_legacy_qdrant_mapping.json`. Legacy cleanup is deferred
indefinitely until a separately approved policy explicitly authorizes it.
