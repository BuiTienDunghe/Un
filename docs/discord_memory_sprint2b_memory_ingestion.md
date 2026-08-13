# Sprint 2B.1 — Discord Memory Ingestion Foundation Audit and Design

Date: 2026-07-28  
Scope: source/runtime audit and design only  
Runtime mutation: none

## 1. Executive Decision

The repository has a live, manually managed Web UI memory feature, but it does
not have Discord long-term memory ingestion. The existing `memories` table and
Qdrant adapter are global and unscoped. They cannot safely represent Discord
personal, guild, channel, or thread memory without changing current Web UI
behavior and creating cross-user retrieval risk.

The selected foundation is therefore:

```text
completed Discord turn + acknowledged Discord delivery
→ Job + transactional outbox in the completion transaction
→ Redis/RQ memory-ingestion worker
→ deterministic rule filter
→ strict extractor proposal
→ deterministic backend validation
→ durable 15-second conflict window
→ versioned Discord memory transaction in PostgreSQL
→ Qdrant index outbox/job
→ idempotent Qdrant indexing and reconciliation
```

Key decisions:

- keep the existing Web UI `memories` table, `/memory/*` endpoints, and
  Qdrant `memories` contract unchanged;
- create a separate Discord structured-memory domain;
- use stable Discord `author_id`, never display name, as member identity;
- use PostgreSQL as canonical truth;
- trigger the asynchronous path only after turn completion and delivery;
- reuse the existing `jobs`/`outbox_events` schema and operating pattern after
  generalizing queue routing and memory-specific recovery;
- use version rows plus source links, rather than in-place overwrite or full
  event sourcing;
- use a separate Qdrant collection for Discord memories;
- do not enable ingestion, auto-apply, or retrieval until their individual
  implementation and production gates pass.

No implementation blocker was found for the candidate/outbox foundation.
Several privacy and governance choices remain blockers for production
auto-apply/retrieval, but they do not block isolated code/test work with
conservative defaults and dry-run mode.

## 2. Audit Method and Production Baseline

Evidence was collected using:

- source, migration, test, and configuration inspection;
- PostgreSQL metadata and count queries inside read-only transactions;
- live OpenAPI GET;
- Qdrant collection-list GET;
- Ollama model-list GET;
- process and health inspection.

No POST/mutation endpoint, model invocation, migration, test mutation,
process restart, Qdrant write, Redis write, or database write was performed.

Verified production baseline:

```text
runtime database                  local_ai_core
runtime revision                  20260728_15
conversations                     7
messages                          80
memories                          0
Discord sessions                 1
Discord turns                    28
Discord delivery rows            2
max Discord sequence             28
jobs                              0
outbox events                    0
```

The runtime Qdrant server reported no collections. In particular, neither
`documents` nor `memories` currently exists. The source can create them on
first write, but this audit did not do so.

## 3. Current-State Inventory

### 3.1 PostgreSQL `memories`

The only runtime memory table is `memories`, created by:

```text
backend/alembic/versions/20260718_07_auxiliary_postgres_domains.py
```

The live table exactly contains:

| Column | PostgreSQL type | Null | Default |
|---|---|---:|---|
| `id` | `varchar(128)` | no | none |
| `content` | `text` | no | none |
| `memory_type` | `varchar(64)` | no | none |
| `importance` | `float8` | no | none |
| `metadata_json` | `jsonb` | no | `{}` |
| `created_at` | `timestamptz` | no | `now()` |
| `updated_at` | `timestamptz` | no | `now()` |

Database metadata confirms:

- primary key: `memories_pkey(id)`;
- no additional indexes;
- no foreign keys;
- no CHECK constraints;
- no uniqueness for subject/scope/content/fact;
- row count: `0`.

There are no runtime tables for:

```text
memory candidates/proposals
memory versions
memory sources
memory audit events
memory fact heads
memory index state
Discord structured memories
```

`backend/app/postgres/models.py:Memory` mirrors this minimal schema.

### 3.2 Active Web UI Memory Runtime

The following components are active runtime, not merely legacy files:

| Component | Exact role |
|---|---|
| `backend/app/main.py` | Constructs `MemoryService` and includes the memory router. |
| `backend/app/postgres/models.py:Memory` | ORM mapping for `memories`. |
| `backend/app/stores/auxiliary_store.py:AuxiliaryStore` | Memory CRUD protocol. |
| `backend/app/stores/postgres_auxiliary_store.py:PostgresAuxiliaryStore` | PostgreSQL CRUD implementation. |
| `backend/app/services/memory_service.py:MemoryService` | Embedding, Qdrant CRUD/search, compensation. |
| `backend/app/schemas/memory_schema.py` | Manual CRUD/search API schemas. |
| `backend/app/routers/memory.py` | Live memory endpoints. |
| `backend/app/services/chat_service.py` | Optional `use_memory` retrieval for ordinary chat. |
| `backend/app/prompts/memory_system.md` | Web/general-chat memory prompt. |
| `backend/app/frontend/index.html` | Memory checkbox. |
| `backend/app/frontend/app.js` | Sends `use_memory` to `/chat`. |
| `backend/app/stores/qdrant_store.py` | `memories` collection implementation. |

Live OpenAPI exposes:

```text
POST   /memory/add
POST   /memory/search
PUT    /memory/{memory_id}
DELETE /memory/{memory_id}
POST   /chat                  (use_memory flag)
```

There is no memory list endpoint, subject-scoped read endpoint, version
endpoint, source endpoint, review endpoint, or Discord memory endpoint.
OpenAPI declares no security scheme for these routes.

The Web UI checkbox is opt-in per chat request. When `use_memory=true`,
`ChatService` retrieves up to five Qdrant results and inserts their `content`
into a system memory block.

### 3.3 Existing Memory Write Semantics

Current `MemoryService` behavior is Qdrant-first:

```text
add:
embed → Qdrant upsert → PostgreSQL insert
PostgreSQL failure → compensating Qdrant delete

update:
load PostgreSQL row → embed → Qdrant upsert → PostgreSQL in-place update
PostgreSQL failure → re-embed old content and compensate Qdrant

delete:
load PostgreSQL row → Qdrant delete → PostgreSQL hard delete
PostgreSQL failure → re-embed and restore Qdrant

search:
embed query → Qdrant only
```

Consequences:

- PostgreSQL is not commit-first for vector updates;
- search does not revalidate Qdrant results against PostgreSQL;
- update overwrites the row in place;
- delete destroys the canonical row;
- there is no durable index job or reconciliation for memories;
- a process crash can leave PostgreSQL/Qdrant inconsistent despite
  best-effort compensation.

This behavior must remain unchanged for the Web UI until a separately approved
UI memory migration exists. It must not be reused as the Discord canonical
store.

### 3.4 Existing Deduplication, Versioning, Source, and Audit

Current Web UI memory provides:

| Capability | Current evidence |
|---|---|
| ID generation | Random opaque `mem_<uuid hex>`. |
| Content deduplication | None. |
| Subject identity | None. |
| Guild/user/channel isolation | None. |
| Versioning | None; update is in-place. |
| Delete history | None; delete is hard. |
| Source conversation/message/turn | None. |
| Evidence | None. |
| Conflict handling | None. |
| Audit | Endpoint-level request log only; no memory ID/content/version linkage. |
| Metadata | `metadata_json` exists but the active adapter creates `{}` and API does not expose it. |

There is no FK from `memories` to `conversations`, `messages`,
`discord_session_turns`, or `discord_conversation_sessions`.

### 3.5 Discord Memory Usage

Discord does not use current Web UI memory:

- `DiscordTurnService.execute()` builds attributed context and calls
  `ChatService.respond_with_context()`;
- `respond_with_context()` always passes `use_memory=False`;
- the bot turn/enqueue contract has no memory flag;
- no completion code calls `MemoryService`;
- no Discord memory ingestion worker exists.

This isolation is desirable and must be preserved while the new Discord
memory domain is built.

### 3.6 Current Qdrant and Embedding Implementation

`QdrantStore` declares:

```text
documents collection: documents
Web UI memory collection: memories
```

Existing memory points use deterministic UUID5 point IDs derived from the
opaque PostgreSQL memory ID. Their payload is only:

```json
{
  "memory_id": "...",
  "content": "...",
  "memory_type": "...",
  "importance": 0.5
}
```

`search_memories()` applies no metadata filter. There is no guild, author,
subject, scope, status, version, source, or index-state payload.

Runtime Qdrant inventory:

```text
collections                         0
memories collection                 absent
memory points                       0
payload indexes                     none
```

The configured and installed embedding model is:

```text
qwen3-embedding:0.6b
configured context: 32768
```

The current `backend/scripts/rebuild_qdrant.py` rebuilds document chunks only.
It does not rebuild Web UI or Discord memories.

### 3.7 Extractor Capability

The proposed extractor is not implemented:

```text
qwen3.5:2b                        not configured
qwen3.5:2b                        not installed in current Ollama inventory
extractor model route             absent
extractor prompt                  absent
extractor JSON Schema             absent
rule filter                       absent
dry-run proposal store            absent
conflict resolver                 absent
```

The current `OllamaClient.chat()` supports `think`, options, streaming, and
ordinary text responses, but it does not accept an Ollama `format` field.
`ModelRouter.chat()` only accepts `general` and `code`; it does not pass a JSON
Schema or seed. A dedicated extractor adapter is required for:

```text
model=qwen3.5:2b
think=false
stream=false
format=<JSON Schema object>
temperature=0.0
seed=<fixed benchmark seed>
num_ctx=4096
```

The primary mode should be an Ollama JSON Schema object. Plain `"json"` is
only a compatibility fallback; both modes still require strict backend
validation.

### 3.8 Jobs, Outbox, Redis/RQ, Lease, and Recovery

The tables and production implementation exist, but the current host backend
is configured with `INGESTION_EXECUTION_BACKEND=thread`. In that mode document
ingestion uses an in-process thread and does not create a Job/OutboxEvent.
Docker Compose configures the RQ profile, but its OCR/index/outbox worker
services were not running during this audit. The tables are present and empty:

```text
jobs            0
outbox_events   0
```

Reusable `jobs` fields include:

```text
id
job_type
status
attempts / max_attempts
available_at
started_at / completed_at
worker_id
heartbeat_at / lease_expires_at
idempotency_key UNIQUE
redis_job_id UNIQUE
error_code / error_message
payload JSONB
```

Document-specific foreign keys are nullable, so a memory job can structurally
exist without a document. `outbox_events` provides a unique idempotency key,
status/attempts/availability timestamps, payload, and job/Redis identifiers.
It does not have a database FK from `job_id` to `jobs`.

Reusable implementation patterns:

- `PostgresDocumentRepository.create_job()` creates a Job and OutboxEvent in
  the same transaction;
- `OutboxDispatcherService` claims due events with a short transaction,
  commits, then calls Redis outside the transaction;
- duplicate dispatch is protected by event state and deterministic RQ job ID;
- retry metadata and backoff are durable in PostgreSQL;
- worker ownership uses worker ID, heartbeat, and lease;
- `JobRecoveryService` has stale-job and missing-Redis reconciliation patterns;
- tests cover atomic rollback, dispatcher retry, competing dispatchers,
  worker leases, Redis outages, and idempotent RQ delivery.

Parts that cannot be reused unchanged:

- `JobQueueService` maps `extract_document` to the OCR queue and every other
  job type to the document index queue/function;
- `app.workers.tasks` only defines document extraction/index tasks;
- document recovery calls ingestion-run transitions and is unsafe for a
  memory job with no `ingestion_run_id`;
- health only knows OCR/index queues;
- current process state reports OCR/index workers unavailable;
- the configured `INGESTION_EXECUTION_BACKEND` is currently `thread`, and
  there is no memory-specific setting or queue.

Conclusion: reuse the `jobs`/`outbox_events` schema and proven transaction,
dispatch, retry, lease, and heartbeat patterns, but add explicit job-type
routing and a memory-specific repository/worker/recovery path. Do not route a
memory job through `index_document` by relying on the current fallback branch.

