# training/

Everything that produces a model, kept out of the runtime.

The API, the workers and the launcher never import from this directory, and
`requirements-train.txt` is not part of `pyproject.toml`. That separation is
invariant #5: a clean machine must be able to start the product without
downloading PyTorch.

```
training/
├── requirements-train.txt   installed into a SEPARATE .venv-train
├── common/                  shared guards, used before any training run
│   ├── split_manifest.py    what each evaluation set is, and its hash
│   └── leak_check.py        text overlap + generator/template collisions
├── reranker/                H1 — Vietnamese cross-encoder (not started)
├── d2_extractor/            H2 — distil the memory extractor (spec written)
└── vi_nli/                  H3 — NLI encoder for verifier + grounding (conditional)
```

## Before any training run

```bash
python -m training.common.split_manifest --check      # eval sets unchanged
python -m training.common.leak_check --construction-only
python -m training.common.leak_check --candidate <the training file>
```

The first fails if an evaluation set changed under a number already recorded. The
second fails if a "held-out" set shares a generator and template with the training
set — the leak that no n-gram check can see, because every row genuinely differs.
The third fails on text overlap with anything marked `gate` or `heldout`.

Nothing here is a formality. `local_ai_core_baseline.txt` shares **100 %** of its
8-grams with the multidoc eval corpus: they are the same project documentation cut
two ways. A training set built from repo documentation would contaminate both evals
at once, and the aggregate scores would look better for it.

## The lifecycle a model goes through

1. A spec in `.scratch/<slug>/spec.md` with acceptance thresholds, the behavioural
   hypothesis, the role of each dataset, and a licence column — all fixed **before**
   measuring.
2. `split_manifest --check` and `leak_check` green.
3. A 100-sample end-to-end probe: train → export → serve → score. Before generating
   the large dataset, never after.
4. Train inside the measured daytime window — see below.
5. Score in three layers: the internal gate, a public human-written set, and latency
   plus VRAM against `data/vram_budget.md`. Ablations go on a separate dev set large
   enough to resolve the effect, with paired bootstrap intervals.
6. One tracked JSON per run: git sha, dataset hashes, base model and revision,
   hyperparameters, hardware, wall-clock, peak VRAM.
7. Hand-read at least 30 failure cases before writing the model card. This part is
   not delegated — see `AUTHORSHIP.md` in each model directory.
8. Ship only if the gate passes (invariant #4). A negative result is published, not
   deleted: `docs/RESULTS.md` gets a row either way.

## When the GPU is free

Counted from `data/discord_listen/passive_counts.jsonl` on 04/09/2026: 44 messages
from real people, over 2 days, by local hour (UTC+7).

| Hour | 22 | 23 | 02 | 03 | 04 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Human messages | 1 | 22 | 11 | 5 | 5 |

**Zero human messages fell outside 22:00–04:59.** The nightly eval also runs at 03:00
local. So the hours that intuition calls "nobody is around" are the only hours anybody
is around, and an earlier plan to train overnight would have contended with both real
users and the one unattended quality check.

Training window: **05:00–21:00**. GPU off limits 22:00–04:59. A long run holds a lock
file so the nightly eval can skip with a logged reason instead of failing.

Caveat, because this is a small sample: 2 days and 44 messages, from a handful of
people. It is enough to reject "train at night" and not enough to claim the shape of
a normal week. Re-count after a longer run of `scripts.passive_listen_report` before
treating the window as settled.

## Environment notes

Blackwell (sm_120) on Windows is not a well-trodden path, and two dependencies are
the usual reason a run does not start:

- `causal-conv1d` has no Windows wheel (PR #46 open). Qwen3.5's architecture wants
  it; without it `transformers` falls back to a slower path rather than failing, so
  check the log instead of assuming.
- `bitsandbytes` on sm_120 Windows: issue #1937 is closed, but the published wheel
  does not list the target. Ten minutes of testing settles it and decides whether
  token-level distillation is available at all. Do not plan around either answer
  before measuring.

Fallback order, cheapest first: keep Ollama loaded → stop the 9B model during the
training window → Docker `unsloth/unsloth` or WSL2 → a different student
(Qwen3-1.7B/4B, a standard transformer with mature GGUF support).
