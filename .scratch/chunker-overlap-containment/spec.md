# Chunker overlap carries whole blocks, so each chunk swallows the one before it

Status: **T3 adopted by the owner 07/09/2026**, labels remapped; measured on both eval surfaces
Owner: Bui Tien Dung
Written 06/09/2026 in a worktree from `54bdbf7` by a background session; corrected and
completed the same day in the main tree, which that worktree could not see.

The acceptance rule was fixed **before** any arm was run. It is kept below exactly as
written, with one correction that had to be made before running it (the control arm).

## The defect

`_overlap_blocks` measured overlap in whole `_Block`s, not in tokens. It walked
backwards accumulating blocks until the running total reached `overlap_tokens`, then
returned those blocks *entire*. A 390-token block therefore became the "80-token"
overlap, and the next chunk re-emitted all 390 tokens of it.

Two things in `chunk_pages` turned that into a superset:

1. the loop flushed twice per fragment — once on `> chunk_tokens` and again on
   `>= chunk_tokens` — so the accumulator was emitted, refilled with the whole
   previous block, appended to, and emitted again;
2. nothing checked that the carried overlap left room for the incoming fragment,
   so the second emission was over budget by construction.

A third, independent defect produced the largest chunks: `_fit_block` only fell back
to `_token_slices` when a block held exactly one sentence. A block with several
sentences, one of them longer than the whole budget, emitted that sentence whole.

Found while labelling reranker training data: 483 of the 508 (question, article)
pairs judged to need *two* chunks needed them because the two chunks were the same
text (95.1%).

## Measured, chunker called directly, production settings 480/80

1 630 Zalo Legal articles (the reranker training positives), four versions of the file:

| | base `54bdbf7` | numbered-clause fix only | overlap fix only | **both** |
| --- | ---: | ---: | ---: | ---: |
| documents producing 0 chunks | 587 | 0 | 587 | **0** |
| chunks over 480 tokens | 501 | 1 164 | 0 | **0** |
| longest chunk, tokens | 1 486 | 1 977 | 480 | **480** |
| adjacent pairs, one contains the other | 671 | 1 906 | 0 | **0** |
| characters emitted / characters in source | 1.18 | 1.96 | 0.71 | **1.02** |

Full corpus, 61 425 documents: zero-chunk share 32.70% → 0.62% with either version
that carries the numbered-clause fix, and the two 382-document sets are identical,
so combining the fixes changed nothing about which documents are lost. Zero chunks
over budget at eleven (chunk, overlap) settings including the degenerate (1, 0).

Live databases before any re-index, distinct chunks fully containing another chunk
of the same version: production `local_ai_core` 39 of 190 (20.5%),
`local_ai_core_drill_heldout` 984 of 4 785 (20.6%).

## Verified by 90 independent agents before anything was re-indexed

Six dimensions (content loss, offsets, tables, termination, tests, downstream), every
finding attacked by three refuters. Content loss: 0 tokens on 2 030 documents by four
methods. Termination: 30 000 fuzzed documents, linear time, the Penal Code in 107 ms.
Tests: 14 of 15 passed, the failure being the defect below.

**One defect survived, in the fix itself.** `_trim_to_tail` rebuilt a block's start
offset by proportion: `end − span × len(tail) / len(text)`. But `start`/`end` index the
raw page while `text` is the whitespace-joined paragraph, and a fragment cut by
`_fit_block` inherits its *parent's* span while carrying a slice of the text. The
proportion pointed **14.5% of chunks** at a different passage (11 777 of 81 174 on the
full corpus; 7 749 with zero overlap). Absent from every earlier version. It reaches
only the `locations` citation field — never the embedded text, BM25 or the labels — and
the fix is to stop estimating: keep the block's own, wide, always-true span. Re-measured
on 4 000 documents: wrong offsets 12.70% → 0.00%, chunk content and token counts
identical on 4 000 of 4 000.

A regression test now covers it (`test_overlap_locations_still_contain_the_text_they_label`),
and it failed on the unpatched file and passes on the patched one — checked, because a
first version of that test passed on both.

## Pre-registered acceptance rule

Both arms on a re-indexed corpus. **Control = the current working tree** (numbered-clause
fix, overlap bug present). The original text said `54bdbf7`; that commit loses 32.7% of
the legal corpus outright, so measuring against it would have credited this change with
the numbered-clause fix as well.

Accepted only if all four hold:

1. `recall@5` (treatment) ≥ control − 0.02.
2. `MRR` (treatment) ≥ control − 0.02.
3. **No question goes from found to missed.** `--allow-per-case-regressions` is not passed.
4. Mechanical invariants: zero chunks over `chunk_tokens`, zero adjacent containment
   pairs not traceable to duplicated source text.