### 3.9 Legacy and Inactive Artifacts

| Artifact | Classification |
|---|---|
| `backend/scripts/migrate_sqlite_to_postgres.py` memory mapping | Legacy migration utility; manually invoked, not runtime. |
| SQLite memory schema in migration tests | Test-only. |
| Historical SQLite archives referenced by migration reports | Legacy evidence. |
| Deleted `SQLiteStore` source; stale `__pycache__` bytecode | Inactive artifact, not importable runtime source. |
| Workflow V5 structured memory tables/config | Docs-only. |
| Existing Qdrant `memories` code with no live collection | Active callable code, presently no runtime data. |

No source was found that silently runs a legacy Discord extractor.

### 3.10 Existing Tests

Existing memory-related coverage:

| Test | What it proves | Limitation |
|---|---|---|
| `backend/tests/test_memory_api.py` | Manual add/search/update/delete route behavior. | Ollama and Qdrant are mocked; no scope/version/source. |
| `backend/tests/test_chat_api.py::test_chat_uses_relevant_memory_when_requested` | `use_memory` inserts returned content into model context. | Memory search is mocked. |
| `backend/tests/test_postgres_auxiliary_store.py` | PostgreSQL adapter CRUD and `MemoryService` contract. | Fake Qdrant/router. |
| `backend/tests/test_auxiliary_postgres_schema.py` | Legacy-compatible `Memory` JSONB/ID persistence. | Does not test structured Discord memory. |
| `backend/tests/test_sqlite_to_postgres_migration.py` | Legacy migration domain recognition. | Fixture contains zero legacy memory rows in the exercised test. |
| `backend/tests/test_qdrant_store.py` | Collection dimension mismatch behavior. | Not a scoped memory-search test. |

There are no tests for Discord ingestion, rule filtering, extractor JSON,
stable-subject validation, source links, conflict windows, versioned facts,
forget, Qdrant guild isolation, stale memory vectors, or memory outbox jobs.

No tests were run in this audit-only gate.

## 4. Component Classification

| Component | Classification | Sprint 2B decision |
|---|---|---|
| Web UI `/memory/*` | active runtime | Preserve unchanged. |
| `memories` PostgreSQL table | active runtime | Do not repurpose for Discord. |
| Web UI `use_memory` | active runtime | Preserve unchanged. |
| Qdrant Web UI memory methods | active runtime, empty runtime collection | Preserve; do not mix Discord points. |
| `qwen3-embedding:0.6b` | active runtime | Candidate embedding model; benchmark for Discord indexing. |
| `jobs` / `outbox_events` | existing and active in the RQ deployment profile; inactive in the current host `thread` mode | Reuse schema/pattern after routing changes. |
| RQ OCR/index/outbox workers | existing but inactive/unavailable in the audited host runtime | Do not treat as a memory worker. |
| SQLite memory migration | legacy | No integration. |
| Temporary SQLite/Qdrant fakes in memory tests | test-only | Keep for regression; not runtime evidence. |
| Structured Discord memory schema | not implemented | Create in later phase. |
| Discord completion ingestion hook | not implemented | Create in 2B.3. |
| Rule filter | not implemented | Create in 2B.4. |
| Qwen extractor adapter | not implemented | Create in 2B.5. |
| Validator/conflict resolver | not implemented | Create in 2B.6. |
| Discord Qdrant index/reconciliation | not implemented | Create in 2B.7. |
| Discord scoped retrieval | not implemented | Create in 2B.8. |
| Workflow V5 memory design | docs-only | Use as design input, not implementation evidence. |

## 5. Gap Analysis

The production Discord path already provides the minimum trustworthy source
envelope:

```text
turn ID
session ID
source Discord message ID
stable author ID
display-name snapshot
reply target ID
raw request text
assistant response
turn status/attempt/lease
Discord response delivery IDs
canonical guild/channel/thread through the session
```

Missing ingestion foundation:

- no completion event;
- no memory job;
- no deterministic filter;
- no extractor configuration or adapter;
- no strict proposal schema;
- no trusted-entity validation;
- no candidate/proposal persistence;
- no stable fact identity;
- no 15-second conflict state;
- no versioned Discord memory;
- no source links;
- no Discord Qdrant collection/filter;
- no reconciliation/rebuild;
- no inspection/forget governance.

Current turn storage also has no edit/delete metadata and no list of mentioned
human IDs. Therefore, initial auto-apply can safely support the current author
and explicitly known guild/project subjects. A statement about another member
must not be auto-applied unless that member's stable ID comes from trusted
Discord metadata, such as an exact reply target or a future persisted mention
list.

## 6. Integration Point Decision

### 6.1 Current Lifecycle

Production lifecycle is:

```text
enqueue turn
→ atomic per-session claim
→ commit claim
→ call chat/model outside transaction
→ persist response/renew lease
→ bot sends Discord response
→ bot acknowledges exact Discord delivery IDs
→ completion transaction:
   insert delivery rows
   mark turn completed
   clear worker/lease/heartbeat
```

The completion transaction is the first point where all required eligibility
facts are simultaneously true:

- turn is terminal `completed`;
- response is non-empty;
- Discord send succeeded;
- delivery IDs are persisted;
- stable author and session location are known;
- ownership and lease are cleared.

### 6.2 Option Comparison

| Option | Durability | Completion latency/coupling | Failure behavior | Decision |
|---|---|---|---|---|
| Call memory service directly in completion | Poor separation | Adds filter/model/vector latency | Extractor/Qdrant can fail Discord ACK | Reject. |
| Transactional outbox in completion | Strong | One small PostgreSQL insert; no model/vector call | Durable retry; Redis/model outage isolated | Select. |
| Direct Redis/RQ enqueue | Redis-dependent | Small but cross-system | DB commit/Redis failure can lose work | Reject as correctness boundary. |
| Poll completed turns | Durable if watermark is perfect | No completion hook | Scan lag, cursor/deletion complexity, duplicate risk | Keep only as reconciliation fallback. |

### 6.3 Selected Completion Hook

For a newly completed, eligible turn, the same database transaction should:

```text
1. persist Discord delivery IDs
2. mark turn completed and clear ownership
3. create Job(job_type=discord_memory_ingest)
4. create OutboxEvent(event_type=job_enqueue)
5. commit
```

Proposed idempotency keys:

```text
job:
discord_memory_ingest:{turn_id}:{extractor_schema_version}

outbox:
job_enqueue:discord_memory_ingest:{turn_id}:{extractor_schema_version}
```

Only the initial `completed` transition creates the event. An idempotent
completion retry observes the already committed delivery/event and creates
nothing new. Pre-activation historical turns are not backfilled automatically.

The hook must check:

```text
status becomes completed
author_id is non-null/non-empty
request_text is non-empty
response_text is non-empty
at least one delivery row exists
session is present and active
guild_id/channel_id are valid
thread/private-channel policy allows ingestion
```

The model, Ollama, Redis, Qdrant, and extractor do not run in this transaction.
An extractor outage therefore cannot fail completion or add response latency.

If the small PostgreSQL outbox insert itself fails, the completion transaction
rolls back atomically. The bot can retry the idempotent completion ACK using
the same delivery IDs without sending Discord content again. This is preferable
to committing completion while silently losing ingestion work.

## 7. Full Proposed Data Flow

```text
Discord completion transaction
  ├─ completed turn + delivery rows
  ├─ durable memory-ingest Job
  └─ transactional OutboxEvent
          ↓ commit
Outbox dispatcher
          ↓
Redis/RQ queue: memory_extract
          ↓
Memory ingestion worker claims Job with lease
  ├─ revalidates completed turn/session/delivery/author
  ├─ creates or loads idempotent candidate receipt
  ├─ runs deterministic rule filter
  ├─ filtered no-op → records reason, completes Job
  └─ candidate → invokes strict Qwen extractor
                    ↓
Backend parses and validates proposal
  ├─ invalid/rejected/no-op → audit state; no turn failure
  └─ valid candidate → awaiting_conflict_check
                       not_before = created_at + 15 seconds
                    ↓
Durable delayed apply job/outbox
                    ↓
Memory apply worker
  ├─ locks canonical fact identity
  ├─ rechecks candidate/source/expiry/scope
  ├─ resolves corrections/conflicts
  ├─ creates/supersedes/deletes version rows
  ├─ writes source links
  └─ creates Qdrant index/delete Job + OutboxEvent
                    ↓ commit PostgreSQL
Qdrant index worker
  ├─ embeds canonical fact
  ├─ upserts/deletes deterministic point
  ├─ marks indexed or pending_reindex
  └─ reconciliation repairs missing/stale points
```

Every network/model operation occurs outside a PostgreSQL transaction.

## 8. Identity, Ownership, and Scope Policy

### 8.1 Trusted Identity

```text
author_id               canonical Discord member identity
author_display_name     presentation snapshot only
guild_id                mandatory isolation boundary
channel_id/thread_id    location boundary
```

Display name is never part of a unique key or permission decision. Rename and
same-display-name cases are already proven by Sprint 2A production evidence.

### 8.2 Initial Scope Vocabulary

Recommended stored scopes:

```text
member_in_guild   personal memory for subject_id within one guild
guild             shared guild/project fact
channel           channel-local fact
thread            thread/forum-post-local fact
```

`personal` is a product concept represented by:

```text
scope=member_in_guild
subject_type=member
subject_id=<stable Discord author ID>
guild_id=<current guild>
```

Personal memory is not global across guilds in the initial release.

### 8.3 Scenario Decisions

| Statement situation | Trusted subject | Recommended initial decision |
|---|---|---|
| Dũng says a durable fact/preference about himself | Current `author_id` | Eligible `member_in_guild` candidate. |
| Dũng talks about Đạt | Đạt only if stable ID is resolved from trusted reply/mention metadata | Default pending review; never silently store as Dũng's memory. |
| Đạt talks about Dũng | Dũng only if trusted stable ID is resolved | Same third-party policy. |
| “Dự án của chúng ta dùng PostgreSQL” | Registered guild/project subject | Eligible shared candidate only with explicit project/shared wording and registered fact key. |
| Two authors give conflicting values | Same canonical identity, different value | Hold all in conflict/pending review; active value unchanged. |
| User changes display name | Same `author_id` | Same subject; new display is only a new snapshot. |
| Two users share display name | Different `author_id` | Different subjects. |
| Legacy turn has NULL author ID | Unknown | Rule-filter no-op/rejected; never infer a person. |

Unknown subjects are not auto-created by the extractor. A future trusted
entity envelope should contain only IDs supplied by the backend:

```text
current author
exact reply target author
explicit Discord-mentioned member IDs persisted by the bot
registered guild/project subjects
```

The current enqueue schema does not persist mentioned human IDs. Third-person
auto-apply based only on a typed display name must remain disabled until that
metadata exists.

## 9. Deterministic Rule Filter

The filter consumes trusted turn/session metadata plus raw user request. It
does not inspect assistant response as factual evidence.

### 9.1 Hard Exclusions

Return no-op before any extractor call for:

```text
turn not completed
missing response or delivery acknowledgement
failed/cancelled turn
missing/unknown author ID
bot/system-authored content
DM
private thread with long-term memory disabled
duplicate source turn/schema version
empty/whitespace content
greeting or thanks only
emoji/joke/small talk only
ordinary question without an assertion
clearly transient current activity
content with no durable value
```

Suggested reason codes:

```text
ineligible_turn_state
missing_trusted_author
memory_policy_disabled
duplicate_source
greeting
thanks
joke_or_smalltalk
question_only
transient_state
no_durable_fact
```

### 9.2 Strong Candidates

```text
explicit_remember
explicit_forget
explicit_correction
durable_preference
hardware_configuration
software_configuration
project_decision
identity_or_name_preference
workflow_rule
explicit_shared_fact
```

Required distinctions:

