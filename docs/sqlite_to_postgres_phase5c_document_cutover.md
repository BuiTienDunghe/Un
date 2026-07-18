# Phase 5C — PostgreSQL document-runtime cutover

Date: 2026-07-18

## Scope and selector separation

The document API/runtime now uses PostgreSQL through
`DOCUMENT_DATABASE_BACKEND=postgres`.  The selectors are deliberately split:

| Concern | Selector | Cutover value |
|---|---|---|
| Auxiliary domains | `AUXILIARY_DATABASE_BACKEND` | `postgres` |
| Document API/lifecycle/indexing | `DOCUMENT_DATABASE_BACKEND` | `postgres` |
| Hybrid/BM25 retrieval | `RETRIEVAL_DATABASE_BACKEND` | `sqlite` |
| Legacy startup cleanup and embedding cache | no selector change | SQLite |

`Settings` rejects an invalid selector and rejects a PostgreSQL selector with a
missing/non-PostgreSQL `DATABASE_URL`.  There is no dual write.  The temporary
selectors remain until the final SQLite-removal phase.

## Preflight, freeze and protection

Before cutover, the auxiliary selector was already PostgreSQL while document
and retrieval selectors were SQLite.  PostgreSQL, Redis and Qdrant were
reachable; Alembic was at `20260718_09`.  The OCR and index queues were empty
before writers were stopped.  FastAPI and the OCR/index workers were stopped
for the delta migration and activation window; PostgreSQL, Redis and Qdrant
remained running.

Created protections:

* PostgreSQL backup:
  `data/backups/postgres-phase5c/local-ai-20260718-044941.dump` (non-empty).
* Production Qdrant snapshot:
  `documents-7079489509187321-2026-07-17-21-49-42.snapshot`.
* Legacy SQLite points were neither removed nor overwritten.

## Final delta and verified Qdrant mapping

The read-only document migration was run with `--apply --resume --qdrant-mode
none`, then twice with `--verify-only --qdrant-mode validate`.  Post-activation
verification uses the explicit `--allow-activated-legacy` flag.  It is
fail-closed: it only accepts a source run with `status=stage=indexed`, its
matching active target version, the target document's matching
`active_version_id`, an indexed target document, an indexed non-cancelled run,
and at least one chunk.  The default tool behavior still rejects active
versions, preserving Phase 5B's no-activation guard.

The verified legacy mappings retained the original four points and upserted
only these deterministic versioned point IDs:

| Legacy point | Versioned point | Document/version |
|---|---|---|
| `c099df50-4153-551a-a3b7-ac61e68567e9` | `ef840613-cdb1-562c-a7fd-d4455c6d6e9a` | `doc_8eea844701b041b980e8142a2793f3ee` / `ver_doc_8eea844701b041b980e8142a2793f3ee_1` |
| `c33d7941-cf5d-5ba6-b6d3-333ce9c0de12` | `4145926d-6c90-5b8f-8d58-8465b57f22af` | same document/version |
| `eed835f2-59be-5e04-966f-81c7df8622e8` | `fdc78878-b30b-5b42-b0c4-250b243a1107` | same document/version |
| `7490dc62-2bc1-5cd7-be30-a5186419ea77` | `a8854bcb-a853-51fe-941a-a9b5181bc5d1` | `doc_e002fbb8408c4d419531b15e1491e1e1` / `ver_doc_e002fbb8408c4d419531b15e1491e1e1_1` |

The final verifier reported exactly 3 documents, 2 versions, 2 runs and 4
chunks, with zero mismatches/failed records; Qdrant validation mapped exactly
the same four points.  The source-less document
`doc_b374b28332c640b28c98e2af2187bbbf` remains `uploaded`,
`source_available=false`, `content_hash=NULL` and has no active version.

## Activation

`scripts.activate_verified_legacy_documents` validated each versioned Qdrant
payload against PostgreSQL document/version/chunk/hash metadata before calling
the repository's locked legacy-activation transaction.  It activated only the
two verified indexed documents.  Each now has exactly one active version and
the corresponding document is `indexed`; the source-less document was not
eligible and was not activated.

## Runtime smoke

After changing only `DOCUMENT_DATABASE_BACKEND` to `postgres`, FastAPI,
`worker-ocr`, `worker-index`, and `outbox-dispatcher` were restarted.

* `GET /health` returned HTTP 200 with PostgreSQL, Redis, Qdrant, OCR worker,
  Index worker and Outbox Dispatcher all `ok`.
* Existing document API list/status returned the two active legacy documents
  as indexed and the source-less document with the expected unavailable-source
  metadata.
* A uniquely named tiny text document was uploaded through the API.  It was
  stored only in PostgreSQL for document metadata, queued through outbox/RQ,
  extracted, chunked, embedded, upserted to Qdrant with `version_id` and
  `chunk_id`, and activated.  Its document status is `indexed`; its run is
  `completed`, its active version is `active`, and it has one chunk.
* The smoke document is intentionally retained as a clearly identifiable
  PostgreSQL runtime record.  It was not sent to the SQLite cleanup flow,
  because cleanup remains legacy SQLite in this phase.

SQLite document counts before and after the smoke were unchanged:

| SQLite table | Count |
|---|---:|
| `documents` | 3 |
| `document_ingestion_runs` | 2 |
| `document_chunk_versions` | 4 |
| `document_chunks` | 0 |

This proves the smoke document did not write to the four SQLite document
tables.  SQLite may still change its embedding cache because that cache has
not moved in this phase.

## Tests and operational checks

* `pytest backend/tests/test_document_backend_selectors.py
  backend/tests/test_sqlite_document_migration.py -q`: **9 passed, 1 skipped**.
* Document/worker/outbox focus set: **16 passed, 2 skipped**.
* Full regression on isolated `local_ai_cutover_test` PostgreSQL database,
  with legacy selectors set for legacy tests: **120 passed, 1 skipped**.
* `docker compose config -q`: exit 0.
* `worker-ocr` smoke: exit 0; queue `local-ai:dev:ocr`, PostgreSQL/Redis/task
  import all ok.
* `worker-index` smoke: exit 0; queue `local-ai:dev:index`, PostgreSQL/Redis/task
  import all ok.

The single skipped test requires the optional Phase 5B validation-collection
environment variable; it is not a cutover failure.

## Rollback boundary and remaining SQLite consumers

Because a new smoke document has been written to PostgreSQL, automatic rollback
to SQLite is no longer safe.  Any rollback now requires stopping document
writers and an explicit reverse migration; roll-forward is preferred.

Remaining SQLite consumers are intentionally out of scope: BM25/hybrid
retrieval, `RetrievalService`, legacy cleanup and the embedding cache.  Phase 6
may begin only after a separate retrieval/BM25 migration plan is approved.

The PostgreSQL document delete endpoint now records the lifecycle request in
PostgreSQL, but physical deletion and legacy retrieval exclusion must not be
treated as migrated until the dedicated cleanup/retrieval phases.  In
particular, a Phase-5C document must not be deleted through the legacy SQLite
cleanup path.
