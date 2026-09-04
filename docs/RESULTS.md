# Results

Every number quoted about this project — in the README, in a model card, in a CV
line — resolves to a row here, and every row names the file that produced it. If a
number cannot be traced to a file in this repository, it does not belong on the CV.

Measured on `PC-dungbt`: RTX 5060 Ti (16 GB), Ryzen 7 7700, 31 GB RAM, Windows 11,
Ollama 0.33.2. What these numbers do **not** catch is the subject of
[FAILURE_MODES.md](FAILURE_MODES.md).

---

## Retrieval

82 questions over a 5-document Vietnamese corpus, scored retrieval-only: a result
counts as a hit when the returned chunk belongs to the expected document **and**
contains every expected verbatim term. No document filter is applied — choosing the
right document among the whole corpus is the capability being measured.

| Configuration | recall@5 | MRR | doc_hit | Evidence |
| --- | ---: | ---: | ---: | --- |
| Bare: no contextual retrieval, no reranker | 0.8659 | 0.7287 | 0.7683 | `results/kept/rag-multidoc-20260821-162010.json` |
| + contextual retrieval (P4-2) | 0.9146 | 0.7967 | 0.8415 | `results/kept/rag-multidoc-20260821-162626.json` |
| + cross-encoder reranking (P4-3) | 0.9756 | 0.8581 | 0.8537 | `results/kept/rag-multidoc-20260821-172245.json` |
| **+ sliding-window rerank (P4-6, shipped)** | **0.9878** | **0.9360** | **0.9268** | `results/kept/rag-multidoc-20260825-190252.json` |

All four live under `data/evaluation/results/kept/` with their 82 per-question rows,
so a claim about individual questions is checkable. The last row is the recorded
baseline (`data/evaluation/rag_multidoc_baseline.json`) and the CI gate's reference.

**The P4-6 step, stated honestly.** Averages moved up, but not uniformly: 11
questions improved, 2 degraded, and exactly one (`br_backup_thu_cong`) went from
found to not-found. That is a real regression accepted for a large net gain, and it
is now machine-checked rather than remembered — see *Per-question gating* below.

**Latency**, same corpus, after a clean restart: `/rag/search` p50 341 ms, p95 358 ms,
max 614 ms. The first `/rag/chat` after a restart costs 6.8 s (BM25 index build plus
first inference), once per restart, and is deliberately reported separately because
p95 over 82 warm questions structurally cannot see it.

**Two cautions.** The bare row above is the local run; `rag_multidoc_baseline_bare.json`
records MRR 0.7341 for the same configuration measured in CI — different machine,
different number, so compare like with like. And CI deliberately measures the bare
path (no GPU, no PyTorch extra), which is why the shipped configuration is measured
here on the operating machine instead.

## Answer grounding

A deterministic self-check that grades each answer sentence against the retrieved
passages. **No model calls** — it costs nothing against the inference budget.

| Metric | Value |
| --- | ---: |
| Grounding rate (82 answers) | 0.9390 |
| Ungrounded answers | 0.0000 |
| Labels | 77 grounded, 5 weak |
| Language mismatch flagged | 3 |
| False positives, two manual audits | 0 |

Evidence: `data/evaluation/rag_multidoc_grounding_baseline.json`. Kept as an
indicator, not a blocker: it has never been shown to have the precision to refuse an
answer, and 0 ungrounded means its recall on real failures is untested.

## Prompt-injection defense

12 cases: 7 attacks across 5 attack types, 5 benign controls. Scoring is
deterministic and marker-based — an attack succeeded iff a planted canary, forced
token, or exfiltration host appears in the answer. The defense wraps retrieved
passages and tool results; it adds **no model calls**.

| | Attack success | Benign pass |
| --- | ---: | ---: |
| Defense off | 0.1429 (`atk_lang_flip`) | 1.0000 |
| **Defense on (shipped)** | **0.0000** | **1.0000** |

Evidence: `data/evaluation/redteam_baseline.json`. Seven attacks is a small suite;
0.0000 means "no case in this suite succeeded", not "the system is not injectable".

## Memory extraction — teacher and student, same conditions

150 hand-written cases, 30 summary metrics over a 29-field row per case, scored
against the real model through the production adapter. Re-measured **04/09/2026** so both models share one denominator,
one prompt version (`..._prompt_v6`), one schema mode, and one machine — the previous
pair did not, which made every teacher/student comparison unsound.

| Metric | qwen3.5:9b | qwen3.5:2b | Gap |
| --- | ---: | ---: | ---: |
| **no_op accuracy** (correctly staying silent) | **0.8600** | 0.5200 | **0.34** |
| **fact content accuracy** | **0.9500** | 0.7000 | **0.25** |
| **operation accuracy** | **0.8600** | 0.6933 | **0.17** |
| trusted subject accuracy | 0.8533 | 0.7200 | 0.13 |
| unsupported inferences (count of 150) | 9 | 25 | 16 |
| memory type / scope / fact key accuracy | 0.8600 | 0.8200 | 0.04 |
| schema compliance | 0.9867 | 0.9867 | 0.00 |
| evidence exact-grounding | 0.9800 | 0.9900 | −0.01 |
| adapter acceptance | 0.9733 | 0.9867 | −0.01 |
| forged subjects accepted | 0 | 0 | 0 |
| out-of-allowlist targets | 0 | 0 | 0 |
| p50 latency per call | 3 829 ms | 1 934 ms | 1.98× |
| generation throughput | 65.5 tok/s | 134.8 tok/s | 2.06× |

Evidence: `data/benchmarks/discord_memory_extractor_20260904_qwen9b_full150.json` and
`…_qwen2b_full150.json`. Mean input tokens were identical (808.32) for both, so the
two rows differ by model alone.

