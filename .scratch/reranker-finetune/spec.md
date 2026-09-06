# Fine-tune the reranker for Vietnamese legal retrieval

Status: rule pre-registered 05/09/2026, before the treatment arm exists; **control re-based 07/09/2026** on the corrected chunker's index (see below)
Owner: Bui Tien Dung
Model: `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` — 118M, 12 layers, hidden 384,
XLM-R vocabulary, currently shipping as `rag.reranker.model`

Thresholds are written down before any trained model exists, and are expressed
against the **control arm**, not against a number chosen after seeing results.
The repository has one worked example of what happens otherwise: P4-6 shipped
against a rule that was violated in exactly one case, and that is only known
because the rule existed in writing first.

## What is wrong, and how much room there is

The system finds the right document inside the top three for 94% of questions,
but puts it first for only 76%. The reranker exists to close that gap, and on
this corpus it has never been measured.

| | Acc@1 | Acc@3 | recall@5 | MRR | Measured |
| --- | ---: | ---: | ---: | ---: | --- |
| BM25 only | 0.7563 | 0.9048 | 0.9150 | 0.8276 | 05/09, reranker off |
| BM25 + dense + RRF | 0.7602 | 0.9391 | 0.9480 | 0.8481 | 04/09, reranker off |
| **+ current reranker — CONTROL** | **0.7766** | **0.9543** | **0.9619** | **0.8622** | 05/09 |
| BM25 + dense + RRF, corrected chunker, reranker off | 0.7614 | 0.9607 | 0.9695 | 0.8554 | 06/09, index rebuilt |
| **+ current reranker on the corrected index — CONTROL, re-based** | **0.7843** | **0.9657** | **0.9810** | **0.8722** | 06/09 |

The dense layer contributes **+0.004** at rank 1 over BM25 alone. Nearly all of
the rank-1 performance is BM25. That is why this experiment targets the
reranker and not the embedding.

**Re-based 07/09/2026.** The chunker that built the index above emitted chunks containing the
chunk before them (`.scratch/chunker-overlap-containment/spec.md`). Fixing it and rebuilding the
index moved the control to **Acc@1 0.7843 · recall@5 0.9810 · MRR 0.8722**, so
every threshold below is read against those numbers: condition 1 now asks for Acc@1 ≥ **0.8163**.
Headroom is recall@5 − Acc@1 = 0.1967; **155 questions** have the answer in the returned
set but not first. The 05/09 rows are kept because the promotion/demotion counts below were measured on them.

**The control arm is the finding that justifies the whole experiment.** The
reranker's net contribution is +0.0165 Acc@1, but that net hides what it is
actually doing:

| | Questions |
| --- | ---: |
| Promoted to rank 1 | **85** |
| Demoted **from** rank 1 | **72** |
| Net | +13 of 788 |

It is close to a coin flip. A reranker that demotes 72 correct top answers is
not ranking Vietnamese legal text — it is reordering it nearly at random with a
slight positive bias, which is what a model trained on machine-translated
mMARCO would be expected to do.

So the goal is not "make it cleverer". It is **stop it destroying rankings it
does not understand**. Recovering only those 72 questions is worth **+0.0914**
Acc@1 on its own — nearly three times the acceptance threshold below.

Ceiling: if the reranker ordered its candidates perfectly, Acc@1 would equal
recall@5 = 0.9619. Available headroom is 0.185, and the threshold asks for 17%
of it. **146 questions** currently have the answer somewhere in the returned set
but not first; every claim of improvement is a claim about those.

## Three assumptions that turned out to be false

Recorded because each one shaped an earlier version of this plan.

| Believed | Measured 05/09 | Consequence |
| --- | --- | --- |
| The reranker costs ~693 ms per 15 candidates | **39.5 ms** | There is no latency problem. 693 ms belonged to `Qwen3-Reranker-0.6B`, rejected in August. |
| Vietnamese expands ~1.6× regex token → subword | **1.00** on this legal corpus | Legal chunks fit the 512 window; the sliding-window patch rarely fires here. The 1.6× was measured on this project's markdown, which is full of code fences and English identifiers. |
| The 0.7602 baseline includes the reranker | It does **not** | Comparing a trained reranker against it would credit the training with the effect of switching the reranker on. Hence the control arm. |

## Data

Built by `training/reranker/build_splits.py`, seed 20260905, in
`data/evaluation/reranker_v1/`.

| Split | Queries | Role |
| --- | ---: | --- |
| train | 2 168 | gradient updates only |
| dev | 240 | early stopping and loss selection; never reported |
| test | 788 | reported numbers only; the control arm is measured on it |

Two defects in the published packaging were handled: 102 duplicate lines in
`queries.jsonl` removed, and **24 queries present in both train and test qrels**
dropped from train. Those 24 carry a *different* relevant document in each file,
which also proves the test labels are incomplete — every score on this set
understates the truth, and that cannot be fixed here, only stated.

