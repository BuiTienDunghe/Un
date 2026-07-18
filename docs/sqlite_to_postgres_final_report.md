# SQLite → PostgreSQL final stabilization report

Date: 2026-07-19

## Executive status

The runtime baseline is PostgreSQL-only. PostgreSQL is the sole source of truth
for document lifecycle, canonical chunks/citations, jobs, outbox, conversations,
memory and operational records. Qdrant is a versioned vector index only; Redis
transports worker jobs only. SQLite is retired from runtime and retained solely
as a controlled, checksum-verified archive.

This report closes migration stabilization through Phase 9A. It does **not**
authorize Phase 9B. No legacy Qdrant point, PostgreSQL backup, Qdrant snapshot,
or SQLite archive was deleted or altered by this stabilization.

## Architecture before and after

| Concern | Before migration | PostgreSQL-only baseline |
| --- | --- | --- |
| Canonical data | SQLite runtime database | PostgreSQL + Alembic |
| Ingestion execution | FastAPI thread | Redis/RQ OCR and index workers, durable PostgreSQL jobs/outbox |
| Document/version model | integer SQLite index version | PostgreSQL `document_versions`, pages and canonical chunks |
| Retrieval | legacy Qdrant point + SQLite chunk lookup | versioned Qdrant candidate + active PostgreSQL chunk validation |
| Cleanup | legacy SQLite path | PostgreSQL lifecycle planner/executor; no legacy-Qdrant domain |
| SQLite | runtime dependency | explicit archive/migration evidence only |

A Qdrant candidate is eligible for runtime retrieval only when it contains both
`version_id` and `chunk_id`. `PostgresRetrievalService` verifies the candidate
against the active PostgreSQL version before returning content or citations.
Points carrying only `index_version` are ignored by retrieval and are not a
cleanup input.

## Completed migration phases

| Phase | Outcome |
| --- | --- |
| 0–1 | Inventory, PostgreSQL foundation, Alembic and backup/migration tooling established. |
| 2–3 | PostgreSQL document/version model and durable Redis/RQ worker execution introduced. |
| 4–5 | Transactional outbox, auxiliary domains, document migration and activation controls completed. |
| 6–7 | PostgreSQL retrieval cutover, embedding-cache cutover and lifecycle cleanup controls completed. |
| 8A | SQLite runtime compatibility code/selectors removed; ordinary runtime/tests became PostgreSQL-only. |
| 8B | SQLite runtime files archived, PostgreSQL restore drill passed, runtime smoke passed. |
| 9A | Read-only legacy Qdrant mapping and deterministic future-deletion evidence produced. |

## Schema and migrated data

Alembic head is `20260718_09`. The Phase 8B restore drill placed both the runtime
database and isolated restored database at that revision.

The verified Phase 8B canonical summary was identical in runtime and restored
database: 15 documents, 15 document versions, 15 ingestion runs, 9 document
chunks, 30 conversations, 60 messages, 18 OCR runs, 156 request logs, 1 job and
28 outbox events. The restored database returned 6 active versions and 30
readable conversations.

## Recovery artifacts and retention

| Artifact | Location / identity | Policy |
| --- | --- | --- |
| PostgreSQL recovery dump | `data/backups/postgres-phase8b/local-ai-20260719-001749.dump` (53,342 bytes) | Retain; restore only into an isolated validation database first. |
| SQLite primary archive | `data/archives/sqlite-retired-20260719T002000Z/local_ai_core.db` | Read-only audit/migration evidence; never runtime. |
| SQLite archive checksum | `10C4BE98120F12F8C38936F542F0E7173C2E1C91E37B7C495CC513229F48335D` | Verified against `manifest.json`; earliest permanent-deletion review is 2027-07-19. |
| Qdrant snapshot | `documents-7079489509187321-2026-07-18-18-10-58.snapshot` | Retain as Phase 9A recovery checkpoint. |

The archive also retains three `pre_postgres_*` snapshots as never-merge
historical evidence. They are not authoritative mapping sources and are never
copied to `data/sqlite/` for runtime use.

## Qdrant final inventory

The Phase 9A read-only inventory contains 81 points:

| Category | Count | Runtime / cleanup treatment |
| --- | ---: | --- |
| Legacy, `index_version` only | 73 | Not queried by retrieval; excluded from cleanup. |
| `VERIFIED_REPLACED` legacy subset | 4 | Deterministic replacement exists; retained pending separately approved policy. |
| `UNKNOWN_DO_NOT_DELETE` legacy subset | 69 | Retain indefinitely; insufficient provenance for any deletion action. |
| Versioned points | 8 | Runtime candidates only when PostgreSQL active-version validation succeeds. |