| Input | Filter result | Reason |
|---|---|---|
| “Tôi đang uống trà sữa.” | no-op | Temporary state. |
| “Tôi thích trà sữa.” | candidate | Durable preference language. |
| “Hãy nhớ món yêu thích của tôi là trà sữa.” | strong candidate | Explicit remember plus preference. |
| “Tôi có một cốc trà sữa.” | no-op | Possession now does not imply preference. |

The filter must not rewrite “I have” into “I like”. It only decides whether an
extractor invocation is warranted and emits a deterministic reason code.

### 9.3 Filter Testing

Build a versioned Vietnamese fixture set containing positive and negative
pairs, negation, corrections, sarcasm, questions, transience, reply context,
two-author conflicts, and explicit remember/forget. Report precision and
recall separately; optimizing only recall would create unsafe memory.

## 10. Strict Extractor Proposal Contract

Version 1 should return exactly one JSON object and reject additional
properties. A bounded single proposal per source turn keeps idempotency and
review clear; multiple-fact extraction can use a later schema version.

Conceptual schema:

```json
{
  "schema_version": "v1",
  "operation": "create | update | delete | no_op",
  "memory_type": "preference | configuration | project_decision | identity | workflow_rule | fact",
  "subject_type": "member | guild | project | unknown",
  "subject_id": "trusted-id-or-null",
  "scope": "member_in_guild | guild | channel | thread",
  "fact_key": "registry.key-or-null",
  "canonical_fact": "normalized fact or empty for no_op",
  "evidence_text": "verbatim supporting source excerpt",
  "source_turn_id": "backend-provided UUID",
  "source_discord_message_id": "backend-provided Discord ID",
  "confidence": 0.0,
  "reason_code": "bounded-enum",
  "target_memory_id": "backend-provided candidate ID or null"
}
```

Conditional requirements:

- `create`: `target_memory_id` must be null;
- `update`/`delete`: target must be one of the backend-supplied active
  candidates and in the same scope;
- `no_op`: subject/fact/target can be null/empty but reason is required;
- `subject_id` must match a trusted entity supplied in the prompt;
- source IDs must echo exact backend constants;
- `evidence_text` must occur in normalized source text;
- `fact_key` must come from a backend registry candidate list;
- confidence is bounded `[0,1]`.

The extractor is a proposal generator. It cannot:

- write PostgreSQL;
- call Qdrant;
- create a Discord/guild/member ID;
- treat display name as identity;
- create facts beyond the evidence;
- choose an update/delete target not supplied by the backend;
- bypass scope, permissions, conflict, or sensitivity policy;
- return prose, markdown fences, or thinking text outside the JSON object.

The backend stores raw output separately from normalized output for audit.

## 11. Deterministic Backend Validation

Validation order:

```text
1. parse JSON
2. validate strict schema/additionalProperties=false
3. verify source turn ID and Discord message ID exactly
4. re-read source turn with row/current-state checks
5. require completed status, response, delivery, cleared ownership
6. verify session/guild/channel/thread policy
7. verify trusted subject map and stable subject ID
8. validate operation and conditional fields
9. validate scope against subject/channel policy
10. validate fact key registry and value schema
11. verify evidence is a normalized exact source excerpt
12. reject unsupported inference beyond evidence
13. load update/delete target under the same guild/scope/subject/fact
14. detect duplicate active value/candidate
15. apply explicit remember/forget/correction policy
16. produce rejected/no-op/pending/awaiting-conflict decision
```

Safety rules:

- confidence never bypasses subject/scope/evidence/sensitive policy;
- different guild or member fails closed;
- an unregistered fact key cannot auto-apply;
- explicit forget is authoritative only for a memory the caller is permitted
  to forget;
- invalid model output becomes a recorded rejection/no-op;
- validator/model errors fail the memory Job, not the Discord turn;
- assistant response is not accepted as evidence for a user fact.

Canonical-fact validation cannot safely be delegated back to the LLM. Initial
auto-apply should be limited to explicit statements and deterministic
normalizations. Ambiguous paraphrases go to pending review.

## 12. Durable 15-Second Conflict Window

Do not use `sleep(15)` in the API, bot, or a transaction.

Candidate state:

```text
validation_status=valid
decision=awaiting_conflict_check
conflict_key=<backend canonical identity>
not_before=<database now + 15 seconds>
```

The conflict key is derived from full canonical fields:

```text
guild_id
scope
subject_type
subject_id
fact_key
channel_id/thread_id discriminator
```

A hash may be stored for lookup/advisory locking, but it is not the business
identity, primary key, or substitute for database uniqueness.

Scheduling:

```text
candidate commit
→ delayed apply Job + OutboxEvent with available_at/not_before
→ dispatcher only publishes due events
→ process restart resumes from PostgreSQL
```

Apply transaction:

1. acquire a transaction-scoped advisory lock for the conflict key;
2. reload all due valid candidates for that full canonical identity;
3. recheck source, expiry, status, and target memory;
4. same proposed value: apply once and attach other sources as confirmations;
5. different values from different authors: mark all pending review and keep
   active memory unchanged;
6. same-author explicit correction: cancel/supersede the earlier candidate
   and apply the corrected value;
7. same-author contradiction without a correction signal: pending review,
   not last-write-wins.

Example:

```text
T1: RAM của tôi là 16 GB
T2 at +7s: À nhầm, RAM 32 GB

result:
T1 candidate superseded/cancelled by explicit correction
T2 becomes the only applicable value
active fact = RAM 32 GB
```

Retry keeps the same candidate, source turn, conflict key, and proposed value.
It never creates another sequence/version merely because a worker restarted.

## 13. PostgreSQL Design

### 13.1 Preserve Existing `memories`

Do not add Discord semantics to `metadata_json` and continue using the same
unfiltered Qdrant search. That would be insufficient isolation. Do not change
the existing API contract in Sprint 2B.

### 13.2 New `discord_memory_candidates`

Recommended fields:

```text
id UUID PK
source_turn_id UUID NOT NULL FK discord_session_turns
session_id UUID NOT NULL FK discord_conversation_sessions
source_discord_message_id TEXT NOT NULL
source_author_id TEXT NOT NULL
source_author_display_name TEXT NULL
guild_id TEXT NOT NULL
channel_id TEXT NOT NULL
thread_id TEXT NULL
extractor_schema_version TEXT NOT NULL
extractor_model TEXT NULL
filter_decision TEXT NOT NULL
filter_reason_code TEXT NOT NULL
raw_output JSONB NULL
normalized_output JSONB NULL
operation TEXT NULL
memory_type TEXT NULL
subject_type TEXT NULL
subject_id TEXT NULL
scope TEXT NULL
fact_key TEXT NULL
canonical_fact TEXT NULL
evidence_text TEXT NULL
confidence NUMERIC(4,3) NULL
target_memory_id UUID NULL
validation_status TEXT NOT NULL
decision TEXT NOT NULL
conflict_key TEXT NULL
proposed_value_hash TEXT NULL
not_before TIMESTAMPTZ NULL
expires_at TIMESTAMPTZ NULL
error_code TEXT NULL
error_message TEXT NULL
created_at / updated_at / reviewed_at TIMESTAMPTZ
reviewed_by TEXT NULL
```

Required constraints/indexes:

```text
UNIQUE(source_turn_id, extractor_schema_version)
UNIQUE(source_discord_message_id, extractor_schema_version)
CHECK confidence between 0 and 1
CHECK operation/status/decision/scope enums
INDEX(decision, not_before)
INDEX(conflict_key, decision, created_at)
INDEX(expires_at)
```

Candidates include filtered/rejected/no-op outcomes, giving one durable
idempotency receipt per eligible source/schema version.

### 13.3 New Versioned `discord_memories`

Recommended fields:

```text
id UUID PK
guild_id TEXT NOT NULL
scope TEXT NOT NULL
subject_type TEXT NOT NULL
subject_id TEXT NOT NULL
channel_id TEXT NULL
thread_id TEXT NULL
memory_type TEXT NOT NULL
fact_key TEXT NOT NULL
canonical_fact TEXT NOT NULL
status TEXT NOT NULL
version INTEGER NOT NULL
origin_candidate_id UUID NOT NULL
supersedes_memory_id UUID NULL
valid_from TIMESTAMPTZ NOT NULL
valid_until TIMESTAMPTZ NULL
expires_at TIMESTAMPTZ NULL
deleted_at TIMESTAMPTZ NULL
extractor_model TEXT NOT NULL
extractor_schema_version TEXT NOT NULL
validation_status TEXT NOT NULL
index_status TEXT NOT NULL
indexed_at TIMESTAMPTZ NULL
index_error TEXT NULL
created_at / updated_at TIMESTAMPTZ NOT NULL
```

Use the table itself as the version history:

- create inserts version 1 active;
- update marks old active row superseded and inserts the next active version
  in one transaction;
- delete marks the active version deleted and retains audit/source rows;
- canonical content and identity are never overwritten in place.

Partial unique indexes must enforce at most one active value for each complete
scope identity. Use separate indexes for member, guild, channel, and thread
scopes so nullable channel/thread fields cannot bypass uniqueness.

### 13.4 New `discord_memory_sources`

```text
memory_id UUID NOT NULL FK discord_memories
candidate_id UUID NOT NULL FK discord_memory_candidates
source_turn_id UUID NOT NULL FK discord_session_turns
source_discord_message_id TEXT NOT NULL
source_author_id TEXT NOT NULL
source_role TEXT NOT NULL
evidence_hash TEXT NOT NULL
created_at TIMESTAMPTZ NOT NULL
```

Allowed source roles:

```text
primary
supporting
confirmation
contradiction
correction
forget_request
```

Use uniqueness on `(memory_id, source_turn_id, source_role)`. Initial FKs
should prevent accidental source deletion. An explicit privacy purge must use
a separate guarded workflow that removes/de-identifies dependent evidence
before deleting source rows.

### 13.5 Versioning Option Comparison

| Design | Auditability | Complexity | Decision |
|---|---|---|---|
| Update one row in place | Low | Low | Reject. |
| Version rows + one active partial unique | High enough | Moderate | Select. |
| Full event-sourced operation log + projections | Highest | High | Defer. |

Candidate rows, version rows, and source links provide sufficient auditability
without creating an event-sourcing projection/replay system.

### 13.6 Job/Outbox Reuse

Initially reuse `jobs` and `outbox_events` rather than create
`memory_index_state` or a second job framework:

```text
discord_memory_ingest
discord_memory_apply
discord_memory_index_upsert
discord_memory_index_delete
```

Use `jobs.payload` for candidate/memory identifiers and domain metadata, never
raw secret-bearing message logs. Add a memory-specific repository and recovery
service. Generalize queue routing through an explicit job-type registry; an
unknown job type must fail closed instead of falling into document indexing.

`discord_memories.index_status` is sufficient for initial index state:

```text
pending
indexed
pending_reindex
failed
not_required
```

A separate index-state table is unnecessary until one memory version requires
multiple embeddings/collections.

## 14. Qdrant Indexing and Reconciliation

Use a new collection, recommended:

```text
discord_memories_v1
```

Do not mix scoped Discord memory with the existing global `memories`
collection.

Index flow:

```text
PostgreSQL version/source transaction
→ index Job + OutboxEvent in same transaction
→ commit
→ embedding + Qdrant operation
→ short PostgreSQL index-status transaction
```

Point ID:

```text
the UUID of the immutable discord_memories version row
```

This is deterministic for retries and natively accepted by Qdrant.

Minimum payload:

```json
{
  "memory_id": "<version UUID>",
  "guild_id": "<guild>",
  "subject_type": "member|guild|project",
  "subject_id": "<stable subject>",
  "scope": "member_in_guild|guild|channel|thread",
  "channel_id": "<nullable>",
  "thread_id": "<nullable>",
  "memory_type": "<type>",
  "fact_key": "<canonical key>",
  "version": 1,
  "status": "active"
}
```