If 1 or 2 fails the change is rejected. If only 3 fails, the losing questions are read
individually before any decision.

## Result on the project's own gate — 82 questions, 5 markdown fixtures, shipped config

Noise floor first. The same index evaluated twice gives 82/82 identical questions; a
fresh re-index of the control chunker with contextual retrieval on gives MRR 0.9339,
0.9350, 0.9350 across three measurements (two days). Treatment re-indexed twice from
the same code moved MRR by 0.006. Anything under 0.01 here is not a finding.

| Arm | MRR | Δ | recall@5 | doc_hit | found→missed |
| --- | ---: | ---: | ---: | ---: | ---: |
| control, re-indexed today | 0.9350 | | 0.9878 | 0.9268 | |
| T1 as delivered — tables isolated, re-index 1 | 0.8907 | −0.044 | 0.9878 | 0.9024 | **1** |
| T1, re-index 2 | 0.8967 | −0.038 | 0.9878 | 0.9146 | **1** |
| T2 old table rule | 0.9035 | −0.032 | 1.0000 | 0.9146 | 0 |
| **T3 table flush** | **0.9136** | **−0.021** | **1.0000** | **0.9268** | **0** |

Contextual retrieval off, so the pair is deterministic and the LLM is out of the loop:
control 0.9329, T1 0.8815 (−0.051), T3 0.9167 (−0.016).

**T1 is rejected** — it fails conditions 2 and 3 in every replicate, and the failure is
systematic: two independent re-indexes lose the same question (`xa_gpu_may_chu`) and
demote the same ones. **The cause is not the overlap fix.** Alongside the fix, the
delivered file changed how tables are chunked: every table became a standalone chunk,
never joined by neighbouring prose. Five of the fifteen questions that moved have their
answer inside a table — `storage.backup_interval_hours`, the GPU model, the lockout rule.
Under the control chunker those tables sat inside 371–465-token chunks with the prose
that explains them and shared 13–14 words with the question; isolated, they are 101–103
tokens, share 3–6 words, and lose to the neighbouring prose chunk.

T3 keeps the overlap fix and changes the table rule to: flush the prose *before* a
table without carrying overlap into it, but let the prose *after* the table join it up
to the budget. It is also the cleanest on the invariants (0 over budget, 0 containment,
14 sub-100-token chunks against 92 for T1 on 1 530 mixed documents).

What is left in T3's −0.02 is seven questions slipping one or two ranks whose target
chunk is **byte-identical** across all versions (468/459/468 tokens, same query-word
overlap). What changed for them is the candidate pool from other documents, and the
reranker reorders near-ties when the pool changes — the same behaviour
`.scratch/reranker-finetune/spec.md` records as demoting 72 of 788 correct answers.
It sits on the −0.02 line: 0.0014 below it with contextual retrieval on, 0.004 above it
with it off. A second replicate of T3 in the shipped configuration gave **0.9136 again, the
same seven questions, 70 of 82 identical** — so the −0.0014 is not a draw; it is where T3 sits.

With the reranker **off** (contextual on), control 0.8114 and T3 0.7819 (−0.030), but recall@5
0.9146 → 0.9268 and doc_hit 0.8171 → 0.8537, 0 lost, 1 gained. So the residual is not the
reranker alone: on these five markdown files the corrected chunks find the right *document*
more often and put the right *chunk* first slightly less often. The old chunker's bloat was
acting as free context, and this gate scores rank-1 of the verbatim-phrase chunk.

Full backend suite on the T1 tree: **754 passed, 1 skipped** (746 before this work; the
eight new tests are the five from the background session, two numbered-clause tests and
the offset regression test).

**CI measures the bare path** (no contextual retrieval, no reranker) against
`rag_multidoc_baseline_bare.json`, so that pair was measured too, locally: control
recall@5 0.8537 · MRR 0.7429 · doc_hit 0.7805; T3 **0.9146 · 0.7799 · 0.7927**
— 0 lost, 5 newly found. On the path CI gates, the corrected chunker is a clear gain, and the
repo's own T3 file re-run through the gate in the shipped configuration gave 0.9126 (third
replicate; `data/evaluation/results/kept/rag-multidoc-20260907-023932.json`).

Full suite on the T3 tree: 754 passed, 1 skipped, and one intermittent ERROR in
`test_debt_t1_t2_t3.py` — a Postgres deadlock in that file's cleanup fixture, reproduced
under the **old** chunker as well (1 of 3 file runs) and 0 of 6 under T1/T3, so a pre-existing
race; filed as its own task, not fixed here.

## Result on the held-out legal set — 788 questions, 2 945 articles, no tables

