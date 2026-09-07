# Model version registry — runbook

Date: 07/09/2026 · Decision: `docs/adr/0001-model-version-registry.md` · Acceptance rules:
`.scratch/model-registry/spec.md` · Contract: `.scratch/model-registry/design.md`

## What this is

Every model the system uses — the answer model, the embedding model, OCR, the reranker,
the Discord memory extractor and verifier, the condenser — used to be a bare name in
`models.yaml`, read by six processes independently. Nothing said which version was serving,
nothing could name the previous one, and one role (the reranker) refused to start when its
load failed. Now one file lists the versions of every role and one `active` pointer per
role. A process reads the file once when it starts, checks that the active version can
actually be served, and — if it cannot — steps back to the nearest earlier version that
can, saying so everywhere an operator looks. Changing a model is an edit of one pointer and
a restart; undoing it is the same edit backwards. Deciding that a version is *worse* is
still a person reading an eval report, never something the file does on its own.

## The file

`backend/app/config/model_versions.yaml`, checked into git, baked into the Docker image.
`models.yaml` (same directory) no longer names any model: its `models:` block and
`rag.reranker.model` are gone; what stays there is policy (`rag.*`, `agent.*`, `storage.*`),
read exactly as before.

```yaml
schema_version: 1
budget:
  vram_mib: 16311            # data/vram_budget.md — invariant #7 in bytes, lives in the data file
roles:
  <role>:                    # exactly these eight: general, condenser, embedding, vision, ocr, reranker, extractor, verifier
    active: <id> | null      # null = not served (vision); never null for general and embedding
    versions:                # OLDEST FIRST — the order is the fallback rule
      - id: <id>
        provider: ollama | gemini | deepseek | sentence-transformers
        config: {...}        # the runtime block, verbatim (every role except the reranker)
        ...
```

Rules that matter when you edit it:

| Rule | Why |
| --- | --- |
| `versions` is ordered oldest → newest. A version listed **before** the active one is a fallback; a version listed **after** it is a candidate and is never served automatically | the position *is* the fallback chain; no separate "previous" field can drift from it |
| `fallback: false` on a record removes it from the chain | for a version that must never be served by accident |
| `config:` is handed to the code as-is (`Settings.load_models()`, `/models.models`, the router, the OCR cache). Nothing is added, nothing stripped. Registry keys (`id`, `eval`, `vram_mib`, `digest`, `ollama`, `provenance`, `collection_suffix`, ...) inside `config:` are a load error | every key of the embedding `config` reaches the embedding-cache fingerprint (`postgres_document_service._cache_identity`); a stray key would invalidate the whole cache. `provider` and `revision` belong inside `config` |
| `embedding` records carry `collection_suffix` **outside** `config` (`""` for v0, `[a-z0-9_]*`, unique) | it changes *where* vectors are stored, not what they are; two versions can never share a collection |
| `query_prefix` / `passage_prefix` live **inside** the embedding `config` | a prefix change produces different vectors, so it must re-key the cache — which means a query-only prefix change is a new version with a new suffix and a full re-embed |
| `vram_mib` must be non-null on the ACTIVE version of general / embedding / reranker / extractor; `0` = shares a resident tag; `null` = "measure before promotion" | `--check` sums the resident set against `budget.vram_mib` |
| `eval.reports: {gate: path}` with gates `d1_multidoc`, `heldout`, `mteb`, `extractor_benchmark`; the ACTIVE version of those four roles needs at least one existing report whose `versions.<role>` stamp equals the id | invariant #4: a served RAG-quality version must be able to point at the report that earned it. The four v0 records are grandfathered (their reports predate the stamp: a warning, not an error) |
| reranker: exactly one of `hub` (+ `revision`) or `path` (repo-relative directory); `activation` is `identity`, `sigmoid` or null; `probe.pairs/scores/tolerance/max_ms`; `path` versions also `digest: {file, sha256}` | a checkpoint saved by sentence-transformers 5.x loads on the production 3.4.1 but defaults to Sigmoid and saturates; the loader forces the record's activation and probe-pair parity catches a mismatch or a random head |
| ollama `ollama: {source, modelfile, gguf_sha256}` with `source` `hub` (default) or `modelfile` | a tag built with `ollama create` cannot be pulled; the launcher needs to know which is which |
| ollama `digest:` (string from `GET /api/tags`) pins a mutable tag such as `glm-ocr:latest` | "loadable" then means "these bytes" |