The vector input is canonical fact text, not extractor reasoning or raw
conversation history.

Update/delete:

- new active version gets a new deterministic point;
- superseded/deleted point gets an explicit delete event;
- an upsert/delete retry is idempotent;
- exhausted retry sets `pending_reindex`;
- Qdrant failure never rolls back canonical PostgreSQL memory;
- retrieval revalidates returned memory IDs/status against PostgreSQL, so a
  stale Qdrant point cannot enter the model prompt;
- reconciliation compares PostgreSQL active rows with Qdrant IDs/payload and
  repairs missing/stale/orphan points;
- rebuild reads only active PostgreSQL versions.

The currently configured `qwen3-embedding:0.6b` is the candidate embedding
model, but dimension/retrieval quality must be measured before production
activation.

## 15. Future Retrieval Flow

```text
current Discord author + canonical session
→ memory-query gate
→ exact PostgreSQL fact lookup first
→ allowed scope calculation
→ Qdrant semantic query with mandatory metadata filters
→ PostgreSQL active-state/permission revalidation
→ optional rerank
→ token budget
→ trusted Discord memory context
→ main LLM
```

Context domains remain explicit:

```text
recent conversation history         raw session turns
personal long-term memory           member_in_guild + current author
shared guild/project memory         guild scope
channel/thread memory               exact canonical location
document RAG                        documents collection/chunks
```

Memory and document vectors use separate collections and code paths. A request
must not search both without an explicit namespace/type gate.

Mandatory retrieval rules:

- guild filter is always present;
- personal memory additionally filters current stable subject ID;
- channel/thread scopes require exact location;
- only PostgreSQL `status=active` is trusted;
- disputed, superseded, expired, and deleted versions are excluded;
- private-thread/DM policy is checked before query;
- exact facts outrank semantic results.

## 16. Idempotency and Failure Policy

| Failure/race | Key/policy |
|---|---|
| One completed turn creates one ingest event | Unique job/outbox key by `turn_id + extractor_schema_version`. |
| Duplicate outbox delivery | Deterministic RQ job ID; completed event not republished. |
| Extractor retry | Same Job/candidate; no second candidate. |
| Invalid JSON/schema | Candidate rejected/failed with bounded error; turn remains completed. |
| Worker crash | Lease expires; memory-specific recovery requeues same Job. |
| Redis unavailable | Outbox remains retrying in PostgreSQL. |
| PostgreSQL memory commit succeeds, Qdrant fails | Memory stays canonical; `pending_reindex`; retry/reconciliation. |
| Update/delete retry | Target/version rechecked under canonical identity lock; idempotent candidate origin. |
| Stale vector | PostgreSQL revalidation drops it; delete/reconcile later. |
| Correction within 15 seconds | Explicit correction supersedes earlier candidate, preserves source trail. |
| Conflicting authors | Pending review; no last-write-wins. |
| Source turn missing before extraction | Job becomes `source_missing` no-op/failure; never infer content. |
| User forget request | Guarded delete candidate; PostgreSQL status changes first, Qdrant deletion async. |

Memory job errors must never change Discord delivery IDs, turn FIFO status,
response content, or completion state.

## 17. Privacy and Isolation

### 17.1 Safe Initial Defaults

Recommended defaults:

```text
DM ingestion/retrieval                  disabled
private-thread long-term memory         disabled
personal memory scope                   member_in_guild
cross-guild personal reuse              disabled
third-party personal auto-apply         disabled
unknown subject auto-apply              disabled
shared fact auto-apply                  only explicit + registered key
sensitive fact auto-apply               disabled
extractor initial mode                  dry-run
```

### 17.2 Inspection and Forget

Do not expose new Discord memory through existing unauthenticated `/memory/*`.
Future governance endpoints/commands must enforce:

- a user sees only their personal memory in the current guild;
- guild shared-memory review/delete requires an explicit admin policy;
- forget-me is scoped to current user + guild;
- delete marks PostgreSQL first and emits Qdrant delete work;
- purge requires confirmation, rate limiting, and an audit record;
- production logs contain IDs/reason codes, not raw memory evidence.

### 17.3 Product Decisions Required Before Auto-Apply/Retrieval

These do not block foundation implementation but must be decided before
production activation:

1. Can a member ever auto-create personal memory about another member, or is
   it always pending/rejected?
2. Who may assert/update a shared project fact: any member, channel role, or
   admin-approved authors?
3. Which fact keys are sensitive and never auto-applied?
4. When a user leaves a guild, should member-in-guild memory be retained but
   hidden, expired, or purged?
5. When a channel/thread is deleted, should location-scoped memory be expired
   or retained for admin audit?
6. Should personal memory ever follow the same Discord account across guilds?
   The recommendation is no for the first release.
7. What retention applies to rejected candidates and evidence excerpts?

Until decided, fail closed using the safe defaults above.

## 18. Phase Plan

### 2B.1 — Audit/design

This document. No code/schema/runtime changes.

### 2B.2 — PostgreSQL candidate foundation

- create `discord_memory_candidates`, `discord_memories`, and
  `discord_memory_sources`;
- add CHECK/FK/partial unique indexes;
- preserve the existing `memories` table/API;
- migration upgrade/downgrade/re-upgrade only on `POSTGRES_TEST_URL`;
- repository tests for scope isolation, versioning, sources, and candidate
  idempotency;
- no runtime migration in the code/test turn.

### 2B.3 — Completion outbox/hook

- add memory Job + OutboxEvent creation to the Discord completion transaction;
- unique event per turn/schema version;
- generalize explicit queue routing;
- add memory-specific claim/lease/recovery task shell;
- prove Redis/extractor outage cannot block chat/model or Discord delivery;
- initially let the worker record an ingestion receipt and no-op.

### 2B.4 — Rule filter

- deterministic filter and reason codes;
- Vietnamese precision/recall fixture;
- no model call for excluded turns;
- policy gates for DM/private thread/legacy author.

### 2B.5 — Qwen3.5:2b extractor adapter

- add dedicated config and adapter;
- install/pull model only in an explicitly approved environment gate;
- `think=false`, JSON Schema mode, temperature 0, seed, context 4096;
- strict schema and 100–300-case benchmark;
- dry-run only; no memory apply.

### 2B.6 — Validation and conflict window

- trusted-entity envelope and fact registry;
- deterministic proposal validator;
- durable 15-second delayed apply;
- correction, same-value merge, multi-author conflict;
- version transaction and source links;
- remain dry-run until acceptance metrics pass.

### 2B.7 — Qdrant indexing/reconciliation

- create separate Discord memory collection in a controlled gate;
- index/delete jobs and payload filters;
- PostgreSQL post-filter;
- pending-reindex and reconciliation/rebuild;
- no retrieval activation yet.

### 2B.8 — Scoped retrieval

- exact PostgreSQL lookup first;
- personal/guild/channel/thread permission filter;
- semantic search and rerank/token budget;
- explicit separation from document RAG and UI memory;
- model-input inspection tests.

### 2B.9 — Production activation/canary

- fresh backup and migration gates;
- backend/worker reload;
- start with dry-run and metrics;
- canaries for remember, no-op, correction, conflict, forget, guild isolation,
  stale Qdrant, worker restart, and retrieval;
- auto-apply/retrieval only after privacy decisions and benchmark gates.

The phases should not be merged initially. The existing infrastructure is
reusable but hard-coded enough that schema, completion durability, filtering,
model compatibility, apply logic, indexing, and retrieval deserve separate
failure boundaries.

## 19. Required Test Matrix

Foundation and migration:

- upgrade/downgrade/re-upgrade from `20260728_15`;
- runtime/test database guard;
- candidate idempotency;
- one active memory per canonical identity for every scope;
- immutable content/version history;
- source FK/uniqueness;
- existing `/memory/*` and Web UI behavior unchanged.

Completion/outbox:

- completion and ingest event atomic;
- duplicate completion creates no duplicate event;
- failed/cancelled/unknown-author/no-delivery turn creates no event;
- Redis down leaves outbox durable;
- two dispatchers publish once;
- memory failure does not alter completed Discord turn.

Filter/extractor/validator:

- required no-op/candidate examples;
- stable ID vs display-name rename/same-name;
- self vs third-party vs shared project;
- strict JSON/additional fields;
- forged subject/source/target rejected;
- evidence mismatch rejected;
- update/delete candidate allowlist;
- invalid output recorded without worker crash.

Conflict/version:

- same-author explicit correction at +7 seconds;
- different-author conflict inside 15 seconds;
- same-value confirmations merge sources;
- restart before `not_before`;
- concurrent apply uses one active version;
- expired candidate cannot apply.

Qdrant/retrieval:

- deterministic point ID;
- guild/member/channel/thread filters;
- no cross-session/guild result;
- update/delete stale point excluded by PostgreSQL;
- Qdrant failure leaves canonical memory;
- reconciliation/rebuild idempotent;
- document RAG points never appear as memory.

Privacy/governance:

- show-me current member/current guild only;
- forget current member/current guild only;
- shared delete permission;
- user leave/channel delete policy once decided;
- no raw evidence in production logs.

## 20. Risks

| Risk | Mitigation |
|---|---|
| Reusing global UI memory leaks across users | Separate PostgreSQL tables and Qdrant collection. |
| Existing queue sends unknown jobs to document index | Explicit job-type registry; unknown fails closed. |
| Model invents subject/fact | Trusted entity and fact-key allowlists; strict backend validation. |
| Display-name identity collision | Stable `author_id` only. |
| Third-party claim becomes personal fact | Disable third-party auto-apply initially. |
| Conflict becomes last-write-wins | Durable window + canonical lock + pending review. |
| Qdrant stale point leaks deleted memory | PostgreSQL active-state revalidation before prompt. |
| Extractor increases Discord latency | Outbox after completion; worker/model outside chat path. |
| Invalid Qwen JSON | Schema mode, fallback JSON mode, strict parse, benchmark, dry-run. |
| Old turns are ingested unexpectedly | No automatic backfill; cutover/versioned event key. |
| Source edit/delete invalidates memory | Future edit/delete reevaluation job; fail closed until implemented. |
| Evidence retention conflicts with forget | Explicit guarded purge/de-identification policy before activation. |

## 21. Completion Decision

The source and runtime provide a trustworthy completed-turn boundary,
stable Discord speaker identity, exact source/reply/delivery IDs, PostgreSQL
transactions, and a reusable durable outbox/lease pattern. The existing Web UI
memory is intentionally unsuitable for Discord structured memory, but it can
remain isolated while new candidate/version/source tables are implemented.

Implementation may begin with the PostgreSQL candidate foundation and
completion outbox in isolated tests. Production auto-apply and retrieval remain
gated by extractor benchmarking, conflict validation, Qdrant reconciliation,
and the listed privacy/product decisions.

```text
SPRINT 2B.1 MEMORY INGESTION FOUNDATION READY FOR IMPLEMENTATION
```

## 22. Sprint 2B.2 — PostgreSQL Discord Memory Foundation

### 22.1 Scope and activation status

Sprint 2B.2 implements only the isolated PostgreSQL domain foundation:

- Alembic schema;
- ORM and immutable V1 state vocabulary;
- candidate, versioned-memory, and source-link repository operations;
- isolated PostgreSQL migration/repository tests.

It does **not** add a completion hook, outbox event, RQ worker, filter,
extractor, conflict-window scheduler, Qdrant indexing/retrieval, API, or UI.
No production migration or process restart was performed. Consequently, no
Discord turn is ingested automatically in this sprint.

### 22.2 Migration

The new revision is:

```text
revision:      20260728_16
down_revision: 20260728_15
file:          backend/alembic/versions/20260728_16_discord_memory_foundation.py
```

`alembic heads` reports exactly one head, `20260728_16`.

The revision creates three tables that are separate from the existing Web UI
`memories` table:

#### `discord_memory_candidates`