Re-index 4 785 → 3 896 chunks in 745 s (the 19 failures are the 19 unchunkable articles,
identical to control). T1 and T3 are byte-identical on this corpus.

| Reranker | Arm | Acc@1 | Acc@3 | recall@5 | MRR | nDCG@5 | found→missed | missed→found |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| off | control, today | 0.7614 | 0.9391 | 0.9480 | 0.8487 | 0.8738 | | |
| off | **treatment** | 0.7614 | **0.9607** | **0.9695** | 0.8554 | 0.8842 | 1 | **18** |
| on | control, 06/09 03:08, same index | 0.7766 | 0.9543 | 0.9619 | 0.8622 | 0.8869 | | |
| on | **treatment** | **0.7843** | **0.9657** | **0.9810** | **0.8722** | **0.8994** | 1 | **16** |

Conditions 1, 2 and 4 pass with room (recall@5 **+0.0216 / +0.0190**, MRR +0.0067 / +0.0100).
Condition 3 fails by one question in each arm, so both were read:

- `e580bc3c…` *"xe máy đi không đúng làn đường gây tai nạn — phạt bao nhiêu?"* wants
  Article 6 of Decree 100/2019 (motorbikes). Reranker off, the new index returns Article 5
  of the same decree (cars) four times — near-identical wording, the only difference is the
  vehicle. Under the old chunker Article 6 had 1 184- and 1 039-token bloated chunks that
  packed more of its text, and BM25 won on bulk. With the reranker on this question is
  found at rank 2. Not a chunking defect; a sibling-article tie that the reranker exists to break.
- `79279d52…` (training obligations for SMEs) wants `49_2019_tt_btc_7`. Reranker off it
  is at rank 2 on the new index; reranker on, the untrained reranker pushes it out of
  the five returned. Control had it at rank 3. This is the demotion behaviour the reranker
  fine-tune targets, on a candidate the retriever still supplies.

Neither loss is text lost or a document made unreachable; against them stand 18 and 16
questions newly answerable. The rule says a condition-3 failure is a discussion, not an
automatic accept, so the number goes to the owner as it is.

**If adopted, the reranker experiment's control arm moves** from Acc@1 0.7766 /
recall@5 0.9619 to **0.7843 / 0.9810** on the new index, and its threshold
(+0.032 Acc@1 over control) is re-based on that.

## Decisions, recorded

1. **Table rule — T3**, chosen by the owner on 07/09/2026 ("làm T3 đi"). Installed in
   `backend/app/utils/chunking.py`; `test_table_chunks_never_absorb_neighbouring_prose`
   replaced by `test_a_table_starts_its_own_chunk_and_keeps_the_prose_that_follows`, which
   states the rule and the measurement behind it. T1 and T3 chunk all 2 947 held-out
   articles and all 1 626 labelled articles identically (checked, not assumed), so the
   held-out index built for T1 is the T3 index and its numbers stand.
2. **Labels — remapped automatically**, by `training/reranker/remap_judgements.py`.
   Not by the prefix anchor the verification suggested: under the old chunker the first
   hundred characters of chunk N are the end of chunk N−1, so that anchor lands on the
   wrong neighbour in exactly the duplicated cases. The judgement's own structure is used
   instead — a sentence in a marked chunk that also appears in a *genuinely different*
   unmarked chunk is not the answer; one that appears only in marked chunks is — and then
   the judge's verbatim citation (98% quote the text) picks the chunk when a 600–900-token
   old chunk spans two or three new ones.

   | | |
   | --- | ---: |
   | judgements | 813 |
   | remapped | **797** |
   | no answering chunk (dropped, as before) | 16 |
   | needing hand reading | **0** |
   | narrowed by the judge's citation | 579 |
   | positives per pair: 1 / 2 / 3 | 641 / 146 / 10 |
   | positive chunks from judgements | **963** (1 729 before, most of them duplicates) |
   | single-chunk articles, still single-chunk | 1413 / 1 413 |

   One judgement was filed under the wrong article id (its reason quotes the forest
   land-use penalties of `35/2019/nđ-cp+12`, the query's only positive and the one task
   with no judgement); corrected explicitly in `CORRECTIONS`, visible in the output.
   Four narrowed pairs were spot-read: in each, the kept chunk holds the cited answer and
   the dropped ones hold neighbouring penalty brackets.

## Corrections to the background session's notes

| It wrote | Actual |
| --- | --- |
| numbered clauses are still eaten as headings, 47% of body tokens lost | true of its worktree only; the fix was uncommitted in the main tree and is merged here |
| `eval_stack.py` / `chunkexp` do not exist | they exist, uncommitted; used for every arm above |
| `reranker_v1/` does not exist, so no labels are invalidated | it exists; 769 of 813 judgements lose their index (see decision 2) |
