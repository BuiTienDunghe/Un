# Model version registry — every role, one pointer, fallback only when a load fails

Status: acceptance rule fixed 07/09/2026, before implementation; design in `design.md`
Owner: Bui Tien Dung
Decided by the owner on 07/09: scope = **the whole project** (general, condenser,
embedding, vision, ocr, reranker, extractor, verifier); switching = a versioned registry
file with one `active` pointer per role, applied at process start; automatic fallback
**only** when the active version fails to load or probe at startup — "ineffective" is a
human decision made from eval numbers, never the file's.

## Why

The next steps of this project are model changes: a fine-tuned reranker (D2), a student
extractor, and possibly a different embedding model. Today a model is a string in
`models.yaml` that six processes read independently, with no record of which version is
serving, no way to name the previous one, and one role (the reranker) that refuses to
boot when its load fails — the opposite of invariant #5. The registry makes a model
change a reversible edit of one pointer, makes "which version produced this number"
answerable from the eval reports themselves (invariant #4), and turns a broken checkpoint
into a logged, visible fallback instead of an outage.

`docs/d4_design.md` §5 rejected "a registry nobody writes to". This one is written to by
construction: `--check` runs in CI on every commit and fails when an active RAG-quality
version has no eval report naming it; every report writer stamps the loaded version ids
and refuses to write during a fallback; the nightly refuses to grade a fallback as the
shipped configuration.

## What is built

`design.md` is the contract (schema, resolver interface, startup flow per process,
failure table, cache and index safety). In one sentence per part:

- `backend/app/config/model_versions.yaml` — the registry; `models:` and
  `rag.reranker.model` leave `models.yaml`. `config:` blocks are verbatim today's flat
  dicts, so nothing that consumes `load_models()` changes.
- `backend/app/config/model_registry.py` — load, validate, resolve (pointer → probe →
  fallback chain → status), derive Qdrant collections per embedding version, CLI
  (`--check`, `--show`, `--ollama-pull-list`, `--ollama-create-list`, `--record-probe`).
- Probes that never download and are bounded by the health timeout; a reranker warmup
  that walks the chain and ends in "disabled, source=fallback" rather than raising.
- `/health.model_fallback`, `/models.registry`, an ATTENTION file, dashboard/app/Discord
  rows; `evaluate_rag`, `eval_heldout`, `run_mteb`, `nightly_eval` stamp and refuse.
- One collection pair per embedding version; deletes sweep every registered collection;
  `rebuild_qdrant --missing-only` and a new `rebuild_memories.py`.
- Launcher pulls the active **and** fallback tags; CI runs `--check`; the CI regex on
  `models.yaml` is replaced by env flags.

## Acceptance — fixed now

All of these must hold before the change is shipped.

| # | Condition | How it is checked |
| --- | --- | --- |
| A | **Nothing changes on landing.** `resolve_models().flat_models()` equals today's five `models.yaml` blocks byte-for-byte; the embedding cache identity is unchanged; collection names are unchanged (`documents`, `memories`, and the lab/test bases) | unit tests in `test_model_registry.py`, `test_postgres_embedding_cache.py` |
| B | **Same index, same answers.** The 82-question gate on the `chunkexp` stack, **without re-indexing**, gives per-question results identical to the run just before the registry landed | `compare_arms.py`: 82/82 identical (the same index evaluated twice was 82/82 identical on 06/09) |
| C | **Boot on this machine** with the shipped registry: every role's status ∈ {active, off, unconfigured}; `/health.status == "ok"` and `model_fallback == "ok"`; `/models.registry` lists eight roles | app test + one real boot of the API |
| D | **Fallback is automatic, visible, and refused by the gates.** Pointing `reranker.active` at a version whose weights are absent: the API boots; `/models.registry.reranker.loaded == "reranker-v0"`, `fallback: true`; `/health.status` stays `"ok"` and `model_fallback == "fallback"`; `data/logs/ATTENTION_model_fallback.txt` exists and names the one-step revert; the log carries `model_version_fallback`; `evaluate_rag --write-baseline` exits 1; `nightly_eval` exits 94 | `test_model_registry_app.py` + one real boot |
| E | **Refusals are loud and early.** An unknown `MODEL_VERSION_<ROLE>` refuses boot naming the variable; an invalid registry refuses boot naming file, role and id; both extractor pins set refuses boot; `--check` on the shipped file exits 0 | unit tests; `python -m app.config.model_registry --check` |
| F | **A rejected version never downloads.** Every chain entry after the first loads with `local_files_only=True`; probes call `/api/tags` and one `/api/embed` at most, never `/api/pull` | unit tests with a recording fake loader/client |
| G | **Embedding never falls back**, and a verified contradiction (width ≠ record, collection width ≠ record, collection absent while the corpus is non-empty) makes `router.embed` refuse before Ollama with a reason that names the rebuild command; "could not decide" is `unverified`, never `degraded` | table-driven `resolve()` tests |
| H | **Deletes reach every registered collection**; a failure on an existing collection raises before the Postgres row flips | `test_qdrant_sweep.py` |
| I | **Launcher and CI.** `--ollama-pull-list` on the shipped file prints exactly the tags the launcher pulled by hand before (`qwen3.5:9b`, `qwen3-embedding:0.6b`, `glm-ocr:latest`), `--ollama-create-list` prints nothing; `ci.yml` parses the registry and runs `--check`; the Ollama cache key equals the active embedding revision | unit test + reading the workflow file |
| J | **Full suite green** — the one known intermittent deadlock in `test_debt_t1_t2_t3.py` (pre-existing, filed) excepted | `cd backend && pytest -q` |
| K | **Docs.** `docs/model_registry.md` runbook (promote, demote, rebuild, revert, Docker note), `docs/adr/0001-model-version-registry.md`, README/DEVELOPMENT_PLAN flag table, `models.yaml` header, `.env.example`, CHANGELOG | present and consistent with the code |

If A or B fails, the change does not land: a registry that changes what serves on the
day it lands is a model change smuggled in without its eval. If D fails, the feature
does not exist. The rest are fixed before merge, not waived.

## Not in scope, on purpose

Hot swap without restart (the owner chose restart-to-switch); automatic demotion on eval
numbers (noise of ±0.02 was measured on 06/09; a human reads the per-question report);
a per-collection provenance table (invariant #8 — point counts and the suffix are the
evidence until a measured need appears); a consumer for `vision`; a third value for
`/health.model_fallback`.

## Result — 07/09/2026, all eleven conditions hold

| # | Result | Evidence |
| --- | --- | --- |
| A | flat_models() equals the five HEAD blocks; cache identity unchanged; collection names unchanged | `test_model_registry.py`, `test_postgres_embedding_cache.py`; S5 re-derived from `git show HEAD:backend/app/config/models.yaml` |
| B | **82/82 identical** on the same `chunkexp` index before and after landing (MRR 0.9167 both) | `scratchpad/arm_before_registry.json` vs `rag-multidoc-20260907-*` after; `compare_arms.py` |
| C | real boot on 8300: `/health.status` as before, `model_fallback: ok`; 8 roles, all active/unconfigured; extractor `source=env_tag` because this machine's `.env` still pins the tag | S5 + a second boot by hand; `--show --no-probe` |
| D | broken active reranker → boots, `loaded == reranker-v0`, `fallback: true`, `/health.status` "ok", ATTENTION file with the revert line, `model_version_fallback` logged, `--write-baseline` exit 1; file clears on the next clean boot | S5 with `MODEL_REGISTRY_PATH` fixture; `test_model_registry_app.py` |
| E | unknown pin refuses boot naming `MODEL_VERSION_RERANKER`; invalid file refuses; both pins refuse; `--check` exit 0 (4 grandfathered warnings) | S5 subprocess boots; `python -m app.config.model_registry --check` |
| F | chain entries after the first load with `local_files_only=True`; probes never call `/api/pull` | `reranker_service.py` + `test_reranker_versions.py` |
| G | 14-case probe table: width/collection/absent-with-corpus → degraded; could-not-decide → unverified; `router.embed` refuses before Ollama, and `_embed_with_cache` refuses before the cache (review finding, fixed) | `test_model_registry.py::test_embedding_probe_table`, `test_postgres_embedding_cache.py` |
| H | deletes sweep every registered collection, raise before the Postgres row flips | `test_qdrant_sweep.py` (9) |
| I | pull list = `qwen3.5:9b`, `qwen3-embedding:0.6b`, `glm-ocr:latest`; create list empty; ci.yml parses the registry, runs `--check`, regex step replaced by env flags; cache key asserted | S5; `test_model_registry_check.py` |
| J | **944 passed, 0 failed**, 1 error = the pre-existing `test_debt_t1_t2_t3` deadlock (excepted) | full suite after the final fix pass, no server running |
| K | `docs/model_registry.md`, `docs/adr/0001-…`, README, DEVELOPMENT_PLAN §3e, `models.yaml` header, `.env.example`, CHANGELOG | present; S4 reviewed |

Three adversarial reviews (invariants/CI, index safety, operator UX) found 15 points; the
majors were fixed before this result was written: the ATTENTION marker is now per log dir
so an eval stack cannot overwrite production's; the nightly strips the tag pins as well as
`MODEL_VERSION_*`; a degraded embedding refuses before the cache, not only before Ollama;
the ATTENTION revert line names the real previous version; the extractor benchmark stamps
`versions.extractor`.

Left for the operator, on purpose: this machine's `.env` still carries
`DISCORD_MEMORY_EXTRACTOR_MODEL=qwen3.5:9b`, so the extractor resolves as `env_tag` (a
documented, non-deviating state) until the line is removed by hand.
