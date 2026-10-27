# Kept eval reports

Every other file in `data/evaluation/results/` is per-run scratch and stays out
of git. These four are the retrieval chain a reader can walk end to end: each
number quoted in `docs/RESULTS.md`, in a model card, or on a CV resolves to one
of them, and each carries all 82 per-case rows — so a claim like "11 questions
improved, 2 regressed" is checkable rather than asserted.

Measured on `PC-dungbt`, lab database, embedding `qwen3-embedding:0.6b`,
corpus `data/evaluation/fixtures/multidoc/` (5 documents, 82 questions).

| File | Configuration | recall@5 | MRR | doc_hit |
| --- | --- | --- | --- | --- |
| `rag-multidoc-20260821-162010.json` | bare: contextual OFF, reranker OFF | 0.8659 | 0.7287 | 0.7683 |
| `rag-multidoc-20260821-162626.json` | P4-2: contextual ON, reranker OFF | 0.9146 | 0.7967 | 0.8415 |
| `rag-multidoc-20260821-172245.json` | P4-3: contextual ON, reranker ON | 0.9756 | 0.8581 | 0.8537 |
| `rag-multidoc-20260825-190252.json` | P4-6: + sliding-window rerank (shipped) | 0.9878 | 0.9360 | 0.9268 |

Two cautions, because a number without its measuring conditions is a rumour:

- The bare row here is the local run. `data/evaluation/rag_multidoc_baseline_bare.json`
  records MRR 0.7341 for the same configuration measured **in CI** — a different
  machine, hence a slightly different number. Compare like with like.
- `data/evaluation/rag_multidoc_baseline.json` is what the gate reads. These
  files are evidence, not gates; promoting a file here never changes a gate.

To promote another report: copy it in, add a row above, and cite it from
`docs/RESULTS.md`. Nothing else in `results/` is tracked.

## Agent Eval

`agent-eval-v0.1-baseline-20261027/` is the first measurement of the agent itself
(`AgentService.run()`, three tools, real `qwen3.5:9b`) on the 40-task set in
`data/benchmarks/agent_eval/v0/` (`agent-eval-v0.1`, sha256 `19d59249…`). Four runs:
three at temperature 0 + seed 42, one at 0.4 as shipped. Each run directory carries
every task's answer, tool calls and per-check grade; `REPORT.md` has the reading,
including 16 hand-graded tasks against the automatic grader. An exploratory baseline,
not a statistical claim.

`agent-eval-v0.2-harness-20261027/` is ticket 10: the same agent on `agent-eval-v0.2`
before and after two prompt changes (1a: look it up first; 2b: point a Discord turn
at the history when documents come back empty), one warm temperature-0 run and three
runs at 0.4 per condition, judged as pre-registered in the ticket. It also holds the
runs showing that temperature 0 is reproducible only from a cold model (unloaded
before each run), not from warm runs separated by other work. 27 runs; `events.jsonl`
only for the eight that the report quotes.

`agent-eval-v0.2-1a-v2-20261027/` is the follow-up: the 1a guide rewritten in one
sentence (1a-v2), alone and with 2b, against the baseline re-run, one cold run each,
judged by a rule registered in the ticket before running. Not shipped: 33/40 against
34. The re-run baseline repeats the 19:43 cold run answer for answer, three hours later.
`decide.py` recomputes `analysis.json` from the runs.

`agent-eval-v0.2-harness-controls-20261027/` is ticket 16's step 5: the agent before and
after the harness controls (turn budget, coded tool errors, content-free trace), one cold
run each, judged by a rule registered in the ticket. 34/40 both; answers identical except
on the three tasks whose tool error text changed. `decide.py` recomputes `analysis.json`.

`agent-eval-v0.3-baseline-20261028/` is ticket 20's starting point: the shipped agent on
`agent-eval-v0.3` (48 tasks, eight of them asking for more than the 400-character preview
or a paste longer than the API accepts), two cold runs, identical. 35/48: the 40 old tasks
repeat ticket 16's answers word for word, the six long-reading tasks all fail, the long
paste is refused. `analyze.py` recomputes `analysis.json`.

`agent-eval-v0.3-read-20261028/` measures ticket 20 #1 (read_document) against that
baseline: two cold runs, identical, 34/48, an internal regression test registered before
the runs. Four of the five long-reading document tasks pass by opening the chunk; the old
forty fall from 34 to 29, none of them calling the new tool, as the changed prompt reshuffles
37 of their 40 answers. `analyze.py` recomputes `analysis.json`.

`agent-eval-v0.3-read-B-20261028/` is #1-B: the same reading tool with main's agent guide,
so only the tool descriptions announce it. Two cold runs, identical, 38/48: the old forty
at 33 (baseline 34), four of five long-reading tasks, which meets the rule registered before
the runs for proposing it. 39 of the 40 old answers still change wording, and one of the
five old tasks that fail now (doc-10) answers with made-up figures without searching.
`analyze.py` recomputes `analysis.json` across the baseline, #1 and #1-B.

## Agent Eval scorecard history

`agent-eval-scorecard-history.jsonl` is one line per kept agent-eval run (ticket 23): commit,
dataset version and sha256, grader, model, temperature, cold or warm, GPU shared or not, and the
scorecard's four dimensions (correctness, efficiency, robustness, traceability), computed by
`backend/scripts/agent_eval_scorecard.py` from the run's own artifacts. A line is added with
`--append-history <run_dir>` when a run is kept, never for a scratch run, so every line opens.
Compare only lines with the same dataset sha256 and grader; the script refuses otherwise, and
does not compare latency across runs that declare different GPU sharing.

`agent-eval-run-conditions.json` holds cold/warm and GPU sharing for the runs kept before the
runner recorded them itself (28/10): Ollama's loaded models copied from the GPU logs written
just before each run, v0.1 from its REPORT. Unknown stays empty, never guessed.