The 4 verified mappings are future-deletion candidates only; they were not
deleted in this stabilization. The Phase 8B controlled smoke explains the
increase from 7 to 8 versioned points. The full mapping/evidence is in
`data/benchmarks/phase9a_legacy_qdrant_mapping.json`.

## Why Phase 9B was not run

Phase 9B would be a destructive policy phase. It remains out of scope because
69 legacy points lack authoritative document/version/chunk provenance. Missing
evidence is not evidence of orphanhood. A future Phase 9B requires a separate
approval, a fresh verified snapshot/inventory, a deterministic deletion list
containing no unknown point, retrieval-parity confirmation and a reviewed
rollback procedure.

## Runtime components

- FastAPI API and health endpoint
- PostgreSQL / SQLAlchemy / Alembic
- Redis/RQ OCR and index workers
- PostgreSQL job, outbox and cleanup services
- Qdrant versioned vector index
- Ollama embedding/LLM and OCR integration

`GET /health` has no SQLite component. Runtime composition fails fast without a
PostgreSQL `DATABASE_URL` or if given a SQLite URL.

## Recovery procedure

1. Preserve the PostgreSQL dump, Qdrant snapshot and SQLite archive.
2. Restore the PostgreSQL dump into a new validation database, never directly
   over the runtime database.
3. Run `alembic upgrade head`, compare revision and canonical summaries, then
   validate repository reads.
4. Reconcile Qdrant only through an approved, versioned PostgreSQL recovery
   procedure; retain legacy points untouched.
5. If SQLite evidence is needed, verify the manifest checksum and pass the
   archive path explicitly to a read-only audit/migration CLI.

## Known limitations

- 69 legacy Qdrant points remain intentionally unresolved and cannot be safely
  deleted.
- Qdrant is not a content source; availability still affects dense retrieval.
- Qdrant did not expose point creation/update metadata in the Phase 9A scroll
  response.
- The existing controlled Phase 8B smoke document accounts for one additional
  versioned point; no new smoke document is required for stabilization.

## Next development recommendations

1. Keep Phase 9B blocked until a separate provenance/deletion policy is
   approved for the 69 unknown points.
2. Continue regular PostgreSQL backup/isolated-restore drills and Qdrant
   snapshot verification.
3. Add monitoring/alerting for missing active-version Qdrant candidates and
   outbox/worker liveness.
4. Review source, OCR-run and request-log retention periodically using the
   PostgreSQL cleanup policy; never fold legacy Qdrant points into that policy.

## Stabilization validation

| Check | Result |
| --- | --- |
| Focused PostgreSQL-only / cleanup / Phase 9A tests | 10 passed, 7 skipped, 1 warning (without test URL); with the isolated URL, full suite passed below. |
| Full `pytest backend/tests -q` with `POSTGRES_TEST_URL=local_ai_core_test` | 150 passed, 1 skipped, 1 warning. |
| Alembic clean database | `local_ai_final_stabilization_test` created, upgraded to `20260718_09 (head)`, then dropped. |
| Docker Compose | `docker compose config -q` exited 0. |
| FastAPI health | HTTP 200; response has no SQLite component. |
| OCR and index worker probes | PostgreSQL, Redis and task import all `ok`. |
| Cleanup dry-run | 1 PostgreSQL candidate, blocked by grace period; 0 eligible, no legacy-Qdrant candidate/domain. |
| Outbox dispatcher smoke | Completed one pass; published 0 events. |
| RAG retrieval smoke | Existing indexed document returned 1 verified candidate with both `version_id` and `chunk_id`; `touch_documents=False`. |
| Qdrant post-check | 81 total, 73 legacy and 8 versioned; exact legacy ID set unchanged from Phase 9A. |

No additional document upload/index smoke was run. Indexing would create or
upsert Qdrant data, which is prohibited by this stabilization boundary. The
successful Phase 8B controlled upload/index smoke remains the applicable
evidence; no fixture or smoke document was added in this phase.

The SQLite reference scan found no SQLite runtime reference in `backend/app/`.
Remaining `sqlite3` usage is confined to explicit migration/audit CLIs and
their migration/audit-specific tests; historical migration documents retain
historical references. `data/sqlite/` contains only its redirect README and no
runtime `.db` file.