The table stores the trusted Discord source identity/location, extractor and
filter metadata, normalized proposal fields, validation/decision state,
conflict scheduling fields, errors/review metadata, and timestamps.

Database boundaries include:

- `UNIQUE(source_turn_id, extractor_schema_version)`;
- `UNIQUE(source_discord_message_id, extractor_schema_version)`;
- foreign keys to `discord_session_turns`,
  `discord_conversation_sessions`, and `discord_memories`;
- confidence restricted to `[0, 1]` when present;
- bounded TEXT checks for operation, scope, filter decision, validation
  status, and candidate decision;
- indexes for decision scheduling, conflict ordering, expiry, and
  guild/member audit lookup.

The `target_memory_id` foreign key is added after `discord_memories` is
created. The downgrade first removes source links, then this circular-side
foreign key, then memories and candidates.

#### `discord_memories`

Every row is an immutable canonical fact version. Content is not overwritten
when a correction is applied: the old row becomes `superseded` and the new
row receives `version + 1`.

Database boundaries include:

- `version >= 1`;
- bounded status, scope, validation status, and index status;
- exact location checks for `member_in_guild`, `guild`, `channel`, and
  `thread`;
- foreign keys to the originating candidate and superseded memory;
- one produced memory version per `origin_candidate_id`;
- four partial unique indexes that permit at most one active version for each
  canonical scope identity;
- four scope-specific unique version indexes that prevent duplicate version
  numbers even after a row is superseded or deleted.

The canonical identity always includes `guild_id` and the exact scope fields.
Display names never participate in identity.

#### `discord_memory_sources`

The source table links a memory version to the exact candidate, Discord turn,
message ID, stable author ID, evidence hash, and a bounded source role:

```text
primary
supporting
confirmation
contradiction
correction
forget_request
```

`UNIQUE(memory_id, source_turn_id, source_role)` makes attachment
idempotent. All evidence foreign keys use `RESTRICT`; normal version
supersede/delete operations therefore cannot cascade-delete audit evidence.
A future privacy purge must use a separate guarded workflow.

### 22.3 Shared domain vocabulary

The immutable Sprint 2B V1 vocabulary is centralized in:

```text
backend/app/postgres/discord_memory_constants.py
```

Both migration CHECK expressions and ORM CHECK expressions use those same V1
tuples. PostgreSQL native ENUM types were intentionally not introduced,
matching the repository's existing TEXT + CHECK convention.

### 22.4 ORM

`backend/app/postgres/models.py` now maps:

- `DiscordMemoryCandidate`;
- `DiscordMemory`;
- `DiscordMemorySource`.

The existing `Memory` model is unchanged. No relationship is configured for
automatic eager loading, so the candidate/memory circular audit references do
not create an eager-load loop.

### 22.5 Repository API

The domain-specific repository is:

```text
backend/app/postgres/discord_memory_repositories.py
```

It is deliberately not part of `PostgresAuxiliaryStore`.

Candidate operations:

- `create_or_get_candidate(...)`;
- `get_candidate(..., guild_id=...)`;
- `get_candidate_by_source(..., guild_id=...)`;
- `update_candidate_result(...)`.

Candidate creation compares stable source identity and both idempotency keys.
An identical retry returns the stored row. Reusing either key with a different
turn/message/author/location is an explicit
`DiscordMemoryConflictError`. A display-name change is not an identity
conflict and does not mutate the original display snapshot.

Memory/version operations:

- `create_active_version(...)`;
- `get_active_memory(...)`;
- `supersede_active_version(...)`;
- `version_history(...)`;
- `mark_deleted(...)`.

Source operations:

- `attach_source(...)`;
- `list_sources(..., guild_id=...)`.

All public lookup paths require or embed `guild_id`. A source candidate from a
different guild cannot be attached to a memory.

### 22.6 Version transaction and concurrency strategy

The repository is caller-transaction-owned. It does not commit internally.
For a canonical memory mutation it:

```text
take PostgreSQL transaction advisory lock for the full canonical field tuple
→ lock/read the active row
→ close the old version when updating
→ insert the next active immutable version
→ attach the exact source link
→ flush
→ caller commits
```

The advisory-lock hash is only a PostgreSQL lock key; it is not a business
identity or primary key. Queries and uniqueness use the complete trusted
canonical fields.

If any statement fails, the caller transaction rolls back the old-row state,
new version, source link, and candidate state together. Same-candidate retries
return the already-created version. Concurrent create or update attempts leave
at most one active version.

Deletion is soft:

```text
status = deleted
valid_until/deleted_at set
history and sources retained
```

### 22.7 Isolated test results

All database mutation tests targeted only `local_ai_core_test`; a guard
requires that exact database name and rejects `local_ai_core`.

Migration/foundation:

```text
35 passed
0 failed
0 skipped
1 warning
```

This includes:

- `20260728_15 → 20260728_16`;
- downgrade to `20260728_15`, removal of all three tables, then re-upgrade;
- final test database revision `20260728_16`;
- legacy `memories` columns unchanged;
- candidate turn/message idempotency and conflict behavior;
- confidence/state/scope database constraints;
- stable author identity under rename and same-display-name cases;
- four-scope active uniqueness and location isolation;
- immutable version 1/version 2 history;
- transaction rollback and concurrent create/update;
- soft delete with retained history;
- idempotent and guild-isolated source attachment;
- restrictive source evidence foreign keys.

Existing backend regression:

```text
72 passed
0 failed
0 skipped
1 warning
```

The selection covers `/memory/*`, chat `use_memory`,
`PostgresAuxiliaryStore`, auxiliary schema, Discord session/turn/delivery,
speaker attribution, and user/bot-response reply grounding.

Bot/client regression:

```text
27 passed
0 failed
0 skipped
1 warning
```

This covers the Discord API client, persistent feature flag, and canonical
channel/thread/forum location.

Python `compileall` and `git diff --check` passed. The warnings are existing
Starlette/httpx and Python `audioop` deprecations; neither is a test failure.
No test contacted Ollama, Qdrant, or Redis.

### 22.8 Production remained unchanged

The final production check was read-only:

```text
database:                      local_ai_core
revision:                      20260728_15
conversations:                 7
messages:                      80
memories:                      0
discord_conversation_sessions: 1
discord_session_turns:         28
discord_turn_deliveries:       2
```

`discord_memory_candidates`, `discord_memories`, and
`discord_memory_sources` are absent from production. No runtime row,
completion event, Qdrant collection, or backfill was created; backend and bot
were not restarted.

The isolated test database ended at `20260728_16`, with all three new domain
tables present and zero candidate/memory/source rows after fixture cleanup.

### 22.9 Remaining work for Sprint 2B.3

Sprint 2B.3 may add the completion-transaction outbox hook only after a
separate production migration gate for revision 16. It must preserve these
boundaries:

- only completed, delivered turns with stable author metadata are eligible;
- one versioned ingestion event per source turn/schema;
- Discord completion remains successful if memory processing later fails;
- no extractor or Qdrant work runs in the completion transaction;
- no automatic backfill of turns 1–28.

Rule filtering, Qwen extraction, 15-second conflict scheduling, validation,
Qdrant indexing, and retrieval remain later phases.

### 22.10 Sprint 2B.2 completion decision

```text
SPRINT 2B.2 POSTGRESQL DISCORD MEMORY FOUNDATION CODE/TEST COMPLETE
```

This status means the schema and repository foundation are implemented and
verified in the isolated test database. It does not mean memory ingestion is
active.

## 23. Sprint 2B.3 — Completion Outbox and Memory Worker Foundation

### 23.1 Scope and current activation state

Sprint 2B.3 adds only the durable transport path:

```text
first successful Discord completion transaction
→ discord_memory_ingest Job
→ JOB_ENQUEUE_REQUESTED OutboxEvent
→ explicit memory_extract RQ route
→ receipt-only memory worker
→ idempotent discord_memory_candidates row
```

The worker does not run a rule filter, Ollama/Qwen model, proposal validator,
conflict-window apply, `discord_memories` mutation, source linking, Qdrant
operation, or retrieval.

Production was not migrated or reloaded. The production feature flag remains
absent/default-false and no production memory job, event, or candidate was
created.

### 23.2 Audited completion transaction boundary

The deployed completion boundary before this change was:

```text
DiscordTurnService.complete()
└─ caller-owned Session.begin()
   ├─ lock discord_session_turns row
   ├─ verify execution ownership and delivery-ID conflict
   ├─ insert discord_turn_deliveries
   ├─ set turn.status = completed
   ├─ set completed_at
   ├─ clear worker_id / lease_expires_at / heartbeat_at
   └─ flush + commit
```

`DiscordMemoryCompletionService.on_first_completion()` now runs inside that
same `Session.begin()` only when `complete_turn()` returns `completed`.
Idempotent completion retries return `idempotent` and never call the hook.

With ingestion enabled, the transaction is:

```text
delivery rows + completed turn
→ flush so eligibility sees canonical rows
→ eligibility check
→ memory Job + matching OutboxEvent
→ one commit
```

Redis, RQ, Ollama, filtering, and Qdrant are not called in the transaction.
If Job or Outbox persistence fails, a
`DiscordMemoryCompletionTransportError` escapes and the complete transaction
rolls back. The already-sent Discord response IDs can then be acknowledged
again without sending another Discord response.

### 23.3 Configuration and safe defaults

`Settings` and `.env.example` now define:

```text
DISCORD_MEMORY_INGESTION_ENABLED=false
DISCORD_MEMORY_EXTRACTOR_SCHEMA_VERSION=v1
DISCORD_MEMORY_QUEUE_NAME=memory_extract
```

The memory path does not inspect or reuse
`INGESTION_EXECUTION_BACKEND=thread`. That setting remains specific to the
existing document service. Memory publication is through its explicit
outbox/RQ route only.

### 23.4 Eligibility

The hook creates transport records only when all trusted state is present:

- the turn really transitioned to `completed`;
- stable `author_id`, non-empty request, and non-empty response exist;
- at least one `discord_turn_deliveries` row exists;
- the mapped Discord session exists and is `active`;
- `guild_id` and `channel_id` are non-empty;
- `thread_id IS NULL`.

The last condition is deliberate: current persisted session metadata cannot
reliably distinguish public, private, and forum-thread memory policy. Thread
ingestion therefore fails closed until trusted channel/thread visibility
metadata is added.

No transport is produced for failed/cancelled turns, missing authors,
delivery-less or historical completed turns, DM-like locations, inactive
sessions, or current thread sessions. There is no startup scan or backfill.

### 23.5 Deterministic Job and Outbox identity

Keys are:

```text
Job:
discord_memory_ingest:{turn_id}:{extractor_schema_version}

Outbox:
job_enqueue:discord_memory_ingest:{turn_id}:{extractor_schema_version}
```

The Job payload contains only:

```json
{
  "turn_id": "<uuid>",
  "session_id": "<uuid>",
  "extractor_schema_version": "v1"
}
```

Raw request, response, evidence, and display text are not copied into the Job
payload. Job/Outbox creation verifies an existing deterministic pair and
raises a conflict if either idempotency key maps to different bounded
metadata. The locked Discord turn serializes concurrent completion retries;
database uniqueness remains the final boundary.

Implementation:

```text
backend/app/postgres/discord_memory_job_repository.py
backend/app/services/discord_memory_completion_service.py
```

### 23.6 Revision 20260728_17

Sprint 2B.2 revision 16 correctly bounded `filter_decision`, but its V1
vocabulary only contained:

```text
candidate
no_op
```

Neither value truthfully represents a durable receipt before the rule filter
runs. Revision 16 was not edited. A minimal follow-up revision was created:

```text
revision:      20260728_17
down_revision: 20260728_16
file:          20260728_17_discord_memory_filter_not_run.py
```

It changes only
`ck_discord_memory_candidates_filter_decision`, adding:

```text
not_run
```

Downgrade restores the immutable V1 vocabulary. ORM/repository code uses the
V2 vocabulary. The isolated migration drill verified
`16 → 17 → 16 → 17`; the test database finished at revision 17.

