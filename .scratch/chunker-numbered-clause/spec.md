# Numbered clauses are not headings

Status: rule pre-registered 04/09/2026, before any measurement of the change
Owner: Bui Tien Dung

Written before the experiment runs, and not edited afterwards. The repository has
one worked example of what happens otherwise: P4-6 shipped against an acceptance
rule that was decided first and then violated in exactly one case, and the only
reason that is known is that the rule existed in writing beforehand.

## What is wrong

`_HEADING_PATTERN` in `backend/app/utils/chunking.py` has a second branch that
matches any line shaped `<number>. <text>`. It exists to catch real numbered
headings — "1. Introduction", "2.1 Setup".

Vietnamese legal documents are written entirely as numbered clauses. Every line
matches, so the whole document is classified as headings, no body text survives,
`chunk_pages` returns nothing, and `postgres_document_service.py:437` rejects the
document with `Document contains no readable text` — a message that describes
neither the cause nor the truth, since the text is perfectly readable.

Measured on a 2 947-document subset of Zalo Legal 2021 (public, MIT):

| | |
| --- | ---: |
| Documents that produce no chunks | 960 / 2 947 (32.6%) |
| Judged-relevant documents lost | 166 / 447 |
| Questions made unanswerable | 184 / 788 (23.4%) |

The project's own 82-question eval cannot see this. Its corpus is this
repository's own documentation, written in markdown with `#` headings.

## The change

A numbered line is a heading only when it does **not** end in sentence
punctuation (`.` `;` `:` `!` `?`). A heading is a label; a clause is a sentence.

Measured in memory, without touching the repository, on the same 2 947 documents:

| Rule | Documents with no chunks |
| --- | ---: |
| today | 960 (32.6%) |
| reject if the line ends in sentence punctuation | **19 (0.6%)** |
| reject if the line is longer than 80 characters | 29 (1.0%) |
| both conditions | 19 (0.6%) |

Punctuation carries the whole effect; length adds nothing and is therefore not
part of the change. This matters: a rule that survives dropping half of itself is
a signal, not a threshold fitted to a number.

## Why this needs an experiment rather than a patch

Chunking changes every chunk in the system. Boundaries move, so embeddings move,
so BM25 lexemes move, so rankings move. Invariant #4 says a retrieval change
becomes the default only after the eval gate passes, and #8 says measure first.

There is also a confound to control. Contextual retrieval calls the generation
model once per chunk at index time, and that call is not deterministic — so
re-indexing alone moves the numbers, with or without this change. Comparing the
treatment against the recorded baseline would attribute that noise to the change.

## Design

Three arms on the lab database, shipped configuration throughout (contextual
retrieval ON, reranker ON), 82 questions, retrieval-only.

| Arm | What runs |
| --- | --- |
| **baseline** | the recorded `rag_multidoc_baseline.json`, already reproduced exactly on 04/09 |
| **control** | re-index the lab corpus with today's chunker, then evaluate. Isolates re-indexing noise. |
| **treatment** | apply the change, re-index, evaluate |

The comparison that decides is **treatment against control**, not treatment
against baseline.

## Acceptance, fixed now

The change ships only if all four hold.

1. **No aggregate regression.** recall@5 and MRR on the 82 questions are each at
   or above `control − 0.02`, the same tolerance the CI gate uses.
2. **No question is given up.** Zero questions go from found (rr > 0) to missed
   (rr = 0) against the control arm. If exactly one does and the aggregate gain
   is large, that is not an automatic pass: it is written down here with the
   question's id and decided explicitly, in the open.
3. **The point of the change is achieved.** On the Zalo Legal subset, documents
   producing no chunks fall to ≤ 5%, and zero judged-relevant documents are lost.
4. **Nothing that indexes today stops indexing.** All five lab documents still
   produce chunks.

Chunk counts and boundaries in the lab corpus are expected to move. That is not a
regression by itself and is not part of the rule.

