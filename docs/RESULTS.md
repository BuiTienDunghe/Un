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
| + corrected chunker (07/09, shipped) | 1.0000 | 0.9126 | 0.9268 | `results/kept/rag-multidoc-20260907-023932.json` |

All four live under `data/evaluation/results/kept/` with their 82 per-question rows,
so a claim about individual questions is checkable. The last row is the recorded
baseline (`data/evaluation/rag_multidoc_baseline.json`) and the CI gate's reference.

**The P4-6 step, stated honestly.** Averages moved up, but not uniformly: 11
questions improved, 2 degraded, and exactly one (`br_backup_thu_cong`) went from
found to not-found. That is a real regression accepted for a large net gain, and it
is now machine-checked rather than remembered — see *Per-question gating* below.

**The chunker step, stated the same way.** The chunker was found emitting chunks that
contained the chunk before them (20.5% of production chunks, 31% over budget; see the
changelog). Fixing it moved this table's MRR from 0.9350 (control re-indexed the same
day) to 0.9126 — 0.9136 and 0.9136 on two earlier replicates — with recall@5 at 1.0000
and **`br_backup_thu_cong` found again** after P4-6 had lost it. Seven questions slipped
one or two ranks; their target chunk is byte-identical before and after, so what moved
is the reranker's ordering of near-ties once the candidate pool changed. The old
duplication was acting as free context on this five-file corpus, and this gate scores
rank-1 of the verbatim-phrase chunk. On the corpus that matters — 788 Vietnamese legal
questions over 2 945 articles, no tables — the same fix raised recall@5 from 0.9619 to
**0.9810** and Acc@1 from 0.7766 to 0.7843 with the reranker on (16 questions newly
found, 1 lost, both read), and recall@5 0.9480 → 0.9695 with it off:
`results/kept/heldout-treat-rerankerON-20260906-185648.json` against
`results/kept/heldout-rerankerON-untrained-20260906-030836.json`. Full record:
`.scratch/chunker-overlap-containment/spec.md`.

**Latency**, same corpus, after a clean restart: `/rag/search` p50 341 ms, p95 358 ms,
max 614 ms. The first `/rag/chat` after a restart costs 6.8 s (BM25 index build plus
first inference), once per restart, and is deliberately reported separately because
p95 over 82 warm questions structurally cannot see it.

**Two cautions.** The bare row above is the local run; `rag_multidoc_baseline_bare.json`
records MRR 0.7341 for the same configuration measured in CI — different machine,
different number, so compare like with like. And CI deliberately measures the bare
path (no GPU, no PyTorch extra), which is why the shipped configuration is measured
here on the operating machine instead. With the corrected chunker (07/09) the local bare path moves from recall@5 0.8537 /
MRR 0.7429 to **0.9146 / 0.7799** (control re-indexed the same day, 0 questions lost),
so the CI gate's own reference is expected to rise, not fall, on its next run.

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

## The embedding model on public benchmarks (05/09/2026)

`qwen3-embedding:0.6b`, exactly as Ollama serves it (Q8_0, 595.78M parameters,
1024 dimensions), scored with `mteb` 2.20.5 on the four retrieval tasks written in
Vietnamese by Vietnamese speakers. This measures the **embedding model alone** —
mteb encodes queries and corpus and ranks by similarity. It never touches this
project's chunker, BM25 layer, rank fusion or reranker.

| Task | Documents | nDCG@10 | recall@10 | MRR@10 |
| --- | ---: | ---: | ---: | ---: |
| TVPLRetrieval | 10 576 | 0.7936 | 0.9060 | 0.7693 |
| ZacLegalTextRetrieval | 61 425 | 0.7188 | 0.8845 | 0.6655 |
| VieQuADRetrieval | 2 490 | 0.4848 | 0.5584 | 0.6070 |
| GreenNodeTableMarkdownRetrieval | 44 678 | 0.3768 | 0.4766 | 0.3457 |
| **Mean** | | **0.5935** | | |

Evidence: `data/evaluation/mteb/vietnamese_native_summary.json`.

**Two findings worth acting on.**

