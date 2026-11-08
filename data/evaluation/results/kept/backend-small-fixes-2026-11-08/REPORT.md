# Backend small fixes — validation, 08/11/2026

The changes isolate three small maintenance tasks: an explicit unsupported-provider error for research JSON generation, shared client construction with per-process provider allowlists, and batched document/paper listing. Memory behaviour, agent prompts/loop, model versions, BM25 and thread execution are unchanged.

## Conditions

- Base: `eeb90be03f0d7a3df1c1afd4b39a2d653fc8f511`.
- Branch: `codex/backend-small-fixes`, in a separate managed worktree.
- Existing main checkout, its uncommitted changes, `.env`, running services and evaluations were left in place. The worktree and separate database isolate files and data, but CPU, RAM and disk are shared with the ongoing model evaluation.
- Python: the existing Python 3.11 virtual environment was used without installing packages; `PYTHONPATH` and cwd point to this worktree. Bytecode writes disabled.
- Unit run: `POSTGRES_TEST_URL` cleared; `DATABASE_URL` points to unused localhost port 1. Models and HTTP calls faked by the tests; startup probes disabled by conftest.
- SQL run: separate `postgres:16-alpine` container `codex-small-fixes-postgres`, a fresh `local_ai_smallfixes_test` database, random localhost port 55684; migration to head. Redis and Qdrant URLs point to unused localhost port 1. No Ollama or cloud model calls.
- No preregistration: these are regression checks, not a model-quality or latency benchmark.

## Results

| Run | Passed | Skipped | Failed |
| --- | ---: | ---: | ---: |
| Focused unit/API/provider/harness suite | 259 | 2 | 0 |
| Batched SQL reads and worker wiring | 9 | 0 | 0 |

Evidence: `unit.xml`, `postgres.xml`. The two skipped tests are existing live PostgreSQL/Qdrant rebuild integration tests; no Qdrant instance was started or reused. Two existing warnings about the research API test's short JWT test key were emitted in the unit run.

## Coverage

- Research rejects anthropic/gemini/deepseek before making an Ollama request and maps the result to HTTP 409 `RESEARCH_PROVIDER_UNSUPPORTED`. A fake-router test supplies an Ollama configuration while the environment requests a cloud version: this proves research follows the supplied router configuration rather than the environment pin. It does not exercise model resolution or prove fallback to Ollama. Existing local JSON-schema fallback and transport-error tests pass.
- The client factory preserves constructor settings, excludes unrequested providers even when their keys exist, and skips cloud clients with no key. Eval, BFCL, embedding rebuilds and memory-worker wiring retain Ollama-only client construction; the condenser retains Gemini-only construction.
- SQL tests run the real PostgreSQL query, including timestamp order, NULL handling and ID tie-breaks. Document listing preserves order, active version, latest run and no-run cases, and excludes deleted documents. SELECT count stays at three when more documents are added to the fixture.
- Paper listing preserves input order, annotation counts, page-count and no-ingestion cases while loading latest runs in one batch. Its three primary reads fetch documents, latest runs and annotation counts. If ingestion has no page count and the page-count cache is empty, `_total_pages()` can call the real document service to find the source file and issue additional database reads. The fixture uses a fake source-file service, so it does not establish a fixed total query count for every paper-listing path.

No performance gain in milliseconds or model-quality change is claimed. Real cloud generation and live rebuild integration were not tested.

## Review clarifications

- With a served cloud general model and contextual retrieval enabled, the API thread path has a cloud client and can generate chunk context through it. The RQ document worker still constructs only Ollama. Its contextualization call raises a missing-provider error, but `ChunkContextService.annotate()` catches it per chunk and continues indexing without that chunk's generated context. This discrepancy concerns index contents; it does not imply that this error alone fails the whole ingestion. This is source inspection, not a live cloud/RQ experiment.
- Before the factory change, `ModelRouter` already imported all four client modules and `AgentService` imported `ModelRouter`. Both measurement scripts use that import chain. The factory change therefore does not by itself establish newly loaded cloud dependencies or additional startup cost. The Gemini client uses HTTP directly.
- The external review reports overlap between these tests and the small-model evaluation, and places the cited harness failures before these tests began. This report does not independently audit that timeline or establish absence of resource contention. A missing per-turn timeout does not establish that latency or every other measurement was unaffected. No additional model evaluation was run to resolve that question.
- The public `unit.xml` and `postgres.xml` are normalized copies: hostname attributes are removed and local checkout paths are made repository-relative. Test names, results, counters, timestamps and durations are unchanged. Original XML files remain only in the gitignored `data/logs/backend-small-fixes-private-evidence/` directory; `metadata-normalization.json` records input/output hashes and the verification result.
- The small-model evaluation must finish before merging changes to its scripts. When reconciling `docs/SO_DO.md`, preserve entries from both checkouts in reverse chronological order. Memory behaviour and a separate local role for chunk contextualization remain outside this change.

## Reproduction

From this worktree, with its `backend` and repository root on `PYTHONPATH` and bytecode disabled:

- Unit suite: `pytest backend/tests/test_llm_factory.py backend/tests/test_research_pure.py backend/tests/test_research_api.py backend/tests/test_model_router.py backend/tests/test_anthropic_client.py backend/tests/test_agent_eval.py backend/tests/test_bfcl_run.py backend/tests/test_eval_harness_import_weight.py backend/tests/test_rebuild_scripts.py backend/tests/test_worker_extractor_model.py backend/tests/test_discord_boundary.py -q` (no database URL for integration tests).
- SQL suite: after migrating a separate database ending in `_test`, `pytest backend/tests/test_batched_document_listing.py backend/tests/test_worker_extractor_model.py -q` with `POSTGRES_TEST_URL` and `DATABASE_URL` set to that database.