Checkpoints exported for `path` / `modelfile` versions live under `data/models/<role>/<id>/`.
Weights are gitignored; `export.json` and `Modelfile` are tracked (`.gitignore`: `data/models/**`,
`!data/models/**/`, `!data/models/**/Modelfile`, `!data/models/**/export.json`). `export.json` is the
contract with the exporter: `{activation_fn, probe_pairs, scores, model_safetensors_sha256,
exported_with, base, base_revision, git_sha, train_data_sha256}`; the record's `activation`,
`probe.pairs/scores` and `digest.sha256` are copies of it, and `--check` requires equality.

What is deliberately **not** in the registry: `rag.reranker.enabled` / `candidate_limit` (policy,
`models.yaml`), the extractor's generation knobs (`DISCORD_MEMORY_EXTRACTOR_NUM_CTX`,
`_TEMPERATURE`, `_SEED` — Settings), a hot-swap endpoint (restart to switch), automatic
demotion on eval numbers (the 82-question gate moved ±0.02 between replicates on 06/09).

## Per-machine environment

| Variable | Meaning |
| --- | --- |
| `MODEL_VERSION_<ROLE>=<id>` (`GENERAL`, `CONDENSER`, `EMBEDDING`, `OCR`, `RERANKER`, `EXTRACTOR`, `VERIFIER`) | pin this machine to a version id listed in the file (`source: env`). **Shell only, never `.env`**: a pin left in `.env` would make every eval grade the wrong version; `nightly_eval` strips these and refuses when any role's `source != "registry"`. An unknown id refuses boot naming the variable |
| `MODEL_REGISTRY_PATH` | another registry file (tests point at a fixture); relative = from the repo root |
| `MODEL_STARTUP_PROBES=false` | skip every startup probe: each role resolves to its pointer with `verified: false`. The test suite pins it (its mocked 3-d embeds and `*_test` collections would contradict a real 1024-d probe) |
| `DISCORD_MEMORY_EXTRACTOR_MODEL=<tag>` / `DISCORD_MEMORY_VERIFIER_MODEL=<tag>` | **new meaning.** Unset = follow the registry. Set = ad-hoc per-machine pin of a raw Ollama tag (`source: env_tag`, id `env:<tag>`, no fallback, no provenance) — the D2 ship path. Setting it together with `MODEL_VERSION_EXTRACTOR` (or the verifier pair) refuses boot. The old default `qwen3.5:9b` is gone: **delete that line from the operating machine's `.env`** — left in place, every production process resolves the extractor as an ad-hoc pin (`source: env_tag`, no provenance). The nightly's lab API clears both tag pins itself (they name no version a retrieval number depends on), so the night is graded either way |
| `QDRANT_DOCUMENTS_COLLECTION` / `QDRANT_MEMORIES_COLLECTION` | still the **base** names (`documents`, `documents_lab`, `documents_test`). The served name is `base` + `_<collection_suffix>` of the embedding version the pointer names; v0 has an empty suffix, so nothing changed on landing. A base that ends with the `_<suffix>` of any registered version refuses boot (it would alias that version's collection) |
| `HF_HUB_OFFLINE=1` | every reranker load is `local_files_only` |

An empty value (`set MODEL_VERSION_X=`, `${MODEL_VERSION_X:-}` in compose) means unset.

## What happens at start

Once per process, before any request (`Settings.resolve_models()`): pointer → probe →
fallback chain → status. The I/O is bounded and single-attempt — one `GET /api/tags`, one
probe embed for the embedding pointer, one `get_collection` + one `count` per embedding
collection, one Postgres count pair (connect timeout 5 s; the Ollama calls use
`OLLAMA_HEALTH_TIMEOUT_SECONDS`, Qdrant `QDRANT_TIMEOUT_SECONDS`). Nothing ever pulls a tag or
downloads a checkpoint: a rejected version may never start a download (invariant #5).

| Status | Meaning | Deviates? | Serves? |
| --- | --- | --- | --- |
| `active` | the pointer's version probed fine | no | yes |
| `unverified` | Ollama / Qdrant / Postgres did not answer in time; pointer kept, nothing contradicted | no | yes (first use surfaces the real error, as before) |
| `off` | feature flag off (`DISCORD_MEMORY_EXTRACTOR_ENABLED=false`, `DISCORD_CONDENSATION_ENABLED=false`, `RAG_RERANKER_ENABLED=false`) or ocr `config.enabled: false` | no | no |
| `unconfigured` | `active: null` (vision) | no | no |
| `pending` | reranker, until `RerankerService.warmup()` reports back | no | — |
| `fallback` | the pointer's version failed its probe; an earlier version serves | **yes** | yes |
| `incomplete` | embedding: the collection exists, width is right, but holds fewer points than active chunks / memories rows | **yes** | yes (BM25 covers the gap in hybrid) |
| `degraded` | embedding: a **verified** contradiction — probe width ≠ `dimensions`, collection width ≠ `dimensions`, or the collection is absent while the corpus is non-empty | **yes** | no: `router.embed` refuses before Ollama with the reason (502 `MODEL_NOT_LOADED` on `/rag/*`, `/chat` memory search, `/memory/*`; index runs fail `DOCUMENT_INDEX_FAILED`) |
| `missing` | general / embedding: chain exhausted | **yes** | no (first use 502 `MODEL_NOT_LOADED`, as before) |
| `disabled` | ocr / extractor / verifier / condenser / reranker: chain exhausted; ocr is served with `enabled: false`, the memory worker runs the rule filter only, the reranker passes candidates through | **yes** | no |

Per provider: an Ollama version passes when its tag is in `/api/tags` (and its `digest`
matches when set); Gemini / DeepSeek pass when the API key is set; the embedding version
additionally gets the width and completeness checks above. **Embedding never falls back**: a
different model must never write into the active collection, and a fallback would make
`document_versions.embedding_model` lie. Keep-pointer-and-refuse is the only truthful state.

The reranker chain is walked by `RerankerService.warmup()` in the API process (the torch
load happens only there). Every entry after the first loads with `local_files_only=True`. A
version is rejected with one of `import | not_cached | load | digest | activation |
num_labels | max_length | parity`; a survivor is timed on 15 pairs, and a latency over
`probe.max_ms` is a WARNING that keeps serving (invariant #7 asks for a measured threshold,
not a refusal). All rejected → `disabled`, source `fallback` — the API boots, `/rag/*` keeps
answering without reranking, and every gate refuses. This replaces the old
`RerankerUnavailableError` at startup; the request-time contract (503 `RERANKER_UNAVAILABLE`
when a loaded model breaks later) is unchanged.

Log events (loguru `event=` field, durable sink): `model_registry_loaded`,
`model_version_config` (role, requested, source), `model_version_probe` (role, version_id,
kind, ok, detail, ms), `model_version_resolved` (role, loaded, status, verified, collections),
`model_version_fallback` (WARNING, every deviation), `qdrant_collections` (documents, memories,
suffix, base), `reranker_version_loaded`, `reranker_version_rejected` (WARNING, reason).

## Where a deviation shows

All of these read one predicate, `RoleResolution.deviates` (status ∈ {fallback, missing,
degraded, incomplete, disabled}), so they can never disagree.

| Surface | What it shows |
| --- | --- |
| `GET /health` → `model_fallback` | `"ok"` or `"fallback"`. A flat key; the top-level `status` stays `"ok"` (the control panel and the smoke test gate on it, and a fallback is a serving state to be seen, not an outage) |
| `GET /models` → `registry` | one row per role: `active` (the file's pointer), `requested` (pin or active), `loaded` (what actually serves, `null` when nothing does), `source` (`registry` / `env` / `env_tag`), `status`, `reason`, `verified`, `name`, `digest`, `fallback` (= deviates); `collections: {documents, memories}` on the embedding row, `latency_ms` on the reranker row |
| `GET /models` → `rag` | `contextual_retrieval`, `reranker`, `retrieval_mode` as this process really runs them (read after warmup, so a rejected chain reports `reranker: false`) |
| `data/logs/ATTENTION_model_fallback.txt` | written by the API after the reranker warmup when any role deviates: one line per deviating role (requested, loaded, status, reason) and the one-step revert, worded for where the pointer came from (see *Revert in one step*); **deleted** when nothing deviates, so a stale marker never outlives the state it described. `check_operational_alerts.py` folds it into the morning report (`model_fallback_alert`, exit 2 with `--fail-on-alert`). The lab launchers give their API a log dir of its own (`nightly_eval`: `LOG_DIR=data/logs/lab`; `eval_stack`: `data/logs/eval_<profile>`), so a lab boot neither erases the marker production earned nor leaves one it did not |
| dashboard (`/ui/dashboard.html`), web app, Discord `/status` | a "Phiên bản mô hình" health row (`ok` ✅ / `fallback` ⚠️) and one row per registry role, red when `fallback`. The frontend has no test harness — after a registry change, open the dashboard once and check the rows by eye |
| `python -m scripts.evaluate_rag ... --write-baseline`, `training/common/eval_heldout.py` | read `/models` once; refuse to write (exit 1) while any `fallback` is true; otherwise stamp `versions: {general, embedding, reranker}` (the loaded ids) and the `rag` flags into the report |
| `training/common/run_mteb.py --version-id <id>` | talks to Ollama directly, so it cannot see a fallback: the embedding id is declared and stamped as `versions.embedding`; `--check` then requires the summary's `model` to equal that version's `config.name` |
| `python -m scripts.benchmark_discord_memory_extractor --version-id <id>` | the only writer of the `extractor_benchmark` gate; talks to Ollama directly too, so the extractor id is declared and stamped as `versions.extractor`. `--check` refuses an unstamped report for any id but `extractor-v0` and requires `model == config.name` |
| `python -m scripts.nightly_eval` | exit **94** with an ATTENTION file when any role that is not `off`/`unconfigured` has `source != "registry"` or `fallback: true`, or the shipped `rag` flags are off. Its lab API runs with every `MODEL_VERSION_*` pin and both `DISCORD_MEMORY_*_MODEL` tag pins stripped from the env (a D2 student shipped by tag pin must not block the retrieval grade) and with `LOG_DIR=data/logs/lab` |

To see what *this* machine would serve without booting: `cd backend && python -m
app.config.model_registry --show` (add `--no-probe` for the pointer only). It prints
`{probed, model_fallback, registry}` plus `counts` (active chunks, memories rows) when the
probes ran — the same rows as `/models.registry`.

## `--check`

```bat
cd backend && ..\.venv\Scripts\python.exe -m app.config.model_registry --check [--registry PATH]
```

Static, stdlib + PyYAML only, no network — CI runs it in the `static` job on every commit,
next to the YAML parse of `model_versions.yaml`. Exit 1 lists every violation, naming
role and id; warnings are printed and do not fail.

| Rule | Error or warning |
| --- | --- |
| the file loads (schema_version 1, `budget.vram_mib`, all eight roles, `active` among the ids, no duplicate id, `config` present for every role but the reranker and absent for the reranker, no registry key inside `config`, `config.provider == provider`, suffix rules, reranker `hub` xor `path`, `hub` with `revision`, `probe.scores` length == `pairs` length, `ollama.source: modelfile` with a `modelfile`, gates ∈ the four) | error — the same errors refuse boot in every process |
| every non-null `eval.reports` path exists and is a JSON object; its `versions.<role>` equals the record id; `extractor_benchmark` / `mteb` reports name `model == config.name` | error; unstamped report on a grandfathered v0 id → warning |
| ACTIVE general / embedding / reranker / extractor: ≥ 1 existing report | error ("promotion without a gate") |
| ACTIVE version of those four roles: `vram_mib` non-null; sum of general + embedding + reranker (+ extractor when its tag differs from general's) ≤ `budget.vram_mib` | error |
| ACTIVE `path` reranker: `digest.sha256` and `probe.scores` non-null; `export.json` exists and equals the record (`activation_fn`, `scores`, `model_safetensors_sha256`) | error |
| ACTIVE `hub` reranker without `probe.scores` | warning (parity disarmed; run `--record-probe`) |
| every `ollama.source: modelfile` version that is active or in a chain: `Modelfile` exists, `gguf_sha256` non-null | error (candidates after the active one are not checked) |
| `.github/workflows/ci.yml`: the `~/.ollama` cache key equals `ollama-` + the active embedding `config.revision` | error (a stale key would serve old weights under a new revision) |

On the shipped file today: 0 errors, 4 warnings (the four v0 reports carry no stamp).

Other modes: `--ollama-pull-list` (one hub tag per line — the launcher pulls these: the
requested tag plus every fallback tag of every Ollama role that is not off; on the shipped
file exactly `qwen3.5:9b`, `qwen3-embedding:0.6b`, `glm-ocr:latest`), `--ollama-create-list`
(`tag<TAB>modelfile` for create-built tags; empty today), `--record-probe <id>` (hub reranker
versions only: score `probe.pairs` on this runtime and print the `scores:` line to paste).

## Promote a reranker, end to end

Worked for a `path` version exported from `training/reranker` (the shipped candidate record
is `reranker-d2-v1`).

1. **Export** into `data/models/reranker/<id>/` with sentence-transformers 5.x. The exporter
   writes `export.json` beside the weights: `activation_fn: identity`, `probe_pairs` copied from
   `reranker-v0`, their `scores` on the exporting runtime, `model_safetensors_sha256` of the
   file **as written** (re-saving changes bytes even with identical tensors), `base`,
   `base_revision`, `git_sha`, `train_data_sha256` (`training.common.split_manifest.digest()`).
   Weights stay out of git; `export.json` goes in.
2. **Record** it after the active one: `path`, `activation: identity`, `num_labels: 1`,
   `max_length: 512`, `digest: {file: model.safetensors, sha256: <from export.json>}`,
   `probe.pairs/scores` copied from `export.json`, `provenance`, `eval.reports` with `null`
   paths, `vram_mib: null`. `--check` passes: a candidate may carry nulls.
3. **Measure** on the lab stack, never on production and never by editing the shared file:
   `python -m training.common.eval_stack --profile chunkexp --start --model-version reranker=<id>`
   (repeatable `ROLE=ID`; it injects `MODEL_VERSION_RERANKER=<id>` into that stack's environment only;
   the stack's app log and ATTENTION marker go to `data/logs/eval_chunkexp/`, never to production's `data/logs`).
   Confirm `/models.registry.reranker` on port 8300 reads `loaded: <id>`, `status: active`,
   `source: env`, and read `latency_ms` (cap 500 ms). Run the gates:
   `python -m scripts.evaluate_rag --multidoc-dataset ... --retrieval-only --baseline ...
   --base-url http://127.0.0.1:8300` on the 82 questions,
   `training/common/eval_heldout.py` on the held-out set. Both stamp `versions.reranker: <id>`
   into their reports. Measure VRAM per `data/vram_budget.md` (idle GPU, one model at a time).
4. **Fill the record**: `eval.reports.d1_multidoc` / `heldout` → the report paths (keep
   them where CI can read them; `data/evaluation/results/kept/` is tracked), `vram_mib`,
   `provenance.promoted_at`.
5. **Move the pointer**: `roles.reranker.active: <id>`. Run `--check` — now the ACTIVE rules
   apply: digest and scores non-null, `export.json` equality, budget, a stamped report.
6. **Restart** every launcher process (`stop-local-ai-core.bat`, then `run-local-ai-core.bat`).
   Verify: `/models.registry.reranker` → `loaded: <id>`, `status: active`, `fallback: false`;
   `/health.model_fallback: "ok"`; no `data/logs/ATTENTION_model_fallback.txt`; the log carries
   `reranker_version_loaded` with `digest_ok: true`, `parity_ok: true`.
7. **Ship the number**: `evaluate_rag --write-baseline` on the shipped configuration (it now
   stamps the version ids), a CHANGELOG `### Changed` bullet in the house shape ("X đổi mặc
   định sau khi … đạt ngưỡng chốt trước khi đo: before → **after**" with the cost line), a
   `docs/RESULTS.md` row citing the kept report.

A hub version instead of a path: `hub` + `revision` (the snapshot commit), then
`--record-probe <id>` on the production runtime and paste the printed `scores:` line. Commit the
`Considered options` reasoning where it belongs — the CHANGELOG bullet, not the registry.

## Promote or demote an embedding version

One embedding version == one pair of Qdrant collections, `<base>` + `_<collection_suffix>`
(`documents_e5l` / `memories_e5l` for the shipped candidate; `documents_lab_e5l` on the lab
stack). The version that embeds the query is the version whose collections are searched —
the same pointer decides both, which is the only thing that makes a same-width swap (qwen3
1024-d ↔ e5-large 1024-d) detectable: Qdrant checks vector size only, search checks nothing.

Writes go to **one** collection. An inactive collection is therefore **frozen** at the moment
it was last built — it is not a mirror. Nothing ever deletes a collection. Deletes do sweep
every registered collection (a revoked memory or a superseded version cannot resurrect on
demotion), and a delete that fails on an existing collection raises before the Postgres row
flips, so the retry is idempotent.

**Promotion and demotion follow the same order** — demotion is not "move the pointer back",
because the old collection has missed every write since it went inactive:

1. Build (or catch up) the target's two collections, with the target pinned **in the shell**:

   ```bat
   cd backend
   set MODEL_VERSION_EMBEDDING=<target-id>
   ..\.venv\Scripts\python.exe -m scripts.rebuild_qdrant --dry-run
   ..\.venv\Scripts\python.exe -m scripts.rebuild_qdrant                 REM --missing-only when the collection already exists
   ..\.venv\Scripts\python.exe -m scripts.rebuild_memories               REM same flags
   set MODEL_VERSION_EMBEDDING=
   ```

   Both scripts resolve with `allow_missing_collections=True` (an absent target is fine; a
   width mismatch still refuses), embed with `side="passage"` from the active chunks in
   Postgres (no re-chunk, cache bypassed) and never write `document_versions.embedding_model`.
   `--missing-only` embeds only the chunks whose point id is absent and upserts without the
   delete-by-filter; without it, a collection that already holds points needs `--confirm`.
2. Read the completeness line each script prints: `points_after == active_chunks`
   (`rebuild_qdrant`) and `points_after == memories_rows` (`rebuild_memories`).
3. Move `roles.embedding.active` and restart every launcher process; Docker workers need
   an image rebuild (below). The startup probe re-checks: width, collection width, and
   `point_count >= corpus count` for both collections.

If the order is skipped, the probe says so: pointer moved without a rebuild → `degraded`
(`<id>: collection <name> does not exist while active chunks = N; run python -m
scripts.rebuild_qdrant --missing-only with MODEL_VERSION_EMBEDDING=<id>`), dense retrieval refuses;
collection behind the corpus → `incomplete` (reason names both counts and
`rebuild_qdrant --missing-only` / `rebuild_memories --missing-only`), dense keeps serving,
the ATTENTION file and the nightly refuse. The completeness check is one-directional
(legacy `index_version` points and not-yet-cleaned superseded versions can only make the
count larger): it catches a frozen collection, not a single missing chunk — `--missing-only`
is the exact comparison, on demand.

Provenance: `document_versions.embedding_model` (an existing, previously unwritten column) is
written **only** when a version is activated, with the index process's resolved embedding
version id: "the version whose vectors were produced at activation". A rebuild into a
candidate collection never stamps it. What serves now is the pointer (git history) and
`/models.registry`; per-collection point counts are the completeness evidence (invariant #8:
no provenance table until a measured need).

A version built with `ollama create` (`ollama.source: modelfile`, e.g. the e5-large GGUF):
put the `Modelfile` under `data/models/embedding/<id>/` with `FROM` naming the GGUF beside it,
fill `gguf_sha256` (required by `--check` once the version is active or a fallback), and let
the launcher build the tag from `--ollama-create-list`. `:ensure_created` never halts the
boot: a missing Modelfile prints a `[SETUP]` line and the role resolves `missing` /
`disabled` until it is built.

## Promote an extractor

The extractor's gate is `extractor_benchmark`, and its only writer is
`cd backend && python -m scripts.benchmark_discord_memory_extractor --model <tag> --version-id <id> --output <report>`
(`docs/RESULTS.md` keeps the full command). `--version-id` stamps `versions.extractor: <id>`
into the report; `--check` refuses an unstamped report for any id but `extractor-v0` and
requires `model == config.name`. Two ways to ship a student (`.scratch/d2-distillation/spec.md`):
the tag pin `DISCORD_MEMORY_EXTRACTOR_MODEL=<tag>` (per machine, `source: env_tag`, no
fallback, no provenance — the nightly strips it), or the record: `ollama: {source: modelfile,
modelfile, gguf_sha256}`, `vram_mib`, `eval.reports.extractor_benchmark: <the stamped report>`,
then `roles.extractor.active: <id>` and a restart of the memory worker.

## Revert in one step

The ATTENTION file prints the line for the case at hand:

| The deviating pointer came from | The file says |
| --- | --- |
| the registry (`source: registry`) | edit `roles.<role>.active` back to the previous id (the durable revert — it lands in git), or `set MODEL_VERSION_<ROLE>=<previous id>` in the shell of this machine only (measurement, not operation — the nightly refuses a pinned machine). "Previous" is what serves after a fallback, else the nearest version listed before the requested one without `fallback: false` |
| a `MODEL_VERSION_<ROLE>` pin (`source: env`) | unset the pin in that shell (or set it to the previous id). `active` already names the version that works: editing it changes nothing, and the pin would re-trigger the fallback on every restart |
| a `DISCORD_MEMORY_<ROLE>_MODEL` tag pin (`source: env_tag`) | unset the tag pin (`.env` or the shell); the role then follows `active`. Setting `MODEL_VERSION_<ROLE>` beside the tag pin refuses boot ("set one, not both") |
| the embedding role, `degraded` / `incomplete` | the rebuild command from the reason, pinned to the requested id: `python -m scripts.rebuild_qdrant --missing-only` / `rebuild_memories --missing-only` with `MODEL_VERSION_EMBEDDING=<requested id>` — moving the pointer is not the remedy. With a pin, or an earlier version listed, the revert line comes as well |
| a role with nothing listed before the requested version | "no earlier version of roles.<role> is registered" and the reason: fix the cause (pull the tag, set the key, export the checkpoint) |

then restart `run-local-ai-core.bat`. Three things to know before relying on it:

| Role | Revert works when |
| --- | --- |
| general / ocr / extractor / verifier / condenser | the previous tag is still on this machine (it is: the launcher pulls every chain tag) or its provider key is set |
| reranker | the previous version is in the local cache — fallbacks load with `local_files_only=True`. The hub baseline is cached on any machine that ever loaded it; on a fresh machine pre-cache it once: `cd backend && ..\.venv\Scripts\python.exe -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/mmarco-mMiniLMv2-L12-H384-v1', revision='1427fd652930e4ba29e8149678df786c240d8825')"` |
| embedding | the previous collections still exist (they do — nothing deletes them) **and** are caught up: run `rebuild_qdrant --missing-only` / `rebuild_memories --missing-only` with the previous id pinned first, exactly the demotion order above. Moving the pointer back without it yields `incomplete`, visibly |

Automatic fallback is only the startup version of the same move: the resolver walks the
versions listed before the active one and serves the first that probes. It never happens for
the embedding role, and it never happens because a number looked bad.

## Docker note

The image bakes `backend/` at build time (`Dockerfile`: `COPY backend /app/backend`); only
`./data` is mounted. A registry edit therefore reaches the compose workers (`worker-ocr`,
`worker-index`, `worker-memory`, `cleanup-worker`; `outbox-dispatcher` and `discord-bot` share the
image but never read the registry) only after `docker compose build`. The
launcher's host workers (backup, cleanup, outbox dispatcher, memory worker, condenser) read the
checkout and pick the edit up on restart. `docker-compose.yml` passes `MODEL_VERSION_EXTRACTOR`,
`MODEL_VERSION_VERIFIER`, `MODEL_VERSION_EMBEDDING` and `DISCORD_MEMORY_EXTRACTOR_MODEL` through
with empty defaults (empty = unset); no `*_MODEL` line in compose carries a model name any more
(`backend/tests/test_compose_defaults.py`).

## Landing guarantees, for the record

The registry must land as a no-op. Condition A of the spec is locked by unit tests
(`backend/tests/test_model_registry.py`, `test_postgres_embedding_cache.py`):
`resolve_models().flat_models()` equals the five former `models.yaml` blocks byte-for-byte, the
embedding cache fingerprint is unchanged, the collection names are unchanged (`documents`,
`memories`, the lab/test bases). Condition B — the same index gives the same 82 per-question
results, without re-indexing — is a measurement on the `chunkexp` stack (the `per_case` ranks
of two `evaluate_rag` result files compared question by question: 82/82 identical) taken
before merge; its evidence path belongs in `.scratch/model-registry/spec.md` §Result, and a
miss means the change does not land. A registry that changed what serves on the day it landed
would be a model change smuggled in without its eval.