*Tables retrieve badly.* 0.3768 on markdown-table retrieval against 0.7936 on legal
prose, same model, same day. This project ingests documents with tables, and its own
82-question eval contains none. Whatever the cause — the chunker splitting tables, the
embedding model, or both — it is unmeasured everywhere else and worth its own
experiment.

*On the one task with public comparisons, the model is mid-field.* `VieQuADRetrieval`
is the only Vietnamese task with results in mteb's public repository. Against those
14 models this one sits below the whole multilingual-e5 family and above the
paraphrase-multilingual family:

| Model | nDCG@10 |
| --- | ---: |
| multilingual-e5-large | 0.6112 |
| multilingual-e5-base | 0.5765 |
| multilingual-e5-small (118M) | 0.5527 |
| e5-mistral-7b-instruct (7B) | 0.5370 |
| **qwen3-embedding:0.6b — shipped here** | **0.4848** |
| paraphrase-multilingual-mpnet-base-v2 | 0.3717 |
| LaBSE | 0.2824 |

Losing to a 118M model while serving a 596M one is a result, not noise, but it is one
task. `VN-MTEB`'s own table ranks bge-m3 above the Vietnamese-specialised models while
AITeamVN's table on Zalo Legal ranks it last — the same models reorder by domain, so a
single task cannot settle a model choice. What this does establish is that swapping
the embedding model is a cheap experiment worth running before any fine-tuning, and
that a baseline now exists to judge it against.

No published Vietnamese number existed for this model before this run.

**A free improvement, measured.** Qwen3-Embedding is trained to take an instruction on
the query side. Adding one — documents untouched, so no re-indexing — moves the score:

| Task | Without | With | Δ |
| --- | ---: | ---: | ---: |
| VieQuADRetrieval | 0.4848 | 0.5315 | **+0.0467** |
| TVPLRetrieval | 0.7936 | 0.8015 | +0.0080 |

The system does not send one today. This is the cheapest change on the table: one
prefix on the query path, no re-index, no new model. Whether it survives the full
pipeline (BM25, fusion, reranker) is a separate question with its own threshold in the
roadmap, but the embedding layer clearly wants it.

*How this was nearly reported backwards.* The first attempt at this ablation returned a
delta of 0.0002 and the conclusion "instructions do nothing" was one sentence away. The
run was a no-op: the wrapper applies an instruction only when `prompt_dict` is not
`None`, and it had been left unset, so both arms measured the same configuration. Two
runs that differ by a flag are not an experiment until something confirms the flag
reached the model.

**Measurement conditions worth carrying forward.** Ollama opens a fresh connection to
its own model runner for roughly every text it embeds — measured at 1.11 sockets per
text on `/api/embed` and 1.70 on `/v1/embeddings`, against Windows' 16 384 ephemeral
ports. A 61 425-document corpus needs about 68 000 sockets over a run, so the two
large tasks fail with `bind: ... lacked sufficient buffer space` until the runner
backs off and waits for TIME_WAIT to drain. Batching does not help: the connections
are made inside Ollama. Each large task takes about 40 minutes with the back-off.

## Held-out retrieval — the first measurement this project did not author

788 questions from Zalo AI Challenge 2021 legal text retrieval (MIT licensed), with
the organisers' own relevance judgements, run through the full shipped retrieval path:
chunking, BM25 over pyvi-segmented lexemes, dense vectors, reciprocal rank fusion.
Contextual retrieval and the reranker are off for this run.

| | |
| --- | ---: |
| Accuracy@1 | 0.7602 |
| Accuracy@3 | 0.9391 |
| Recall@5 | 0.9480 |
| MRR | 0.8481 |
| nDCG@5 | 0.8733 |
| `/rag/search` p50 · p95 | 2 251 · 2 466 ms |

Evidence: `heldout_retrieval_v1/results/heldout-bare-20260904-220305.json`, 2 926
documents indexed of 2 947.

**Depth is capped at 5 and that is not a bug.** `/rag/search` clips to
`rag.max_context_chunks` so it returns exactly what `/rag/chat` would cite, regardless
of the `top_k` asked for. So no metric deeper than 5 is measurable here; the first run
recorded `recall@10` and `nDCG@10` before this was noticed, and those fields are now
null rather than a shallower number wearing a deeper label.