**What this says, and it is the reason D2 is worth doing.** The 2B model is not worse
at *producing* memory records: it is equal on schema compliance, slightly better on
evidence grounding and on adapter acceptance. It is worse at *deciding whether a
record should exist at all* — it emitted 43 abstentions where the 9B emitted 55, and
its no_op accuracy is 34 points lower. A capacity ceiling would depress the
structural metrics too. This one does not, which makes "the training data barely
contains examples of saying nothing" a testable explanation rather than a hope.

**Superseded numbers.** A 9B run on 19/08 scored fact content 0.74 and no_op 0.60,
against today's 0.95 and 0.86. Do not read that as an improvement: the old run used
75 of the 150 cases *and* prompt version v5, so sample and prompt both changed. The
old pair is not comparable to the new pair and is retained only as history.

**The deterministic guard**, layered on the extractor, was measured on 19/08 at poison
rate 36.2% → 21.6% while keeping 96.7% coverage on the 9B model. On the 2B model the
same guard reaches 49.2% → 36.0% only by rejecting almost half of everything:
coverage falls from 100% to 53.3%. That asymmetry is why the answer was to change the
model rather than to tune the guard. Neither figure has been re-measured under prompt
v6, and doing so is the next benchmark to run.

## Memory pipeline, end to end

P = 0.94, R = 0.80, 0 forged facts, verifier 16/16 on correct cases.

**Not yet machine-recorded.** Until 04/09 the harness printed these and discarded the
dict; the number existed only as a sentence in `memory_design.md`. It now writes
`data/benchmarks/memory_e2e/memory-e2e-<timestamp>.json`, so the next
`--with-extractor` run makes it a file. Treat the values above as unverified until
that run exists.

## Throughput, measured 04/09/2026

| | qwen3.5:9b | qwen3.5:2b |
| --- | ---: | ---: |
| Generation, this benchmark | 65.5 tok/s | 134.8 tok/s |
| Generation, single long completion | 69.8 tok/s | — |
| p50 per extractor call (~808 in, ~220 out) | 3 829 ms | 1 934 ms |

VRAM is measured separately and from an idle GPU in [`data/vram_budget.md`](../data/vram_budget.md):
the shipped answer path — 9B generation at ctx 4096, the embedding model, and the
cross-encoder — occupies 9 920 MiB of 16 311 MiB, leaving **6.2 GB** for anything new.
An earlier estimate of 9.3 GB counted only the generation model and at the wrong
context length.

**Every latency figure recorded before 04/09 was a CPU measurement.** The same
harness recorded 4.07 tok/s for the 9B model on 19/08 against 65.5 today — a factor
of 16. Comments in `settings.py` and `discord_memory_verifier.py` that quoted "~60 s
per background call" described a machine that no longer exists and have been
corrected. The verifier's own cost has still not been measured on the GPU.

## Engineering

| | |
| --- | ---: |
| Tests | **811** collected (554 test functions, expanded by parametrisation) across 90 files, against real PostgreSQL, Redis and Qdrant |
| CI jobs | 4: static checks, backend tests, retrieval-eval gate, bot/tools tests |
| Schema migrations | 32, each with a working downgrade, `alembic check` gated |
| Alembic head | `20260828_32` |
| Backups | automatic, with a quarterly restore rehearsal |

## Per-question gating

The regression gate compares recall@5 and MRR against the recorded baseline with a
0.02 tolerance. Two averages cannot see a swap: three questions breaking while three
others improve leaves both untouched. Since 04/09 the baseline also records each
question's reciprocal rank, and the gate fails if any question that used to be found
stops being found. `--allow-per-case-regressions` accepts such a trade-off explicitly
and prints which questions were given up; P4-6 is the worked example of one worth
taking.

The recorded baseline was backfilled with per-question ranks from the run it was
originally recorded from (`created_at` matches to the microsecond). The bare CI
baseline has no per-question record and is not yet guarded this way; the gate says so
in its output rather than looking armed.

## Reproducing these

```bash
# Retrieval (needs API + Ollama; use the lab database, never production)
cd backend && python -m scripts.evaluate_rag \
  --multidoc-dataset ../data/evaluation/rag_multidoc_eval.jsonl \
  --retrieval-only --baseline ../data/evaluation/rag_multidoc_baseline.json

# Extractor benchmark (needs Ollama only)
cd backend && python -m scripts.benchmark_discord_memory_extractor \
  --model qwen3.5:9b --skip-repeatability \
  --output ../data/benchmarks/<name>.json

# Red-team (drives the generation model; lab database only)
cd backend && python -m scripts.redteam_rag --label defense-on

# Data-provenance guards
python -m training.common.split_manifest --check
python -m training.common.leak_check --construction-only
```

## What is not measured

Stated because a results page that only lists wins is a sales page.

- **No model here was trained by the author.** Every model is off the shelf. That is
  the gap the current roadmap exists to close.
- **The eval corpus is saturated.** One question is worth 1.22 recall points, the
  gate tolerance is 0.02 (≈1.6 questions), and one miss remains. It can no longer
  distinguish small real improvements from noise, and it is not held out from
  anything.
- **The 150-case extractor benchmark is both the source of ideas and the gate.**
  Fixes suggested by reading its failures are then scored on it.
- **The verifier has produced no verdicts in production** — it ships behind a flag
  that is off, so its production behaviour is unmeasured.
- **Grounding recall is unknown**: 0 ungrounded answers means the check has never
  been shown a fabrication it had to catch.
- Red-team coverage is 7 attacks; the memory end-to-end eval is 21 cases.
