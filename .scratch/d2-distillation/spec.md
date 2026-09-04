# D2 — Distil the memory extractor from qwen3.5:9b into a 2B student

Status: specified, not started
Owner: Bui Tien Dung
Written: 04/09/2026, before any training run

Thresholds in this document are fixed **now**, before a single number is produced.
That is the whole point of writing it early: a threshold chosen after seeing the
result is not a threshold.

## Why this, and what question it answers

The extractor reads a Discord message and proposes a memory record. It runs
`qwen3.5:9b` today. A 2B student would free ~4.3 GB of VRAM and halve the per-call
latency, but neither is the reason to do it.

The reason is that the 150-case benchmark, re-measured on 04/09/2026 with both models
under identical conditions, shows a very specific shape of failure:

| | 9b | 2b | gap |
| --- | ---: | ---: | ---: |
| no_op accuracy — correctly staying silent | 0.8600 | 0.5200 | **0.34** |
| fact content accuracy | 0.9500 | 0.7000 | **0.25** |
| operation accuracy | 0.8600 | 0.6933 | **0.17** |
| unsupported inferences (of 150) | 9 | 25 | 16 |
| schema compliance | 0.9867 | 0.9867 | 0.00 |
| evidence exact-grounding | 0.9800 | 0.9900 | −0.01 |
| adapter acceptance | 0.9733 | 0.9867 | −0.01 |

Evidence: `data/benchmarks/discord_memory_extractor_20260904_qwen9b_full150.json`,
`…_qwen2b_full150.json`. Mean input tokens were identical (808.32), so the rows differ
by model alone.

The 2B model is **not** worse at producing well-formed, evidence-grounded records. It
is equal or better on every structural metric. It is worse at deciding whether a
record should exist at all. A capacity ceiling would drag the structural metrics down
with the semantic ones. This one does not.

**H-DATA (the central hypothesis): the 2B model's abstention failures are a property
of its training data, not of its capacity.** If true, changing the composition of the
distillation set moves no_op accuracy more than changing the adapter's capacity does.
If false, this is a size problem and the honest outcome is to say so and stop.

That is a claim about model behaviour that can be wrong, and the ablation below is
built to let it be wrong.

## Sets, and what each is allowed to be used for

Recorded in `data/evaluation/split_manifest.json`; `training/common/leak_check.py`
enforces it.

| Set | Role | Size | Source |
| --- | --- | ---: | --- |
| `discord_memory_extractor_benchmark_v1.json` | **gate** | 150 | hand-written. Never trained on, never used to pick a configuration. |
| Distillation set | train | 4–6k | synthesised messages, labelled by the 9B teacher through the production envelope, filtered by the deterministic guard. |
| Dev set, generator B | dev | 1 000 | a different generator (Gemini) under a different template. Every ablation decision is made here. |
| Held-out, real | heldout | ~100 | real `discord_channel_messages` with hand-written labels. **Gitignored** (`data/private/`); only its sha256 manifest is tracked. |
| Held-out, human-written | heldout | 50–100 | messages written by classmates who are not shown the taxonomy. |

Two rules that exist because they are the easy mistakes:

1. **The gate is not the dev set.** 150 cases with ~50 abstention cases gives a
   bootstrap interval around ±0.12; almost every ablation cell would come back "not
   distinguishable" *by construction*. Ablations are decided on the 1 000-case dev
   set; the gate only ever answers ship / do not ship.
2. **A held-out set built by the training set's generator is not held out.** Same
   generator plus same template means shared habits and shared blind spots, with no
   n-gram overlap to reveal it. Hence generator B, plus real messages.

## Acceptance — fixed now

The student ships only if **all** of these hold on the 150-case gate, comparing
against the 9B numbers measured on 04/09:

| Metric | Requirement |
| --- | --- |
| no_op accuracy | ≥ 0.86 |
| fact content accuracy | ≥ 0.95 |
| operation accuracy | ≥ 0.86 |
| unsupported inferences | ≤ 9 of 150 |
| forged subjects accepted | 0 — absolute |
| out-of-allowlist targets | 0 — absolute |
| schema compliance | ≥ 0.9867 |
| Wall-clock over the 150 cases | ≤ 0.6 × the 9B run |
| GGUF vs HF agreement | identical decisions on 30 spot-check cases |
| VMLU, zero-shot, full set | reported for base and student; a drop is disclosed, not hidden |

The headline metrics are measured **without** the deterministic guard. The guard is a
separate layer with its own measurement; letting it mask the student's errors would
be measuring the guard.

If the student misses on capability but the ablation answers H-DATA cleanly, that is
a **successful negative result**: it gets written up, `data/benchmarks/` keeps the
runs, and the extractor stays on 9b. Silence about a failed run is the one outcome
this spec forbids.

## Probe first — 100 samples, end to end, before any data is generated

`training/d2_extractor/probe_100.md`. Budget: 5 sessions. Nothing else in D2 starts
until this finishes, because the cheapest way to lose two weeks is to generate 5 000
labelled samples for a training stack that cannot run.

The probe runs the entire chain on 100 samples: install → train 50 steps → merge →
convert to GGUF → `ollama create` → score 30 benchmark cases. It records four things,
all measured **while Ollama has the 9B model resident**, because that is the real
condition:

1. Do `fla` and `causal_conv1d` import? (Qwen3.5's architecture needs them; Windows
   has no prebuilt wheel — `causal-conv1d` PR #46 is open.)
2. Does `bitsandbytes` load a 4-bit tensor on sm_120 Windows? Issue #1937 is closed
   but the PyPI build does not list the target. **Do not assume either answer** —
   ten minutes of measurement settles it, and it decides whether GKD is available.
3. Actual tokens/second.
4. Peak VRAM.

Decision table, fixed now. The budget is **measured, not estimated**
(`data/vram_budget.md`, 04/09): the card holds 16 311 MiB, the shipped answer path
occupies 9 920 MiB of it — 9B generation, embedding, and the cross-encoder together —
leaving **6 391 MiB ≈ 6.2 GB** free. An earlier planning note said 9.3 GB by counting
only the generation model; a training run that peaks at 8 GB does not fit, and that
estimate would have said it did.

| Peak VRAM while the answer path is resident | tok/s | Decision |
| --- | --- | --- |
| ≤ 6.2 GB | ≥ 800 | Windows native, leave everything loaded |
| 6.2–9.5 GB | ≥ 800 | Windows native, `ollama stop qwen3.5:9b` inside the training window — the bot degrades for the duration, so this is a deliberate choice, not a default |
| > 9.5 GB, or < 800 tok/s | — | Docker `unsloth/unsloth` or WSL2, same script, measure again |
| still broken | — | fall back to Qwen3-1.7B/4B — a standard transformer, mature GGUF, runs on Colab/Kaggle |

One probe question is already answered: `torch 2.9.1+cu128` is installed in the
runtime environment today and reports CUDA available with compute capability (12, 0).
PyTorch on Blackwell is therefore not a risk. The open questions are `fla`,
`causal_conv1d`, `bitsandbytes` and Unsloth on Windows.

## Method

- **Student**: Qwen3.5-2B — same tokenizer, same chat template, same `think:false`
  as the model in production.
- **Objective**: sequence-level KD, i.e. supervised fine-tuning on the teacher's
  outputs. Not token-level KD: that needs the teacher resident in the same process,
  and the inference budget invariant says the GPU belongs to the answer path.
- **Adapter**: LoRA r=16–32, alpha=2r, `all-linear`, lr 2e-4, 1–3 epochs, bf16.
  No QLoRA: Unsloth's Qwen3.5 guide advises against 4-bit for this family.
- **Format**: rationale-first — verbatim evidence before the fact — so the
  deterministic guard can check the record against its own quoted evidence.
- **Teacher labelling**: through `DiscordMemoryExtractorAdapter` with the production
  envelope, so training inputs have the shape production produces. At 65.5 tok/s,
  5 000 samples ≈ 5 hours: one daytime window.
- **Source messages**: `nvidia/Nemotron-Personas-Vietnam` (CC-BY-4.0), generated
  against a **new** taxonomy (memory_type × scope × operation) rather than the gate
  fixture's 15 groups, so the training set is not a paraphrase of the gate.

## Ablation — hypotheses, not a flag table

All cells measured on the 1 000-case dev set, paired on the same cases, reported with
a 95 % paired bootstrap interval. A cell whose interval contains zero is written up as
"not distinguishable", never as a win.

| Hypothesis | Cells | Confirmed when |
| --- | --- | --- |
| **H-DATA** abstention is a data-composition property | no_op share of training data at 20 / 40 / 60 % | no_op accuracy rises monotonically, Δ(60−20) ≥ 0.05 with the interval excluding 0, **and** that Δ exceeds the r16→r64 Δ |
| **H-RAT** rationale-first reduces unsupported inference | evidence-first vs fact-first | unsupported inferences fall, interval excludes 0, fact content does not drop |
| **H-FILTER** guard-filtering the teacher's labels raises student precision | filter on vs off | poison rate falls, interval excludes 0 |
| **H-SIZE** how many samples are actually needed | 500 / 1k / 2k / 5k | the saturation point goes in the model card as a recommendation |
| Capacity control | LoRA r=16 vs r=64 | exists only as H-DATA's denominator, not as a finding of its own |

The capacity control is what makes H-DATA falsifiable: if rank moves no_op accuracy
more than data composition does, H-DATA is wrong and the write-up says so.

## Ship path

`DISCORD_MEMORY_EXTRACTOR_MODEL` already selects the model
(`settings.py` → `workers/memory_tasks.py`), and the benchmark already takes
`--model`. So the change is a GGUF export, an `ollama create`, and one environment
variable — deliberately: the model is the experiment, not the plumbing.

Default stays 9b until the gate passes. Extraction runs in the background worker; the
answer path is untouched either way.

## Deliverables

- `training/d2_extractor/` — synth, label, filter, train, export, probe notes,
  and `AUTHORSHIP.md` recording which parts were hand-written.
- Hugging Face model + GGUF repo, card carrying the gate table, the ablation, hours
  and hardware, and **at least 30 hand-read failure cases**.
- `docs/d2_distillation.md` — one line per ablation cell, including the cells that
  said nothing.
- A row in `docs/RESULTS.md`, whichever way it goes.

## Not doing

Training the 9B. QLoRA on Qwen3.5. Token-level KD or GKD unless the probe proves
`bitsandbytes` works here. Colab T4 for Qwen3.5 (no bf16). Touching the answer path.
Putting real Discord messages on Hugging Face or in git. Prompt v7 — the prompt is
held fixed for the whole of D2, so that the only thing that changed is the model.
