# OCR rollout, 09/11/2026

Target branch: `codex/tool-state-continuity`, base `59c2ad4`. No 9B/cloud route,
production database migration or production index write is part of this change.

Manifest: [v1](../../../../benchmarks/ocr_evidence/v1/manifest.json). Ten locally
generated synthetic Vietnamese images, 28 lookup questions, including explicit
missing-field questions. The first seven images were already inspected in an
earlier experiment. Three new images were frozen before this rollout run but
their results were subsequently inspected to improve column grouping. The final
replay is diagnostic, not an untouched held-out qualification.

| Run | Correct / total | Median OCR seconds |
| --- | ---: | ---: |
| [GLM + same reader](glm-lfm/report.json) | 22/28 | 0.907 |
| [Ovis structured, before grouping](ovis-lfm/report.json) | 25/28 | 1.792 |
| [Ovis + layout grouping replay](ovis-layout-lfm/report.json) | 27/28 | reused same OCR |

The model answering these questions is LFM3 1.7B. Its requests contain only
text and a bounded ID-selection schema. Typed-field prefilters abstain without
calling it when no phone/email/account evidence exists. The remaining failure
is an OCR accent error (`Liên Chiểu` -> `Liên Chiếu`), not repaired by guessing.

Scores test expected-field presence in selected evidence and refusal on missing
fields. They are not a broad OCR accuracy, entailment or handwriting metric.
Raw model responses, blocks, selections and exact failures are in each report.

[Startup probe](startup-probe.json) passed both turn completion and strict JSON
parsing on the real local model. It records Ollama's per-model residency at
ctx 16384, not peak memory for the full stack. Runtime: Ollama 0.40.13,
RTX 5060 Ti 16,311 MiB; GGUF Q8 weights + BF16 projector downloaded from the
pinned community conversion recorded in the registry.

Focused integration tests use dedicated PostgreSQL/Redis/Qdrant containers on
55439/56379/56333. They do not start or alter the production containers.
The focused JUnit file and final validation are retained alongside this report.

Final validation on the actual target worktree, 10/11/2026:

- [Full backend suite](target-full.xml): **2,217 passed**, no failures.
- The live API exposed that the registered LFM3 configuration had not disabled
  thinking, while the evaluation harness had. With a 128-token selection cap,
  that mismatch exhausted generation before the JSON selection completed.
  The LFM3 registry now explicitly sets `think: false`.
- [Final related tests](target-final-focused.xml): **128 passed**, including a
  regression that uses the real registered LFM3 configuration and checks the
  outgoing text-only request, thinking flag and selection token cap. This run
  followed the configuration fix; the full-suite run preceded that last fix.
- [Live HTTP API smoke](live-api.json): uploaded the synthetic material receipt,
  received seven validated OCR blocks, answered `VT-4068` through LFM3 with its
  source block/bbox, and abstained on the absent phone number with zero calls.
  This checks the actual FastAPI services and local Ollama, not a mocked route.
  It does not claim a browser interaction test.
- Registry validation: zero errors; the two existing embedding/reranker eval
  stamp warnings remain. JavaScript syntax and `git diff --check` passed.

The isolated API and three task-owned test containers were stopped after QA.
The downloaded OCR weights remain installed. No production process was restarted.

Implementation, sources, limitations and rollback: [runbook](../../../../../docs/ocr_pipeline.md).