**Against published numbers on the same dataset** — indicative only, see the warning
below:

| System | Acc@1 | Acc@3 | Acc@5 | Corpus |
| --- | ---: | ---: | ---: | ---: |
| **This project, no reranker** | **0.7602** | **0.9391** | **0.9480** | 2 947 |
| AITeamVN Vietnamese_Reranker | 0.7944 | 0.9324 | 0.9537 | 61 425 |
| AITeamVN Vietnamese_Embedding | 0.7274 | 0.8992 | 0.9305 | 61 425 |
| bkai vietnamese-bi-encoder | 0.7109 | 0.8680 | 0.9014 | 61 425 |
| BGE-M3 | 0.5682 | 0.7728 | 0.8382 | 61 425 |

**The corpora differ by a factor of 20, so this table does not settle anything.** Fewer
distractors is an easier task, and the difference flatters the first row. It is a first
data point, not a ranking. Two further cautions: the bkai row is contaminated — its
model card says it trained on 80% of this dataset's train split — and the other rows
measure an embedding model alone while the first measures a whole pipeline.

**Latency scales with corpus size, visibly.** The same code answers in 341 ms on the
5-document lab corpus and 2 251 ms on 2 926 documents. That is the first measurement
of this system on a corpus of realistic size, and it says the p50 target of 900 ms
does not survive three thousand documents.

## Chunking: numbered clauses are not headings (04/09/2026)

The chunker read any line shaped `<number>. <text>` as a heading. Vietnamese legal
documents are written entirely as numbered clauses, so every line became a heading,
no body survived, and the document was rejected as containing no readable text while
being perfectly readable.

Measured on a 2 947-document subset of Zalo Legal 2021 (public, MIT licensed):

| | Before | After |
| --- | ---: | ---: |
| Documents producing no chunks | 960 (32.6%) | **19 (0.6%)** |
| Judged-relevant documents lost | 166 of 447 | **0** |
| Questions made unanswerable | 184 of 788 | **0** |

The change: a numbered line is a heading only when it does not end in sentence
punctuation. Ending punctuation carries the entire effect — adding a length cap
changed nothing — so this is a signal, not a threshold fitted to a number.

Three arms on the 82-question eval, shipped configuration, all built from the same
fixtures in one database:

| Arm | recall@5 | MRR | doc_hit |
| --- | ---: | ---: | ---: |
| Recorded baseline (25/08) | 0.9878 | 0.9360 | 0.9268 |
| Control — re-index, unchanged code | 0.9878 | 0.9350 | 0.9268 |
| Treatment — new chunker | 0.9878 | 0.9339 | 0.9268 |

**The control arm is the point.** Rebuilding the same corpus with unchanged code
moved MRR by −0.0010 on its own, because contextual retrieval makes one
non-deterministic generation call per chunk at index time. Treatment moves it a
further −0.0011, the same order. Measuring against the recorded baseline instead
would have charged the change with both.

Per question against the control: zero went from found to missed, and exactly one
slipped from rank 3 to rank 4 (`ca_lam_moi_sau_phase`). Four of the five eval
documents chunk byte-identically; the fifth changed because a numbered line inside
a bash code block is no longer read as a heading.

The rule was written down before the run (`.scratch/chunker-numbered-clause/spec.md`)
and all four of its conditions passed. Reports:
`results/rag-multidoc-20260904-202349.json` (control),
`…-202721.json` (treatment).

**The recorded baseline is deliberately not updated yet.** It gates the nightly eval,
which measures `local_ai_core_lab_20260821` — and that database holds documents whose
original files were lost in the 22/08 path migration, so nothing there can be
re-indexed and its chunks are frozen under the old rule. Re-recording from a
different database would make the baseline and the gate measure different corpora.
The nightly still passes and still reproduces the baseline exactly, because those
frozen chunks are unchanged. Rebuilding the lab corpus from the fixtures is the
prerequisite, and it is an operator decision.

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
