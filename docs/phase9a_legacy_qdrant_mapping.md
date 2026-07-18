# Phase 9A — read-only legacy Qdrant mapping audit

Date: 2026-07-19

## Safety result

Phase 9A made no Qdrant point mutation.  The audit CLI uses only collection
snapshot, existence/list, scroll and retrieve-style reads; it contains no
Qdrant delete, payload-update or upsert call and makes no PostgreSQL write.
SQLite was opened through a `mode=ro` URI with `PRAGMA query_only=ON`.

The PostgreSQL-only runtime guard remains in force: `DATABASE_URL` must use a
`postgresql+` dialect and `PostgresRetrievalService` deliberately ignores
index-version-only points.  Recovery references retained for this phase are:

* PostgreSQL: `data/backups/postgres-phase8b/local-ai-20260719-001749.dump`
* Qdrant: `documents-7079489509187321-2026-07-18-18-10-58.snapshot`
* SQLite authoritative evidence: `data/archives/sqlite-retired-20260719T002000Z/local_ai_core.db`

The archive checksum was verified against `manifest.json` before it was read:
`10C4BE98120F12F8C38936F542F0E7173C2E1C91E37B7C495CC513229F48335D`.
The three `pre_postgres_*` archives were explicitly rejected as non-authoritative.

## Inventory and Phase 8A comparison

| Metric | Phase 8A | Phase 9A |
| --- | ---: | ---: |
| Total points | 80 | 81 |
| Legacy (`index_version` only) | 73 | 73 |
| Versioned (`version_id`) | 7 | 8 |
| Missing document ID | n/a | 0 |
| Missing chunk index | n/a | 0 |
| Missing content hash | n/a | 75 |
| Duplicate logical legacy tuples | n/a | 0 |
| Duplicate vector groups | n/a | 5 |

The 73 legacy point IDs are identical to Phase 8A; no legacy ID was added or
removed.  The single versioned-point increase is the controlled Phase 8B smoke
document already recorded in that phase.  It is classified as versioned, never
as legacy.  Qdrant did not provide per-point creation/update metadata in the
scroll responses, so the artifact records it as null rather than inferring it.

Five byte-identical vector groups were observed.  One group contains 70 legacy
points and four groups pair a verified legacy point with its replacement.  A
duplicate vector is not treated as duplicate logical content and grants no
deletion eligibility.

## Mapping method

Each legacy point was evaluated in this order:

1. PostgreSQL document, exact version number and exact chunk index.
2. Deterministic versioned point ID, replacement payload, canonical chunk hash,
   vector dimension/fingerprint, and citation metadata.
3. The manifest-verified primary SQLite archive, including deterministic legacy
   ID, chunk hash and citation metadata.  A missing historical payload hash can
   be filled by this evidence; a present mismatching hash is a hard failure.
4. Source metadata only, without reparsing or embedding a source artifact.

For future deletion, a replacement also had to be the active PostgreSQL
version, have no active job/outbox reference, and be unreachable from runtime
retrieval through the legacy payload path.

## Classification

| Classification | Count | Eligible for future delete |
| --- | ---: | ---: |
| `VERIFIED_REPLACED` | 4 | 4 |
| `LEGACY_DOCUMENT_KNOWN` | 0 | 0 |
| `LEGACY_CHUNK_RECOVERABLE` | 0 | 0 |
| `STALE_VERSION_VERIFIED` | 0 | 0 |
| `ORPHAN_VERIFIED` | 0 | 0 |
| `UNKNOWN_DO_NOT_DELETE` | 69 | 0 |

### Deterministic deletion candidates (do not delete in Phase 9A)

| Legacy point | PostgreSQL chunk | Replacement point |
| --- | --- | --- |
| `7490dc62-2bc1-5cd7-be30-a5186419ea77` | `chunk_a8854bcba85351fe941aa9b5181bc5d1` | `a8854bcb-a853-51fe-941a-a9b5181bc5d1` |
| `c099df50-4153-551a-a3b7-ac61e68567e9` | `chunk_ef840613cdb1562ca7fdd4455c6d6e9a` | `ef840613-cdb1-562c-a7fd-d4455c6d9a` |
| `c33d7941-cf5d-5ba6-b6d3-333ce9c0de12` | `chunk_4145926d6c905b8f8d588465b57f22af` | `4145926d-6c90-5b8f-8d58-8465b57f22af` |
| `eed835f2-59be-5e04-966f-81c7df8622e8` | `chunk_fdc78878b30b5b42b0c4250b243a1107` | `fdc78878-b30b-5b42-b0c4-250b243a1107` |

All four are 1024-dimensional, have exact vector equality, canonical
PostgreSQL citation metadata, a verified primary-archive row, a deterministic
replacement ID, an active PostgreSQL version, and no active job/outbox
reference.  Their legacy payloads lack `content_hash`; this is recorded as a
payload anomaly, not a gap, because the manifest-verified archive supplies the
canonical hash.

### Recoverable and unknown points

There are no additional recoverable points.  The remaining 69 legacy IDs are
all `UNKNOWN_DO_NOT_DELETE`: they lack a matching authoritative primary archive
row and PostgreSQL document/version/chunk evidence.  The complete, machine
readable unknown list and all payload anomalies are in
`data/benchmarks/phase9a_legacy_qdrant_mapping.json`; no missing evidence was
reinterpreted as orphan evidence.

## Tests and regression

The dedicated Phase 9A audit tests cover deterministic ID separation,
read-only SQLite access, manifest mismatch rejection, `pre_postgres_*`
rejection, vector helper stability, snapshot verification failure and paged
read-only Qdrant scrolling: **8 passed**.

The targeted inventory/mapping, PostgreSQL retrieval, Qdrant and document/RAG
selection completed with **9 passed, 22 skipped** before the isolated test URL
was configured. The final isolated `local_ai_core_test` migration and full
suite completed with **150 passed, 1 skipped, 1 warning**. `docker compose
config -q` exited 0 and runtime `GET /health` returned HTTP 200 without a
SQLite component.

## Files

* `backend/scripts/audit_legacy_qdrant_phase9a.py`
* `backend/tests/test_phase9a_legacy_qdrant_audit.py`
* `data/benchmarks/phase9a_legacy_qdrant_mapping.json`
* `docs/phase9a_legacy_qdrant_mapping.md`

## Blocker and Phase 9B recommendation

Phase 9B must remain separately approved.  It may consider only the four
deterministic IDs above, after repeating the snapshot and mapping audit and
confirming retrieval parity.  The other 69 legacy points must remain untouched
until their document/chunk provenance is recovered.  Rollback is the retained
PostgreSQL backup plus the Qdrant snapshot; no SQLite archive is restored into
the runtime path.