**Chunk-level positives, built 06–07/09.** The reranker scores chunks, so the document-level
qrels were carried down to chunks: 1413 single-chunk articles transfer with no inference; the
813 (question, article) pairs whose article splits were read and judged chunk by chunk (93.3%
agreement on a blind re-audit of 45), then remapped onto the corrected chunker by answer
sentence and the judge's own citation (`training/reranker/remap_judgements.py`). Result:
**2376 positive chunks** — `chunk_labels_clean.jsonl` (1413) and
`chunk_labels_judged.jsonl` (963); 16 pairs had no answering chunk and are dropped.

Negatives are mined from the **full 61 425-document corpus**, not the 2 947-document
evaluation subset. Mining inside the subset would produce artificially easy
negatives and would touch the 447 documents that are test answers.

**Open, needs a decision before mining:** train and dev share 89 positive
documents while train and test share none, so dev measures a systematically
easier task than test and early stopping on it will stop late.

## Acceptance, fixed now

Ships only if all of these hold on the 788-question test set, against the
**control arm** (current reranker, untrained, switched on).

| # | Condition | Threshold |
| --- | --- | --- |
| 1 | Acc@1 | ≥ control **+ 0.032** |
| 2 | Acc@3 | ≥ control − 0.01 |
| 3 | Questions going from found to missed | 0 |
| 4 | Latency, 15 candidates | ≤ 100 ms (control measures 39.5 ms) |
| 5 | Project's own 82-question eval | no question goes from found to missed |
| 6 | Loads in the production venv (`sentence-transformers<4.0`) | yes, verified before any number is reported |

**Why +0.032 and not something smaller.** On 788 questions, a paired McNemar
test at 80% power resolves a difference of roughly 3.2 to 5.5 points depending
on how often the two systems disagree. A gain below that is indistinguishable
from chance, so promising less would be promising something unmeasurable.

Condition 6 is not a formality: the model is trained under
`sentence-transformers` 5.7.0 and served under 3.4.1. A checkpoint that only
loads in the trainer is not a shippable model.

## Decisions — one settled, one still open

Neither is mine to make; both change the shape of the training data.

**Training unit — settled: chunks.** Decided by the owner on 06/09 ("lấy chunk retriever trả về, bạn
sẽ là người đọc từng cái rồi ra quyết định"), and the labels above are built that way. The table
is kept for the record of what was weighed.

**Training unit — chunk or whole document.** The reranker scores *chunks* at
inference, but the labels are attached to whole legal articles. Measured on the
2 233 positive pairs with the model's own tokenizer, **38.2% exceed the 512
window** as whole documents (median 376, p95 2 031 subwords).

| Option | For | Against |
| --- | --- | --- |
| Train on chunks | matches exactly what the reranker sees in production; loses no data | which chunk holds the answer must be inferred, since the labels are document-level |
| Drop pairs over 512 | one line of filtering | loses 38.2% of an already small set, and loses precisely the long, hard documents |
| Keep and let them truncate | costs nothing | teaches the model "this pair is positive" on text that may not contain the answer |

**The 89 shared documents between train and dev.**

| Option | For | Against |
| --- | --- | --- |
| Rebuild dev disjoint from train by document | dev becomes an honest proxy for test | costs training data; dev hash changes |
| Keep two dev sets, require both to improve | loses nothing, shows both angles | doubles evaluation cost; the rule is untested |
| Keep as is, record the bias | free | choosing checkpoints with a ruler known to be bent, by an unknown amount |

## Negative mining — the one thing that is settled

Not settled by opinion. Measured on this exact configuration — cross-encoder,
binary labels, Vietnamese legal text (arXiv 2507.14619):

| Negatives per query | Taken straight from the top | Sampled at random within the top 90 |
| ---: | ---: | ---: |
| 2 | 0.2689 | 0.7681 |
| 5 | 0.4796 | 0.7791 |
| 10 | 0.6751 | 0.7892 |
| baseline, no fine-tuning | 0.5584 | |

MRR@10. Taking the hardest negatives drops the model **below the untrained
baseline** — worse than doing nothing. So: sample within a wide window rather
than take the top.

Do **not** skip the top few ranks either. The system's error lives at ranks 2–3;
excluding them means never teaching the model to separate exactly the candidates
it gets wrong.

Cheap check before training: score every mined negative with the untrained
reranker. In the paper above, a poisoned negative set had 50.9% of samples
scoring ≥ 0.9; a safe one had 8.6%. Above roughly 10%, the set is poisoned.

## Loss — deliberately not decided in advance

The published evidence points both ways and every comparison was measured at
roughly 43× more data than we have. One training epoch takes 74 seconds and peak
VRAM is 2.2 GB at batch 8, so comparing six losses costs under an hour.

Choosing the loss by argument here would be choosing the more expensive way to
be wrong. It is selected on **dev**, and only then.

## If the rule fails

The change is not shipped, the result is recorded as a negative one, and
`docs/RESULTS.md` gets a row either way. A negative result answers the same
question — whether the gap between this reranker and Vietnamese-specialised ones
is closable with 2 168 in-domain examples — and costs less to believe.

## Result

*(filled in after the run)*
