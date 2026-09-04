# Failure modes

Four incidents from this repository, written up in the shape Hamel Husain uses for
error analysis: what broke, how it stayed hidden, what actually found it, what the
fix was, and what would catch it now.

The reason to write them down is narrow. Every one of these survived a system that
already had tests, a CI gate, and a recorded retrieval eval. None of them was a case
of nobody measuring. Three of the four were invisible *because* the measurements
that existed were the wrong shape — an average that cannot see a permutation, a
version pin that pins nothing, a confidence score that is decoration. The fourth was
a gate that went red for eight days for a reason it does not watch, and the error
message could not tell a powered-down machine from a real regression.

So this document is about the limits of measurement, not the absence of it. Where a
fix cost something, the cost is stated. One of these incidents shipped with a
pre-registered acceptance rule knowingly violated; that is written down here in the
same words the commit used.

---

## 1. The reranker judged two thirds of the corpus on a truncated prefix

**P4-6 · lived 4 days · 21–25 August 2026 · commit `aba731c`**

### What broke

Cross-encoder reranking was turned on by default on 21 August (`affa70a`). The model
is `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, whose input window is 512 subword
tokens, and `CrossEncoder(model_name)` was constructed without `max_length` — so
every passage longer than 512 subwords was silently truncated before scoring.

The worked example is chunk 2 of `p3_progress.md`: 778 subword tokens, with all four
answer phrases sitting at tokens **583–743**, entirely behind the cut. The reranker
scored the first 512 tokens — which are about something else — and concluded that
chunk 3 (531 tokens) and chunk 4 (385 tokens), both of which fit nearly whole, were
more relevant.

This was never about two questions. The width of the defect, measured on both
corpora (`docs/p4_progress.md:568-569`):

| Corpus | chunks over 512 subwords | median | longest |
| --- | --- | --- | --- |
| Lab (27 chunks) | 10 = 37% | 471 | 778 (1.5×) |
| Production (190 chunks) | **123 = 65%** | 536 | 1494 (2.9×) |

The root cause under the root cause is a units mismatch. `models.yaml` sets
`rag.chunk_tokens: 480`, counted by the chunker's **regex word counter**
(`chunking.count_tokens`). The cross-encoder counts **subwords**. Vietnamese expands
about 1.6× between those two rulers. Two components used the word "token" with
different instruments, and the bias ran systematically against every long chunk.

### How it hid

Nothing external changed. Latency stayed inside budget, `/rag/chat` kept returning
sources, and `message_sources` still recorded retrieved chunks for every answer — so
there was no symptom to notice.

Two of the eval questions (`p3_khoa_brute_force`, `p3_refresh_khong_xoay`) had been
failing since 21 August, and were logged at the time as "headroom for exact-match
retrieval" — a wrong diagnosis that was plausible enough to close the question.

The transformers tokenizer *did* print the finding, on every call, for four days:

```
Token indices sequence length is longer than the specified maximum sequence
length for this model (778 > 512).
```

That line went nowhere. `logging_service.py` configured loguru and nothing else — no
`InterceptHandler`, no `logging.captureWarnings`. As of 25 August the file sink held
8 daily log files covering its 30-day retention, and a search of all of them returns
**zero** matching lines. The warning existed and was discarded.

### What found it

A human measuring the retrieval stages separately, using the chunk viewer shipped the
previous day. Isolating each stage on the two failing questions eliminated four
hypotheses by number (`docs/p4_progress.md:548-553`):

| Stage | verdict on the chunk that contains the answer |
| --- | --- |
| Chunking | all four phrases intact in one chunk — correct |
| BM25 | rank 1 on both questions (11.55 vs 9.98 · 21.95 vs 11.41) |
| Dense (Qdrant) | rank 2 and 3 |
| RRF (k=60) | rank 1 and 2 — fusion correct |
| Cross-encoder rerank | **out of the top 5 on both** |

### The fix

A sliding window at the rerank layer (`backend/app/services/reranker_service.py`,
`window_stride_ratio` parameter, default 0.5). A passage longer than the model's
window is cut into overlapping windows, each scored, and the candidate keeps its
**best** window's score. No change to chunking, no re-index, no schema change. Short
passages — the common case — take exactly the path they took before.

Two earlier attempts failed, and both were caught only by looking at per-chunk
scores, never by the aggregate:

- A flat 64-token safety margin looked prudent and cut through another question's
  answer: 448 tokens scored **−0.710** where the model's own 512-token truncation
  scored **1.405**. The window is therefore derived from the model's real limit minus
  the actual question length, never a constant (`reranker_service.py:93-120`).
- Slicing by decoding token ids back to text collapsed newlines — a markdown
  passage's blank line came back as a single space — and moved one score from 1.405
  to **−0.008**, a worse bug than the truncation. Windows are sliced out of the
  original string through the fast tokenizer's offset mapping instead
  (`reranker_service.py:123-158`).

Measured on the lab corpus with a same-day control run that reproduced the old
baseline to every digit:

| Metric | Before | After | Pre-registered condition |
| --- | --- | --- | --- |
| recall@5 | 0.9756 | **0.9878** | ≥ 0.9756 ✅ |
| MRR | 0.8581 | **0.9360** | ≥ 0.8581 ✅ |
| doc_hit | 0.8537 | **0.9268** | ≥ 0.8537 ✅ |
| p50 / p95 `/rag/search` | 305 / 325 ms | 343 / 366 ms | ≤ 900 / 1200 ms ✅ |

### The trade-off, stated plainly

Over all 82 eval questions the ledger is **11 up, 2 down**. Comparing the two archived
21 August reports (rerank OFF vs ON) shows the reranker had been demoting the correct
chunk on **eight** questions, not two. Six of those eight recovered:

| Question | Before | After |
| --- | --- | --- |
| p3_khoa_brute_force | MISS | **1** |
| p3_refresh_khong_xoay | MISS | **1** |
| p3_require_admin_db | 4 | **1** |
| xd_kiem_tra_quyen_admin_doc_db | 3 | **1** |
| vi_version_failed_retry | 2 | **1** |
| p3_bootstrap_advisory | 2 | **1** |
| p3_migration_chot_phase | 2 | 2 |
| **br_backup_thu_cong** | **5** | **MISS** |

One question that used to be found stopped being found. That violates acceptance
condition 3, pre-registered that same morning — "no question that is currently a hit
becomes a miss" — and the patch was shipped anyway. The mechanism is understood:
max-over-windows is monotonically non-decreasing, so it can only lift long passages;
a short, correct passage with a modest score (0.333) gets overtaken. That is an
inherent bias of the method, not an implementation bug.

The stated reasons for accepting: the sacrificed question was already a casualty of
this same defect (fusion ranked it 1, the reranker pushed it to 5 back on 21 August);
the trade is two questions for one; and the defect being fixed touches 65% of the
production corpus, far wider than 82 eval questions can sample.

The progress log records this in its own words as *loosening a threshold after seeing
the numbers — exactly what the P4-4b lesson forbids* — so it cannot become a silent
precedent (`docs/p4_progress.md:638-640`). It is the one place in this repository
where a pre-registered gate was overridden.

### What now catches it

- **`_InterceptHandler` in `logging_service.py:42-131`** (commit `8c043d9`,
  26 August) routes the standard library's logging into loguru's file sink at
  WARNING and above. The comment there names its own price: "Ten lines is what that
  record cost." It is verifiable that it works — the same warning now lands in the
  file: 4 lines in `data/logs/app_2026-08-26.log`, 2 in `app_2026-08-27.log`, tagged
  `logger_name: transformers.tokenization_utils_base`.
  The non-obvious part is that `basicConfig` + `captureWarnings` alone — the recipe
  every guide gives — produces **zero** lines, because transformers sets
  `propagate=False` and installs its own handler. Naming the libraries explicitly is
  the whole mechanism, not belt-and-braces.
- **The nightly eval** (`backend/scripts/nightly_eval.py`) runs the *shipped*
  configuration against the lab corpus. CI deliberately pins `reranker` and
  `contextual_retrieval` to false (`.github/workflows/ci.yml:272-291`) so it measures
  the bare path — which is precisely the blind spot this bug lived in.
- **A per-case gate** in `backend/scripts/evaluate_rag.py:304-326`, added 4 September,
  fails the run when any question goes from found to missed. The baseline now records
  every question's reciprocal rank. The comment cites P4-6 as the worked example, and
  `--allow-per-case-regressions` exists so that accepting such a trade is possible but
  never silent.

---

## 2. The word segmenter was a floating dependency of every BM25 lexeme

**T16 · 25 August 2026 · commits `9cee341`, then `a268526` three hours later**

### What broke

Nothing yet — this is a hazard found by inspection, not an outage, and it is here
because the *first fix for it was measured and found to be worth almost nothing*.

`pyvi` was declared as a version range (`>=0.1.1,<1.0`). But pyvi's output **is** the
BM25 lexeme set: `tokenize_vietnamese` returns segmented terms like `học_sinh`
(`backend/app/utils/vi_tokenizer.py`). A different pyvi release resegments every
chunk in the corpus, moves retrieval ranking, and leaves the recorded eval baseline
describing a stack that no longer exists — with no signal anywhere. Today that is
runtime-only drift, because the sparse index rebuilds from PostgreSQL at startup. The
moment a lexeme is persisted (P4-4b), the same drift becomes permanently dirty data.

### How it hid

There is no observable at all. Retrieval would still answer, the eval would still
produce numbers, and the numbers would simply describe a different tokenizer than the
baseline they were compared against. The gate would compare them anyway.

### What found it

A debt sweep, not an alarm — and then, crucially, a measurement of the fix itself.
`a268526` asked what the pin was worth and the honest answer was: nothing.

pyvi 0.1.1 is the **newest** release on PyPI, uploaded 2021-06-30 — 1,882 days before
the pin was written — and it is the only version satisfying the old range. The range
and the exact pin have resolved to the identical artifact every day since 2021.
`pip install -U pyvi` is a no-op.

Meanwhile the thing that *can* move was never pinned. Segmentation is decided by two
data files loaded at import — `models/words.txt` (354,580 B, 22,705 bigrams + 1,907
trigrams) and `models/pyvi3.pkl` (789,337 B of CRF weights) — plus a C decoder whose
packages (`python-crfsuite`, `sklearn-crfsuite`, `scikit-learn`, `numpy`) appear
nowhere in `requirements.txt`, with no hashes and no lockfile.

The one-sentence canary added by the first commit was measured too. An adversarial
sweep of every dictionary bigram occurring in the 190-chunk production corpus found
**468** whose removal resegments it; the canary notices **3** of those 468 — 0.6% —
and those three are exactly the words hard-coded in its own assertion. A realistic
edit (adding eight domain compounds a Vietnamese RAG project would plausibly add)
resegments **169 of 190** chunks and moves **3.11%** of token positions with every
existing guard green.

### The fix

Three layers, and only the third is load-bearing:

1. `requirements.txt:17-22` pins `pyvi==0.1.1` exactly, with a comment saying out loud
   that bumping the line is a *retrieval change* requiring a re-recorded baseline.
2. `TOKENIZER_VERSION` is read back from the installed distribution, never hard-coded
   — a version constant that can disagree with reality is worse than no constant — and
   travels with everything derived from it: the `bm25_rebuilt` log line, `/models`, and
   the baseline JSON (`tokenizer_version: "pyvi-0.1.1"`).
3. The **segmentation contract itself** is hashed: `test_vi_tokenizer.py:73-107`
   sha256s `words.txt` and `pyvi3.pkl`. That covers the whole
   dictionary-and-weights half of the contract instead of 0.6% of it, and costs one
   hash per test run.

### What now catches it

- `test_pyvi_is_pinned_exactly_and_the_pin_matches_the_installed_version` reads
  `requirements.txt` and demands exactly one `pyvi==<installed version>` line —
  catching both a range creeping back and a pin edited without reinstalling.
- `test_the_segmenter_model_files_are_the_ones_the_baseline_was_measured_with`
  compares both sha256 digests.
- `evaluate_rag.py:286-295` refuses to compare against a baseline recorded with a
  different `tokenizer_version`, the same way it already refuses across an embedding
  model change; and `evaluate_rag.py:261-262` refuses to *record* a baseline when the
  server does not report one, since a `null` stamp would pass the check forever.

**Still open, and named as such:** the decoder packages are unpinned and do still
release (`python-crfsuite` 0.9.12, December 2025). Their recent changes are
packaging-only, so this is a live path rather than an urgent one.

---

## 3. The extractor was confident and wrong at the same time

**P2-1b · benchmark of 19 August 2026 · 150 cases**

### What broke

The Discord memory extractor proposes facts to write into a member's memory, each
carrying a `confidence` field, and auto-apply was gated on `confidence >= 0.8`. The
19 August benchmark showed the gate was decorative: **every severely wrong proposal**
from both models — 72 of 72 on `qwen3.5:2b`, 17 of 17 on `qwen3.5:9b` — declared
`confidence = 1.0` (`docs/p2_progress.md:82-83`).

Reading the stored raw outputs directly confirms the mechanism: across the 150-case
2b run, `confidence` takes only the values `{0.0, 0.9, 1.0}`, and every `0.0` is a
`no_op` row where no proposal was made. On the 75-case 9b run it takes
`{0.0, 0.9, 0.99, 1.0}`. There is no threshold in `(0, 1]` that separates right
proposals from wrong ones, because essentially every proposal declares the maximum.

### How it hid

The threshold *looked* like a safety mechanism, and every downstream document treated
it as one. Nothing about a confidence value can be falsified by a passing test — it is
a number the model writes about itself, and it was never checked against outcomes.

The first crack was a live incident, not a metric: a message asking for "answers with
worked examples" was extracted by 2b as *"User dung-live prefers Vietnamese"*, with
confidence 1.0, auto-applied, and caught only because a human saw it on the review
dashboard (`docs/p2_progress.md:47-52`).

### What found it

A dedicated benchmark run — the first time the 150-case dataset was measured for real
(`backend/scripts/benchmark_discord_memory_extractor.py`, prompt v5, JSON-schema
mode). Raw results in `data/benchmarks/discord_memory_extractor_20260819_*.json`. Each
run writes a 31-field summary, so the confidence axis was one measurement among many
rather than the only thing being asked about:

| Metric | `qwen3.5:2b` (150 cases) | `qwen3.5:9b` (75-case stratified subset) |
| --- | --- | --- |
| Valid JSON / schema-compliant | 99.3% / 96.7% | 100% / 92% |
| Stayed silent when it should (`no_op`) | 44% | 60% |
| Fact content correct | 66% | 74% |
| Mean latency / throughput | 12.2 s · 23.4 tok/s | 59.2 s · 4.1 tok/s |
| Byte-identical repeat (temp 0 + seed) | 100% | not measured |
| Forged subject / out-of-allowlist target | 0 / 0 | 0 / 0 |

The 100% repeatability is its own finding: self-consistency voting cannot help,
because the model returns the identical wrong answer every time.

### The fix

Drop confidence as a signal entirely and replace it with a deterministic,
evidence-based guard: the proposal's `evidence_text` must be a verbatim quote of the
source message, and the fact's content words must actually appear in that message
(`backend/app/services/discord_memory_guard.py`). `τ` survives only as a policy
switch (`off` = review everything), and the docs say so explicitly.

Simulated over the same 75 cases (`docs/p2_progress.md:89-92`):

| Policy | 2b: coverage · poison | 9b: coverage · poison |
| --- | --- | --- |
| A — `conf >= 0.8` only (the old gate) | 100% · **49.2%** | 100% · **36.2%** |
| C — A + verbatim evidence + fact/source content-word overlap | 53.3% · 36.0% | **96.7% · 21.6%** |

The guard is near-free on 9b, because 9b's facts genuinely reflect the source message.
On 2b it cuts coverage roughly in half and still lets more than a third of the poison
through — which is why the recommendation was to change the model, not tune the
harness.

Two further deterministic rules landed on 27 August (`a8955b7`), both measured
**zero-cost** on the same benchmark (coverage 96.7% and poison 21.6% unchanged to the
digit) while closing two measured holes: a negation-clause rule (the guard used to
*accept* a fact contradicting its source, because "Dũng dùng Postgres" reduces to
`{postgres}` and the substring hits), and a minimum-two-content-words rule.

### The honest accounting

- **21.6% poison remains.** No model here is safe enough to run blind. The written
  conclusion is that the human review-and-revoke loop is not a stopgap but the correct
  architecture: supervised autonomy (`docs/p2_progress.md:107-109`).
- **9b's cost:** 11 real facts missed (more cautious, plus 6 schema slips). Accepted
  because a miss is cheap — the user says it again — while a poisoned memory makes the
  agent confidently wrong forever.
- **A number in this repo went stale and was corrected rather than quietly kept.** The
  "~60 s per extraction" figure above was a CPU measurement. Re-measured on GPU over
  all 150 cases on 4 September: p50 3.8 s, p95 4.6 s, 65 tok/s
  (`backend/app/config/settings.py:46-52`,
  `data/benchmarks/discord_memory_extractor_20260904_qwen9b_full150.json`).
- The guard refuses only the *autonomous* path. A human approving on the dashboard is
  the guard, and stays free to apply anything. A false refusal costs one review; a
  false accept corrupts the ledger.

### What now catches it

`backend/tests/test_discord_memory_guard.py:105-142` —
`test_production_guard_reproduces_the_measured_benchmark_policy` re-derives coverage
and poison from the stored 9b benchmark results using **the production functions**,
and asserts `coverage >= 0.90` and `poison <= 0.25`. The measurement and the shipped
code cannot drift apart silently: retuning the guard past the measured trade-off turns
the test red.

---

## 4. The nightly gate was red for eight days for a reason it does not watch

**27 August – 4 September 2026 · fixed and verified green, not yet committed**

### What broke

Two independent faults, back to back, in the one unattended check that watches the
shipped retrieval configuration.

**Fault A — one secret, two configuration sources.** The operator put
`LOCAL_AI_API_KEY` into `.env`. The server reads `.env` through pydantic-settings
(`backend/app/config/settings.py:16`, `local_ai_api_key` at line 23), so it began
enforcing the `X-API-Key` header on write endpoints. The eval harness read only
`os.environ` — and the Windows Scheduled Task that runs it exports nothing. Every run
that got as far as the eval died `401 Unauthorized` on the very first
`POST /documents/upload`.

**Fault B — an error message that was a question.** The lab uvicorn's stdout went to
`DEVNULL`, so when the lab API failed to come up, exit 97 could only print
`lab API never became healthy (Ollama or Docker down?)`. That is a guess, and it left
nothing behind to answer with.

### How it hid

It did not hide — it was loud in the wrong register. A gate that is red every night
for a reason unrelated to what it guards teaches you to stop reading it. The exact
record (`data/logs/nightly_eval.log`):

| Run (UTC) | Exit | What it said |
| --- | --- | --- |
| 2026-08-26 20:00 | 0 | last green run |
| 2026-08-27 20:00 | 1 | `401 Unauthorized` for `/documents/upload` |
| 2026-08-28 → 08-31 | — | **no entries at all** (machine off; no `app_*.log` for 29–31 Aug) |
| 2026-09-01 12:14 | 97 | `lab API never became healthy (Ollama or Docker down?)` |
| 2026-09-01 20:00 | 97 | same |
| 2026-09-02 20:00 | 97 | same |
| 2026-09-03 20:00 | 1 | `401 Unauthorized` for `/documents/upload` |

Eight days with no usable verdict on retrieval quality. Note the shape: of the five
recorded runs, only **two** actually reached the eval and hit the 401; **three** died
before the API was even serving; and four nights left no record whatever. Three
different causes producing one undifferentiated "red".

The second-order failure is the important one. The exit-97 message could not
distinguish *"the machine was powered off"* from *"something regressed"*. Both look
the same in `ATTENTION_nightly_eval.txt`, and only one of them deserves attention.

### What found it

Reading `data/logs/nightly_eval.log` end to end on 4 September and noticing that the
last green run was 26 August. Nothing alerted; the check that is supposed to alert was
the thing that was broken.

### The fix

Both faults, on 4 September. **These changes are in the working tree and not yet
committed at the time of writing**, so the citations below are file:line rather than
a sha.

They have, however, been confirmed end to end. `scripts.nightly_eval` was run by hand
on 4 September and exited 0 — the first green run since 26 August. It reproduced the
recorded baseline exactly (recall@5 0.9878, MRR 0.9360, doc_hit 0.9268), left
`br_backup_thu_cong` as the single known miss, passed the new per-question gate
against all 82 recorded ranks, and deleted `ATTENTION_nightly_eval.txt` on its way
out. The report is `data/evaluation/results/rag-multidoc-20260904-180426.json`.

- `api_key_headers()` in `backend/scripts/evaluate_rag.py:19-42` falls back to
  `Settings` — *the same file the server reads* — when `os.environ` has no key. An
  explicit environment variable still wins, which is what CI and one-off runs against
  another host rely on. A missing `.env` or unreachable database sends no header
  rather than refusing to start. `backend/scripts/redteam_rag.py:34` imports the same
  function instead of reimplementing it, so the two harnesses cannot diverge.
- `diagnose()` in `backend/scripts/nightly_eval.py:54-79` replaces the guess with
  evidence: `ollama ps`, `docker compose ps`, and the last 15 lines of the lab
  uvicorn's own output, which now goes to `data/logs/nightly_eval_lab_api.log`
  instead of `DEVNULL`. A missing binary *is* the diagnosis, so it is recorded rather
  than raised. None of the three probes costs a model call.
- `stop_api()` is called *before* `diagnose()` on the failure paths, because the
  uvicorn log is only complete once its writer is gone
  (`nightly_eval.py:82-90`, `151-161`).
- The log tail was raised from 12 lines to 40 (`nightly_eval.py:187`). Twelve lines
  fitted a Python traceback and nothing else; a startup diagnosis is three command
  outputs plus a log tail, and truncating it to 12 threw away the two that say whether
  Docker was even running.

### What now catches it

The failure line now carries the three facts that separate the three causes, so a red
gate is a starting point rather than a shrug. What is **not** yet fixed: nothing
watches for the *absence* of a run — the four nights from 28 to 31 August produced no
entry, and no mechanism would have noticed. `ATTENTION_nightly_eval.txt` only exists
when a run happened and failed.

---

## Patterns

**Instrumentation nobody reads is not instrumentation.** The tokenizer printed
`778 > 512` on every call for four days and the process threw it away; the pyvi canary
tested only the three words hard-coded in its own assertion, catching 0.6% of the
segmentations that could actually move. Both looked like coverage. The test is whether
something durable reads the output and whether it would fail on a case it does not
already name.

**An average cannot see a permutation.** P4-6 improved every aggregate — recall, MRR,
doc_hit all up — while one question went from found to missed. Three questions breaking
and three improving leaves recall and MRR exactly where they were. That regression
reached a document only because a human read the per-question ledger by hand, which is
why the gate now records and checks every question's rank individually.

**Two sources of truth for one value will drift, and the drift surfaces somewhere
unrelated.** A secret in `.env` that the server reads and the harness does not took
down the nightly gate for eight days. A chunk size counted by a regex word counter on
one side and a subword tokenizer on the other truncated 65% of the production corpus.
In both cases the fix was to make the second reader consult the first reader's source,
not to keep them in sync by discipline.

**A red gate is not a diagnosis.** Exit 97 said `Ollama or Docker down?` — a question,
not a finding — and three different causes (an unexported secret, a powered-down
machine, a real regression) all rendered as the same red. A gate that cannot say
*why* it is red trains you to stop looking at it, at which point it protects nothing.