### 23.7 Explicit queue routing

The former routing logic effectively treated every non-extraction job as a
document indexing job. It has been replaced by a bounded registry:

| Job type | Queue suffix | RQ task |
|---|---|---|
| `extract_document` | `ocr` | `app.workers.tasks.extract_document` |
| `index_document` | `index` | `app.workers.tasks.index_document` |
| `discord_memory_ingest` | configured `memory_extract` | `app.workers.memory_tasks.discord_memory_ingest` |

An unknown type raises `UnknownJobTypeError` before an RQ queue is selected.
The outbox event is marked `failed`, not successfully dispatched or routed to
document indexing. Existing OCR/index routes retain their queue and task
names. RQ IDs remain the durable PostgreSQL Job IDs.

The production outbox-dispatcher script now passes the configured memory queue
name to `JobQueueService`; it was not started or reloaded in this sprint.

### 23.8 Receipt-only worker

The separate worker path is:

```text
app.workers.memory_tasks.discord_memory_ingest
→ DiscordMemoryWorkerService
→ DiscordMemoryJobRepository
→ DiscordMemoryRepository.create_or_get_candidate
```

It:

1. atomically claims only `discord_memory_ingest`;
2. assigns worker ownership, attempt number, heartbeat, and lease;
3. re-reads the canonical Job payload, turn, session, and delivery rows;
4. revalidates eligibility;
5. creates/gets one candidate keyed by source turn/message + schema;
6. completes the same Job and clears ownership.

The receipt state is explicit:

```text
filter_decision   = not_run
filter_reason_code = foundation_receipt_only
validation_status = pending
decision          = deferred
extractor_model   = NULL
```

Stable `author_id`, exact turn/message/session/guild/channel IDs, and the
display snapshot are copied from canonical PostgreSQL rows. Display name is
not identity.

No `discord_memories` or `discord_memory_sources` row is created. The worker
module has no Ollama or Qdrant dependency.

### 23.9 Failure, lease, and recovery

Redis is only contacted by the outbox dispatcher after the completion commit.
If Redis is unavailable:

```text
Discord turn/delivery: unchanged and completed
Job:                  queued
Outbox:               retrying with bounded error
```

If a worker is unavailable, Job and Outbox remain durable. A duplicate RQ
delivery cannot claim a completed/running Job a second time and cannot create
a second candidate.

Worker source failures use bounded reasons:

```text
source_missing
source_ineligible
session_inactive
delivery_missing
author_missing
thread_policy_disabled
```

Unexpected worker failure moves the same Job to `retrying` while leaving the
completed Discord turn and deliveries untouched. Attempts exhausted becomes
`failed`.

`DiscordMemoryRecoveryService` processes only stale
`discord_memory_ingest` jobs. Retry clears old ownership and resets the same
OutboxEvent to retrying; it does not create another Job. Exhaustion records
`WORKER_STALE`. `JobRecoveryService` and
`PostgresDocumentRepository.queued_jobs_without_redis()` now explicitly
filter document job types, preventing either recovery path from entering the
other domain.

The separate operator shell is:

```text
backend/scripts/recover_discord_memory_jobs.py
```

It supports guarded `--dry-run` or `--execute`.

### 23.10 Health and metrics

Operational health reports:

- configured memory queue name;
- `worker_memory = disabled | unavailable | ok`;
- `memory_ingestion = disabled | unavailable | ok`.

When the feature is disabled, a missing memory worker does not degrade overall
health. When enabled without a registered memory worker, health is degraded
and the component is explicitly unavailable.

Metrics expose counts for:

- pending memory jobs;
- retrying memory jobs;
- failed memory jobs;
- separate pending, retrying, and processing memory Outbox events;
- memory queue length.

No raw request, response, or evidence content is emitted.

### 23.11 Tests

All mutation tests used only `local_ai_core_test`. Redis/RQ behavior was
tested with fakes/mocks; no real Redis, Ollama, or Qdrant service was invoked.

Focused Sprint 2B.3:

```text
30 passed
0 failed
0 skipped
1 warning
```

Coverage includes migration 17, safe configuration defaults, completion
atomicity, forced Job/Outbox rollback, sequential/concurrent retry
idempotency, eligibility exclusions, dispatcher retry/concurrency,
fail-closed unknown routing, worker claim/heartbeat/receipt idempotency,
source disappearance, worker failure, stale/exhausted recovery, domain
isolation, and health/metrics.

Regression selection:

```text
126 passed
0 failed
0 skipped
1 warning
```

It covers Discord completion/delivery/FIFO, speaker and reply correlation,
Sprint 2B.2 repository/migration, transactional outbox, stale recovery,
reconciliation, document job foundations, `/memory/*`, Web UI chat
`use_memory`, and the PostgreSQL auxiliary store.

Bot/client regression:

```text
27 passed
0 failed
0 skipped
1 warning
```

Total:

```text
183 passed
0 failed
0 skipped
3 warnings
```

Warnings are the existing Starlette/httpx and Python `audioop` deprecations.
Python compile and `git diff --check` passed.

### 23.12 Production unchanged

Final production inspection was read-only:

```text
database                       local_ai_core
revision                       20260728_15
conversations                  7
messages                       80
legacy Web UI memories         0
jobs                           0
outbox_events                  0
discord_conversation_sessions 1
discord_session_turns          28
discord_turn_deliveries        2
Discord memory tables          absent
health                         HTTP 200 / status=ok
```

Backend and Discord bot Python process trees remained running. Neither was
restarted or reloaded. Revision 16/17 was not applied to production, the
feature flag was not enabled, and no production worker/job/event/candidate or
backfill was created.

The isolated test database finished at revision `20260728_17`; all three
Discord memory domain tables contained zero rows after fixture cleanup.

### 23.13 Remaining work for Sprint 2B.4

Sprint 2B.4 can implement the deterministic rule filter over these receipt
rows. It must:

- claim only deferred `not_run` receipts;
- use canonical source rows, not Job payload text;
- produce bounded candidate/no-op decisions and reason codes;
- remain restart/idempotency safe;
- not call Qwen, Qdrant, or apply canonical memories yet.

Production activation of revisions 16 and 17, backend/outbox reload, memory
worker deployment, and feature-flag enablement require separate gates.

### 23.14 Completion decision

```text
SPRINT 2B.3 COMPLETION OUTBOX/MEMORY WORKER FOUNDATION CODE/TEST COMPLETE
```

This means the durable transport and receipt-only worker foundation are
implemented and tested. Discord memory ingestion and automatic memory apply
are not active.

## 24. Sprint 2B.4 — Deterministic Memory Rule Filter

### 24.1 Scope and architecture

Sprint 2B.4 replaces the receipt-only worker step with a deterministic,
high-precision gate:

```text
claim discord_memory_ingest Job
→ re-read canonical turn/session/delivery rows
→ create/get the idempotent candidate receipt
→ run discord_memory_rule_filter_v1 on raw user request_text
→ persist the terminal filter result
→ complete the same Job
```

The filter answers only whether the current trusted Discord user message
should be sent to a future extractor. It does not rewrite evidence, choose a
subject or scope, produce an operation, create canonical memory, call Ollama,
embed content, or call Qdrant. Assistant response text is required by the
upstream completion eligibility gate but is not supplied to the filter as
evidence.

### 24.2 Revision and bounded vocabulary

The existing revision 17 vocabulary could represent only `candidate`,
`no_op`, and the foundation `not_run` state. It could not truthfully represent
a policy rejection or terminal no-op validation. Revision 17 was not edited.
A minimal revision was added:

```text
revision:      20260728_18
down_revision: 20260728_17
file:          20260728_18_discord_memory_filter_vocabulary.py
```

It:

- adds `rejected_policy` to the candidate filter-decision CHECK;
- adds `not_required` to the candidate validation-status CHECK;
- adds a bounded CHECK for `filter_reason_code`.

The reason-code vocabulary is centralized in
`discord_memory_constants.py`. It contains explicit intent, durable category,
no-op, and policy reasons. Migration drill
`17 → 18 → 17 → 18` passed and the isolated test database finished at head
`20260728_18`.

### 24.3 Typed contract and normalization

`DiscordMemoryFilterInput` accepts trusted IDs and source state:

```text
turn/message/author/guild/channel/thread IDs
raw request_text
turn status
delivery existence
session state
policy flags
source role
duplicate-source signal
```

`DiscordMemoryFilterResult` returns:

```text
decision
reason_code
candidate_strength
detected_intent
matched_rules
policy_version=discord_memory_rule_filter_v1
```

Text matching uses Unicode NFC, surrounding trim, repeated-whitespace
collapse, and case-insensitive matching. The raw source is never changed.
Negations such as `không`, `chưa`, and `đừng` are preserved; no stemming or
content-derived identity is used. Discord mentions are removed only from the
classification view, not from persisted evidence.

### 24.4 Rule priority

Rules execute in this order:

```text
trusted-metadata/policy exclusions
→ explicit forget
→ explicit correction
→ explicit shared remember
→ explicit remember
→ identity/workflow/hardware/software/project/preference assertions
→ transient state
→ greeting/thanks/small talk
→ question-only
→ no durable fact
```

This ordering lets a strong fact win in mixed content:

```text
Máy tôi có RAM 32 GB, vậy chạy model nào?
→ candidate / hardware_configuration

Cảm ơn nhé, từ giờ hãy trả lời bằng tiếng Việt.
→ candidate / durable_preference
```

Critical no-op behavior is explicit:

```text
Tôi có một cốc trà sữa.
→ no_op / transient_state

PostgreSQL là gì?
→ no_op / question_only

Chúng ta chưa chốt dùng PostgreSQL.
→ no_op / no_durable_fact
```

Possession is not converted into preference. A question containing a trusted
durable assertion is not discarded merely because it has a question mark.

### 24.5 Persistence and idempotency

Every worker first creates/gets the existing `not_run` receipt keyed by source
turn/message plus extractor schema version. The terminal filter metadata is
stored in `normalized_output` with:

```json
{
  "stage": "rule_filter",
  "policy_version": "discord_memory_rule_filter_v1",
  "decision": "candidate|no_op|rejected_policy",
  "reason_code": "...",
  "candidate_strength": "strong|normal|none",
  "detected_intent": "...",
  "matched_rules": ["..."]
}
```

This object is explicitly filter metadata, not extractor output.
`raw_output`, `operation`, `canonical_fact`, `subject_id`, and model
confidence remain NULL.

State mapping is:

| Filter result | validation_status | candidate decision |
|---|---|---|
| `candidate` | `pending` | `deferred` |
| `no_op` | `not_required` | `no_op` |
| `rejected_policy` | `rejected` | `rejected` |

The candidate row is locked before transition. Repeating the identical result
for the same policy version is idempotent. A different result or a new policy
version cannot silently overwrite the terminal V1 result; it raises an
explicit conflict. Future re-evaluation therefore needs a deliberate schema
version/policy workflow rather than an in-place rewrite. Display name never
participates in receipt identity.

The RQ entrypoint passes the current ingestion feature flag into the worker.
If policy is disabled after an event was durably created but before it runs,
the receipt terminates as `rejected_policy / memory_policy_disabled`; no
extractor or canonical-memory work follows.

A duplicate RQ delivery cannot claim a completed Job. A filter exception
rolls back its candidate/filter transaction and retries the same memory Job;
the completed Discord turn and delivery rows remain unchanged.

### 24.6 Vietnamese fixture and metrics

The versioned fixture is:

```text
backend/tests/fixtures/discord_memory_rule_filter_v1.json
```

It contains 100 non-generated assertions covering explicit
remember/forget/correction, preferences, hardware, software, project
decisions, workflow, shared facts, greetings, thanks, question-only, mixed
messages, transient possession, negation, light typos, Discord mentions,
accented/unaccented Vietnamese, and reply text without a new fact.

Measured confusion matrix:

| | Predicted candidate | Predicted no-op |
|---|---:|---:|
| Expected candidate | 66 | 0 |
| Expected no-op | 0 | 34 |

Metrics:

```text
candidate precision                 1.00
candidate recall                    1.00
no-op precision                     1.00
reason-code accuracy                1.00
explicit remember/forget/correction 1.00 recall
critical false positives            0
false negatives                     0
```

These metrics describe the bounded V1 fixture, not arbitrary real-world
language. Unknown or ambiguous wording remains deliberately conservative.

### 24.7 Tests

Focused rule-filter suite:

```text
113 passed
0 failed
0 skipped
1 warning
```

Migration drill:

```text
3 passed
0 failed
0 skipped
1 warning
```

Worker/foundation database tests:

```text
62 passed
0 failed
0 skipped
1 warning
```

The combined selected regression suite, including all of the above plus
Discord completion/delivery/reply/session tests, job routing, dispatcher and
recovery, document routing, `/memory/*`, chat and conversation APIs, passed:

```text
263 passed
0 failed
0 skipped
1 warning
```

Root-level Discord bot/client/control regressions:

```text
45 passed
0 failed
0 skipped
1 warning
```

Unique selected total:

```text
308 passed
0 failed
0 skipped
2 warnings
```

The warnings are the existing Starlette/httpx test-client and Python
`audioop` deprecations. Python compile and `git diff --check` passed. Tests
used `POSTGRES_TEST_URL` with database `local_ai_core_test`; Redis/RQ routing
used fakes/mocks. No Ollama or Qdrant call was added.

### 24.8 Production state

Final production inspection was read-only:

```text
database                       local_ai_core
revision                       20260728_15
conversations                  7
messages                       80
legacy Web UI memories         0
jobs                           0
outbox_events                  0
discord_conversation_sessions 1
discord_session_turns          28
discord_turn_deliveries        2
Discord memory tables          absent
memory feature flag            false
health                         HTTP 200 / status=ok
```

Sprint 2B.4 does not activate production. Revisions 16, 17, and 18 were not
applied to `local_ai_core`; backend/bot process trees remained running and
were not reloaded; the memory feature flag was not enabled; no worker, Job,
OutboxEvent, candidate, canonical memory, source link, Qdrant collection, or
backfill was created in production.

### 24.9 Remaining work for Sprint 2B.5

Sprint 2B.5 may consume only `candidate` rows and add the constrained
Qwen3.5:2b proposal adapter. It must retain raw evidence, use JSON schema,
validate trusted subject/scope IDs in the backend, and leave no-op/rejected
rows terminal. Canonical apply, conflict-window scheduling, Qdrant indexing,
and retrieval remain later phases.

### 24.10 Completion decision

```text
SPRINT 2B.4 DETERMINISTIC MEMORY RULE FILTER CODE/TEST COMPLETE
```

This decision means candidate selection is deterministic and durable. Discord
memory ingestion is not complete: no extractor has run and no canonical
Discord memory has been created or indexed.

## 25. Sprint 2B.5A — Strict Extractor Adapter and Proposal Contract

### 25.1 Scope and configuration

Sprint 2B.5A adds a dry-run extractor boundary after the deterministic rule
filter. It does not install or call a real Qwen model, apply canonical memory,
create source links, or access Qdrant.

Dedicated settings are:

```text
DISCORD_MEMORY_EXTRACTOR_ENABLED=false
DISCORD_MEMORY_EXTRACTOR_MODEL=qwen3.5:2b
DISCORD_MEMORY_EXTRACTOR_SCHEMA_VERSION=v1
DISCORD_MEMORY_EXTRACTOR_NUM_CTX=4096
DISCORD_MEMORY_EXTRACTOR_TEMPERATURE=0.0
DISCORD_MEMORY_EXTRACTOR_SEED=424242
DISCORD_MEMORY_EXTRACTOR_JSON_FALLBACK=false
DISCORD_MEMORY_EXTRACTOR_TIMEOUT_SECONDS=60
DISCORD_MEMORY_EXTRACTOR_RETRY_COUNT=1
```

`DISCORD_MEMORY_INGESTION_ENABLED` and
`DISCORD_MEMORY_EXTRACTOR_ENABLED` are independent. Ingestion may durably
create and filter a candidate while the extractor remains disabled.
Temperature is validated as exactly `0.0`; context, timeout, retry count,
model, and schema version are independently bounded.

No new Alembic revision was necessary. Existing revision 18 columns and
candidate states accurately represent disabled, valid-deferred, and
rejected-invalid extractor outcomes. Test head remains `20260728_18`.

### 25.2 Strict Proposal V1

`DiscordMemoryProposalV1` is a strict Pydantic V2 contract with
`additionalProperties=false`. It contains:

```text
schema_version
operation
memory_type
subject_type
subject_id
scope
fact_key
canonical_fact
evidence_text
source_turn_id
source_discord_message_id
confidence
reason_code
target_memory_id
```

Bounded vocabularies:

```text
operation:
  create | update | delete | no_op

memory_type:
  preference | configuration | project_decision |
  identity | workflow_rule | fact

subject_type:
  member | guild | project | unknown

scope:
  member_in_guild | guild | channel | thread
```

`schema_version` must be `v1`; confidence must be a strict numeric value in
`[0,1]`, so a JSON string such as `"0.9"` is rejected. String lengths are
bounded.

Conditional validation enforces:

- `create`: no target ID and non-empty subject, fact key, canonical fact, and
  evidence;
- `update/delete`: a UUID target is mandatory;
- `no_op`: target is NULL and a reason code is mandatory.

The parser accepts exactly one bare JSON object. Markdown fences, prose plus
JSON, arrays, unknown fields, permissive coercion, malformed JSON, and invalid
operation shapes are rejected.

### 25.3 Dedicated Ollama adapter

The adapter is independent of the general/code model router:

```text
backend/app/services/discord_memory_extractor.py
```

Its primary request is:

```json
{
  "model": "qwen3.5:2b",
  "stream": false,
  "think": false,
  "format": "<Proposal V1 JSON Schema object>",
  "options": {
    "temperature": 0.0,
    "seed": 424242,
    "num_ctx": 4096
  },
  "messages": ["versioned system prompt", "trusted envelope JSON"]
}
```

Plain `format="json"` is used only when the explicit fallback flag is true
and Ollama first rejects schema-object format. There is no silent downgrade
to text mode. Timeout/transport/5xx failures receive bounded transport
retries. Invalid JSON or schema-invalid output is not transport-retried.

Logs contain model, schema/prompt version, format mode, latency, outcome, and
bounded error code only. Raw user content is not logged.

### 25.4 Trusted envelope

The worker re-reads canonical PostgreSQL rows and constructs an envelope with:

```text
exact source turn/message IDs
stable current author ID
guild/channel/thread IDs
raw current user request
filter reason and strength
trusted subject allowlist
bounded active-memory target allowlist
```

Initial trusted subject policy is deliberately narrow:

```text
label=current_author
subject_type=member
subject_id=<stable Discord author_id>
allowed_scope=member_in_guild
```

Display name is absent from identity. A third-party name typed in message
text does not become a trusted subject. Reply-target authors are not
auto-applicable subjects in this sprint.

Active target lookup is limited to at most 20 active
`member_in_guild` memories for the exact guild and stable member ID. Other
guilds, other members, other scopes, inactive versions, and unsupported
memory types are excluded. Durable filter categories narrow targets further
(for example preference → `preference`, hardware/software →
`configuration`); explicit remember/forget/correction may use the bounded
supported set because their target category is not yet known. Each target
contains only ID, fact key, canonical fact, type, scope, and version.

The adapter then fails closed if a proposal:

- changes either trusted source ID;
- selects a subject/scope outside the trusted tuple;
- selects an update/delete target outside the supplied allowlist.

This is identity/target boundary validation, not the full semantic evidence
validation planned for Sprint 2B.6.

### 25.5 Versioned prompt

Prompt version:

```text
discord_memory_extractor_prompt_v1
```

It instructs the model to return one JSON object, propose rather than commit,
use only current user evidence, never use display name as identity, never
invent IDs, never select a target outside the allowlist, avoid converting
possession/current state into durable preference, echo source IDs, and return
`no_op` when uncertain.

Tests assert these semantic requirements to detect prompt drift.

### 25.6 Worker transaction and states

The worker now uses:

```text
claim transaction
→ prepare/filter/envelope transaction
→ commit
→ Ollama HTTP/model call outside PostgreSQL transaction
→ proposal/rejection + Job-completion transaction
```

Behavior by state:

| Filter/extractor state | Worker behavior |
|---|---|
| filter `no_op` or `rejected_policy` | complete Job; never call adapter |
| candidate, extractor disabled | keep `pending/deferred`; record `extractor_disabled` |
| candidate, valid proposal | persist Proposal V1; keep `pending/deferred` |
| candidate, deterministic invalid output | persist bounded rejection; complete Job |
| transport/timeout failure | retry same Job and same candidate |

No canonical `discord_memories` or `discord_memory_sources` row is created.
Discord turn and delivery state is never changed by extractor failure.

### 25.7 Raw and normalized persistence

Filter metadata is preserved rather than overwritten:

```json
{
  "rule_filter": {"...": "Sprint 2B.4 metadata"},
  "extractor_proposal": {"...": "exact normalized Proposal V1"},
  "extractor_audit": {
    "prompt_version": "discord_memory_extractor_prompt_v1",
    "format_mode": "json_schema",
    "latency_ms": 5
  }
}
```

`raw_output` stores the parsed JSON object only. If a response is valid JSON
but fails schema/trusted-binding checks, that parsed object may be retained
for audit. Malformed/fenced/prose output is not stored as a JSONB string and
its raw body is not retained; only a bounded error code is persisted. No
chain-of-thought is requested or stored.

Proposal columns may hold the parsed dry-run proposal, but
`validation_status=pending` and `decision=deferred` explicitly prevent it
from being interpreted as approved/applied memory.

### 25.8 Idempotency and failure policy

One candidate/schema key has at most one terminal extractor result:

- a duplicate RQ delivery cannot claim a completed Job;
- an existing terminal proposal prevents a second model call;
- repeating the identical raw/normalized proposal is idempotent, even if
  latency differs;
- a different proposal conflicts and cannot overwrite the first;
- deterministic invalid output becomes terminal `rejected`, avoiding
  repeated model calls;
- transport retry preserves the candidate/filter result and retries the same
  durable Job.

Configured model, extractor schema, prompt version, filter policy version, and
display snapshot remain auditable. Display snapshot is never changed or used
as identity.

### 25.9 Tests

Strict schema/adapter/envelope tests:

```text
27 passed
0 failed
0 skipped
1 warning
```

Focused extractor, worker, repository, target-isolation, and routing tests:

```text
99 passed
0 failed
0 skipped
1 warning
```

Combined selected backend regression, including Sprint 2B.2–2B.4,
completion/delivery/reply/session, Job/Outbox/recovery, document routing,
`/memory/*`, chat, and conversations:

```text
294 passed
0 failed
0 skipped
1 warning
```

Root Discord bot/client/control regression:

```text
45 passed
0 failed
0 skipped
1 warning
```

Unique selected total:

```text
339 passed
0 failed
0 skipped
2 warnings
```

All Ollama calls were handled by `httpx.MockTransport` or injected adapter
stubs. No real Ollama, Qwen, Redis/RQ worker, or Qdrant service was called.
Warnings are the existing Starlette/httpx and Python `audioop` deprecations.

### 25.10 Production unchanged

Final production inspection was read-only:

```text
database                       local_ai_core
revision                       20260728_15
conversations                  7
messages                       80
legacy Web UI memories         0
jobs                           0
outbox_events                  0
discord_conversation_sessions 1
discord_session_turns          28
discord_turn_deliveries        2
Discord memory tables          absent
ingestion feature flag         false
extractor feature flag         false
health                         HTTP 200 / status=ok
```

