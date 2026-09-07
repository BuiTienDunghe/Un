# ADR-0001: A version registry for every model role, with fallback only on load failure

Date: 07/09/2026 · Status: accepted · Owner: Bui Tien Dung

## Context

Every model the system uses — the answer model, the embedding model, OCR, the
reranker, the memory extractor and verifier, the condenser — was a bare name in
`models.yaml`, read independently by six processes. Nothing recorded which version was
serving, nothing could name the previous one, and the reranker refused to start when its
load failed, against invariant #5 (the launcher must always boot). The project is about
to change models deliberately (a fine-tuned reranker, a distilled extractor, possibly a
new embedding model), and each change must be measurable, reversible and safe to ship
while the old version keeps serving.

`docs/d4_design.md` §5 had rejected a prompt registry as "a registry nobody writes to".
That objection is the constraint here, not an argument against.

## Decision

One versioned file, `backend/app/config/model_versions.yaml`, lists the versions of every
role with provenance and eval reports, and one `active` pointer per role. Processes
resolve the pointer once at start; switching is an edit plus a restart. If the active
version fails to load or probe at startup, the resolver walks the versions listed before
it and serves the first that works, logging the deviation, writing an ATTENTION file and
exposing it in `/health` and `/models`; the eval writers and the nightly refuse to treat a
fallback as the shipped configuration. Judging a version *ineffective* stays a human
decision from per-question eval reports. The embedding role never falls back: a different
model must never write into the active collection, so each embedding version owns its own
Qdrant collections, chosen by the same pointer that chooses the query model.

The registry is written to by construction: `--check` runs in CI and fails when an active
RAG-quality version has no eval report naming it (invariant #4); every report stamps the
loaded version ids.

## Considered options

| Option | Why not |
| --- | --- |
| Hot-swap endpoint, no restart | More code, auth and concurrency for an operation that happens a few times a month; the owner chose restart-to-switch |
| Automatic demotion on eval numbers | The 82-question gate moved ±0.02 between replicates on 06/09; a rule that flips versions on that noise would flip them back and forth |
| Versioning the reranker only | The owner asked for the whole project; the embedding case is the one that needs the most care and is the one most likely to be attempted next |
| A database table for versions | Adds a DB read before Settings is validated and a migration for data that is naturally a file under review; the file is the source, `/models.registry` the runtime view (invariant #8: measure before schema) |

## Consequences

- A model change is a pull request that edits one pointer and ships the eval report that
  justifies it; a revert is the same edit backwards.
- Landing the registry changes nothing that serves: the `config:` blocks are today's
  dicts verbatim, and acceptance condition B in `.scratch/model-registry/spec.md` requires
  the same index to give the same 82 answers before and after.
- Promotion and demotion of an embedding version both require rebuilding that version's
  collections first; the startup probe catches the operator who skips it and refuses to
  serve dense retrieval rather than mixing vectors.
- The reranker chain can end in "disabled, source=fallback"; the eval gates then refuse,
  so a silent degrade cannot be graded as shipped.
