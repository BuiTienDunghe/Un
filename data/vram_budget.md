# VRAM budget

Measured 04/09/2026 on `PC-dungbt`, RTX 5060 Ti, **16 311 MiB** total, starting from
an idle GPU (0 MiB in use). Every model added to this system has to fit in what is
left after the answer path, because the answer path belongs to a real user who is
waiting.

## The answer path, as shipped

| Loaded | GPU used | Added | Notes |
| --- | ---: | ---: | --- |
| idle | 0 MiB | — | no process holds the GPU between requests |
| `qwen3-embedding:0.6b` | 2 870 MiB | 2 870 | every retrieval query touches it; Ollama serves it at ctx 8192, and the KV cache dominates a 639 MB model |
| `qwen3.5:9b` | 9 277 MiB | 6 407 | at `num_ctx` 4096, the value `discord_memory_extractor_num_ctx` actually uses |
| cross-encoder reranker | 9 920 MiB | 643 | `mmarco-mMiniLMv2-L12-H384-v1`, loaded in the API process, 512-token window |

**Free with the whole shipped answer path resident: 6 391 MiB ≈ 6.2 GB.**

Not included, and each would take more: `glm-ocr` (loads on demand for scanned
documents), a second generation model, and any model a future feature adds. Ollama
evicts on idle, so these figures are the loaded-state ceiling, not a constant draw.

## The rule

A model introduced by any new work must fit in the free column **while the answer
path is resident**, or it must come with an explicit plan for unloading something —
and unloading `qwen3.5:9b` means the Discord bot answers worse for the duration.

This is invariant #7 expressed in bytes rather than in call counts. A scoring model
that fits is fine; one that forces an eviction is a change to the product's behaviour
and has to be argued for as one.

## Correction to an earlier estimate

An earlier planning note put the free budget at ~9.3 GB, from 16.3 GB total minus
7.0 GB for `qwen3.5:9b` at ctx 16384. Two things were wrong with it: the shipped
`num_ctx` is 4096, not 16384, and the estimate counted only the generation model —
the embedding model and the reranker are equally part of the answer path and together
add another 3.5 GB.

The practical consequence is for D2's training probe. Its decision table was written
against 9.3 GB; the real figure is **6.2 GB**, so a training run peaking at 8 GB does
*not* fit alongside the answer path even though the old estimate said it would. The
thresholds in `.scratch/d2-distillation/spec.md` have been corrected to match.

## Reproducing

```bash
nvidia-smi --query-gpu=memory.used,memory.total --format=csv
ollama ps        # what Ollama holds, and at which context length
```

Measure from an idle GPU and add one model at a time. A single reading of a warm
machine cannot tell you which model is holding what.