No migration, backend/bot reload, worker start, Qwen pull/call, production
Job/Outbox/candidate, canonical memory, Qdrant collection, or backfill was
performed.

### 25.11 Sprint 2B.5B real-model benchmark plan

Sprint 2B.5B should be a separate non-production gate:

1. install/pin the intended Qwen3.5:2b build;
2. verify Ollama supports JSON Schema object plus `think=false`;
3. benchmark the versioned Vietnamese fixture and adversarial outputs;
4. measure schema-valid rate, trusted-binding rejection, latency, and
   transport behavior;
5. review false create/update/delete proposals;
6. keep auto-apply disabled and production flags false.

Model quality is not established by mocked adapter tests.

### 25.12 Completion decision

```text
SPRINT 2B.5A STRICT EXTRACTOR ADAPTER/CONTRACT CODE/TEST COMPLETE
```

This decision covers the strict dry-run adapter and proposal persistence only.
It does not mean Qwen quality, semantic validation, conflict handling,
canonical memory apply, or retrieval is complete.

## 26. Sprint 2B.5B — Qwen Real-Model Extractor Benchmark

Date: 2026-07-28 (Asia/Saigon).

This was a controlled, direct-adapter benchmark. It did not use the
production Job/Outbox path, did not write PostgreSQL, did not call Qdrant,
and did not enable either Discord memory feature flag.

### 26.1 Model identity and controlled pull

Preflight and the successful registry pull established the exact model
identity:

```text
Ollama version  0.32.4
tag             qwen3.5:2b
digest          324d162be6ca5629ae4517c8710434d0bd2d665bc94dbad46e9af8fbf8a2f0df
size            2,741,192,820 bytes
modified_at     2026-07-28T22:09:06.8536377+07:00
architecture    qwen35
parameters      2.3B
quantization    Q8_0
model context   262,144
```

`ollama pull qwen3.5:2b`, `ollama show qwen3.5:2b`, and `ollama list`
all succeeded. Only this requested model was pulled. This changes the local
Ollama model cache, but it is not Discord memory activation.

### 26.2 Real JSON Schema capability

The first real call used:

```text
model       qwen3.5:2b
think       false
stream      false
temperature 0.0
seed        424242
num_ctx     4096
fallback    false
```

Ollama accepted a small JSON Schema object. It rejected the complete Pydantic
Proposal V1 schema with HTTP 400:

```text
Failed to initialize samplers: failed to parse grammar
```

Isolation tests showed that Ollama 0.32.4 grammar generation rejected the
large `maxLength` constraints and conditional `allOf` clauses. The adapter
therefore sends an Ollama-compatible JSON Schema object that retains:

- a closed top-level object;
- required properties;
- JSON types and nullable unions;
- constants and bounded enums.

The full Pydantic Proposal V1 schema, length/range checks, conditional
operation checks, and trusted bindings are still applied deterministically
after generation. Plain `format="json"` fallback remained disabled and was
never used. With the compatible schema, real calls returned HTTP 200 and a
bare JSON object, proving schema-object mode itself works, while also
documenting the Ollama grammar limitation.

### 26.3 Trusted fact-key hardening

The benchmark exposed that a list of fact-key strings was insufficient for
the 2B model to choose a consistent `memory_type`. The trusted envelope now
supplies bounded pairs:

```json
{
  "fact_key": "hardware.ram",
  "memory_type": "configuration"
}
```

The backend validates the pair. It does not let the model invent a fact key
or select a mismatched memory type. The V1 registry is:

```text
user.preferred_language
user.response_style
user.display_name_preference
hardware.gpu
hardware.ram
hardware.cpu
software.python_version
project.database
project.architecture
workflow.codex_prompt_after_update
```

Trusted subjects remain limited to the current stable Discord author ID.
Display name is not sent as identity. Target memory IDs remain bounded by
the exact backend allowlist.

### 26.4 Dataset and benchmark modes

Dataset:

```text
backend/tests/fixtures/discord_memory_extractor_benchmark_v1.json
version     discord_memory_extractor_benchmark_v1
cases       150
```

It contains explicit remember/forget/correction, preferences, hardware,
software, identity, workflow, project/shared statements, transient
possession, mixed assertion/questions, negation, Vietnamese with and without
accents, typo cases, target selection, third-party/reply text, same-display
and rename wording, prompt injection, embedded JSON/code, and a source longer
than 4,096 characters.

Harness:

```text
backend/scripts/benchmark_discord_memory_extractor.py
```

Modes run:

1. one deterministic schema-mode call for all 150 cases;
2. three calls each for 30 evenly distributed/stratified cases;
3. adversarial cases within the same immutable dataset.

The harness derives stable benchmark source IDs, constructs the production
envelope, calls the dedicated adapter, and records adapter/model metrics. It
does not instantiate a database repository.

### 26.5 Prompt hardening before/after

Baseline prompt V1 on the first 20 explicit remember/hardware cases:

```text
valid JSON                 100%
schema compliance          100%
operation accuracy           0%
observed operation          no_op for all 20
mean latency             11.153 s
```

Prompt hardening added:

- explicit decision order for update/delete, create, and no-op;
- a prohibition on treating eligible explicit remember/configuration as
  no-op;
- trusted fact-key/memory-type pairs;
- mandatory non-empty `reason_code`;
- exact source-ID echo and verbatim evidence;
- explicit prompt-injection precedence;
- nullable-field rules for no-op.

Final prompt:

```text
discord_memory_extractor_prompt_v5
```

The hardening materially fixed the all-no-op baseline but did not bring the
model above acceptance thresholds on the full dataset.

### 26.6 Final real-model metrics

Final 150-case results:

| Metric | Result | Required | Decision |
|---|---:|---:|---|
| Valid JSON | 99.333% | >= 99% | pass |
| Proposal V1 schema compliance | 95.333% | >= 99% | fail |
| Additional-property violations | 0 | 0 | pass |
| Source-turn echo, all cases | 95.333% | 100% | fail |
| Source-message echo, all cases | 95.333% | 100% | fail |
| Source-ID mismatch among schema-valid proposals | 0 | 0 | pass |
| Adapter-accepted proposals | 84.667% | informational | — |
| Forged subject accepted | 0 | 0 | pass |
| Out-of-allowlist target selected | 0 | 0 | pass |
| Cross-guild target selected | 0 | 0 | pass |
| Target allowlist accuracy | 95.333% | 100% | fail |
| Operation accuracy | 73.333% | >= 90% | fail |
| Memory-type accuracy | 77.000% | >= 90% | fail |
| Scope accuracy | 93.000% | >= 95% | fail |
| Fact-key accuracy | 93.000% | reported | — |
| Exact evidence grounding | 96.000% | >= 97% | fail |
| No-op accuracy | 42.000% | reported | fail |
| Critical unsupported inference | 31 | 0 | fail |
| Repeatability, stratified 30 x 3 | 100% | >= 95% | pass |
| Timeout count | 0 | reported | pass |
| Transport error count | 0 | reported | pass |

The seven structurally invalid outputs were:

```text
extractor_schema_invalid  6
extractor_invalid_json    1
```

An additional 16 outputs selected a fact-key/memory-type pair that the
trusted envelope did not permit. The adapter rejected all 16 before any
persistence. Security boundaries therefore failed closed, but model-level
trusted-binding accuracy did not meet the required 100%.

The 31 critical unsupported inferences were concentrated in transient
hardware/software statements, untrusted shared/project subjects,
third-party/reply text, and prompt-injection cases. This is a blocking model
quality result even though none became canonical memory.

### 26.7 Latency and resource evidence

Real call latency:

```text
mean            14.378 s
p50             13.854 s
p95             16.967 s
max             93.717 s
```

Ollama performance fields:

```text
mean prompt tokens       746.32
mean output tokens       230.78
mean generation rate      20.736 tokens/s
p50 generation rate       20.727 tokens/s
p95 generation rate       21.378 tokens/s
mean load duration          211 ms
p95 load duration           230 ms
```

The long-context fixture produced the maximum latency, 1,669 output tokens,
and terminal invalid JSON after about 93.7 seconds.

Observed placement while loaded:

```text
ollama ps processor       100% CPU
ollama context            4096
llama-server working set  about 3,882 MB
host RAM                  31.1 GB total / 8.27 GB free at inspection
GPU                       NVIDIA RTX 5060 Ti, 16,311 MiB
GPU memory used           0 MiB
GPU utilization           0%
```

Therefore this exact build ran on CPU, not GPU. Ollama reported a default
idle residency of approximately four minutes after each call. No global
Ollama setting was changed; a later `ollama ps` check was empty, confirming
the model unloaded after the idle window. The primary model was not concurrently loaded,
so impact with both models resident was not measured rather than guessed.

### 26.8 Failure behavior

Controlled direct-adapter probes verified:

```text
missing model tag  -> bounded extractor_transport_error
1 ms timeout       -> bounded extractor_transport_error
invalid schema     -> terminal extractor_schema_invalid
malformed JSON     -> terminal extractor_invalid_json
```

Transport errors remain retryable at the worker layer with the same durable
Job/candidate. Deterministic invalid output is terminal and cannot create a
memory. The real benchmark did not restart the shared Ollama service because
that could affect the healthy production API; restart recovery and explicit
task cancellation remain covered by mocked/unit recovery behavior, not a
destructive real-service probe.

### 26.9 Persistence and regression

The benchmark did not use PostgreSQL persistence. Final isolated test counts:

```text
discord_memory_candidates 0
discord_memories          0
discord_memory_sources    0
test database             local_ai_core_test
test revision             20260728_18
Alembic heads             one: 20260728_18
```

Regression results:

```text
focused extractor/worker   59 passed, 0 failed, 0 skipped, 1 warning
selected backend regression 298 passed, 0 failed, 0 skipped, 1 warning
root Discord tests         27 passed, 0 failed, 0 skipped, 1 warning
unique selected total     325 passed, 0 failed, 0 skipped, 2 warnings
Python compileall          passed
git diff --check           passed (line-ending notices only)
```

Warnings are the existing Starlette/httpx and Python `audioop`
deprecations. No real Redis/RQ worker or Qdrant operation was invoked.

### 26.10 Production unchanged

Final production inspection was read-only:

```text
database                       local_ai_core
revision                       20260728_15
conversations                  7
messages                       80
legacy Web UI memories         0
jobs                           0
outbox_events                  0
discord_conversation_sessions 1
discord_session_turns          28
discord_turn_deliveries        2
Discord memory tables          absent
ingestion feature flag         false
extractor feature flag         false
health                         HTTP 200 / status=ok
PostgreSQL/Redis/Qdrant/Ollama ok
```

No production migration, backend/bot reload, memory worker start,
Job/Outbox/candidate, canonical memory, source link, Qdrant point, or turn
backfill occurred.

### 26.11 Files changed and next decision

Sprint 2B.5B changes:

- `backend/app/services/discord_memory_extractor.py`
- `backend/app/postgres/discord_memory_repositories.py`
- `backend/app/services/discord_memory_worker_service.py`
- `backend/scripts/benchmark_discord_memory_extractor.py`
- `backend/tests/fixtures/discord_memory_extractor_benchmark_v1.json`
- `backend/tests/test_discord_memory_extractor.py`
- `backend/tests/test_discord_memory_outbox_worker.py`
- this document.

There is no Alembic revision. Extractor output remains dry-run
`pending/deferred`; Sprint 2B.6 must not start auto-apply from this result.
The next safe step is a separate model/prompt selection gate, or a stronger
deterministic pre-extractor contract that reduces the model's operation and
scope choices, followed by rerunning the same dataset version.

### 26.12 Completion decision

```text
SPRINT 2B.5B BLOCKED — qwen3.5:2b failed schema, operation, memory-type,
scope, evidence-grounding, no-op, and critical-inference thresholds on the
150-case real-model benchmark
```

The model tag exists and JSON Schema object mode works, but those facts are
not sufficient for safe backend validation/auto-apply.