If the rule fails, the change is reverted, the lab corpus is re-indexed back, and
the result is recorded as a negative one. `docs/RESULTS.md` gets a row either way.

## After a pass

Re-record `rag_multidoc_baseline.json` (with per-question ranks), note the
re-index requirement in the changelog, and only then ingest the legal corpus for
the held-out measurement that this was blocking.

Production documents also need re-indexing to benefit; that is the operator's
call and is not part of this experiment.

## Result — run 04/09/2026, rule PASSED on all four conditions

Three arms, 82 questions, retrieval-only, shipped configuration, all on
`local_ai_core_chunkexp` built from the same fixtures by the same path. A fresh
database rather than the lab one, because the lab documents reference source
files that no longer exist on disk and cannot be re-indexed in place — see the
note at the end.

| Arm | recall@5 | MRR | doc_hit | Report |
| --- | ---: | ---: | ---: | --- |
| baseline, recorded 25/08 | 0.9878 | 0.9360 | 0.9268 | `rag_multidoc_baseline.json` |
| control — re-index, today's chunker | 0.9878 | 0.9350 | 0.9268 | `results/rag-multidoc-20260904-202349.json` |
| treatment — new chunker | 0.9878 | 0.9339 | 0.9268 | `results/rag-multidoc-20260904-202721.json` |

**The control is the finding that makes the rest readable.** Rebuilding the same
corpus from the same fixtures with unchanged code moved MRR by −0.0010 on its
own, because contextual retrieval calls the generation model once per chunk and
that call is not deterministic. Treatment moves it a further −0.0011 — the same
order of magnitude. Comparing treatment against the recorded baseline instead
would have charged the change with both.

Per question, treatment against control:

| | |
| --- | --- |
| found → missed | **0** |
| missed → found | 0 |
| rank improved | 0 |
| rank slipped | 1 — `ca_lam_moi_sau_phase`, rank 3 → rank 4 |

The single slip is the honest cost and is recorded rather than rounded away. It
sits in `backup_restore.md`, the one eval document whose chunks moved at all: a
numbered line *inside a bash code block* used to be read as a heading, and no
longer is, which shifts one chunk boundary by 71 characters. Four of the five
eval documents chunk byte-identically before and after.

| Condition | Required | Measured | |
| --- | --- | --- | --- |
| 1. no aggregate regression | ≥ control − 0.02 | recall 0.9878 (=), MRR 0.9339 vs floor 0.9150 | PASS |
| 2. no question given up | 0 found → missed | 0 | PASS |
| 3. the point of the change | ≤ 5% unchunkable, 0 relevant lost | 0.6%, 0 of 447 lost, 0 of 788 questions lost | PASS |
| 4. nothing stops indexing | 5 of 5 lab documents chunk | 5 of 5 | PASS |

On the Zalo Legal subset the change moves unchunkable documents from 960 of
2 947 (32.6%) to 19 (0.6%), recovers all 447 judged-relevant documents, and
makes all 788 questions answerable.

Suite: 746 passed, 1 skipped, on a freshly created test database. Two regression
tests added in `backend/tests/test_chunking.py` — one that an article of numbered
clauses produces chunks, one that a real numbered heading is still a heading.

### Found while verifying, and deliberately not fixed here

A numbered heading's title reaches neither the chunk body nor `heading_path`, so
its words are absent from retrieval entirely; a markdown `#` heading in the same
position is recorded normally. Verified identical before and after this change,
so it is pre-existing and out of scope. It has its own ticket.

### Left for the operator

`local_ai_core_lab_20260821` — the database the nightly eval measures — holds
documents whose original files are missing from `data/documents/`, so
`POST /documents/index` answers `SOURCE_UNAVAILABLE` and no chunking change can
ever reach it. The nightly will keep measuring chunks built by the old rule until
that corpus is rebuilt from the fixtures. Production documents likewise only
benefit after a re-index, which is the operator's call and was not part of this
experiment.
