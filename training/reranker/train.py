"""Fine-tune the shipped cross-encoder on Vietnamese legal retrieval.

Run in `.venv-train` (torch cu128, sentence-transformers 5.x). The checkpoint it writes is
NOT shippable until `export_checkpoint.py` has loaded it under the production runtime —
see acceptance condition 6 in `.scratch/reranker-finetune/spec.md`.

**The goal is not "make it cleverer".** Measured on the 788-question held-out set, the
untrained reranker promotes 85 correct answers to rank 1 and demotes 72 — close to a coin
flip, which is what a model trained on machine-translated mMARCO does with Vietnamese
legal text. Recovering only those 72 is worth +0.0914 Acc@1 on its own, nearly three
times the acceptance threshold.

**Dev is scored by document identity, not by chunk label.** The chunk-level judgement pass
covered the train split only, so dev has no chunk labels — and it needs none: the reported
metric is "is a chunk of an answering article ranked first", which is exactly what
`eval_heldout.py` measures on test. Dev is the mined BM25 pool of 45 candidates per
question (`mine_negatives.py`), rescored by the model. Its ceiling is therefore whatever
BM25 put in the pool, printed as `pool_ceiling` so no run is read as better than the
retriever allows.

**The loss is chosen here, not argued in advance.** The published evidence points both
ways and every comparison was measured at roughly 43x more data than these 2 168
questions, so picking by argument would be the more expensive way to be wrong. All six
losses train on the SAME mined pairs, reshaped to what each one needs:

    pairwise   BinaryCrossEntropyLoss           (query, doc, 0/1)
    in-batch   MultipleNegativesRankingLoss     (query, positive, negative_1..n)
    listwise   LambdaLoss, ListNetLoss, PListMLELoss, RankNetLoss   (query, [docs], [labels])

    python -m training.reranker.train --loss all           # the comparison
    python -m training.reranker.train --loss LambdaLoss --epochs 3 --save
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import random
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

import numpy as np  # noqa: E402
import torch  # noqa: E402
from datasets import Dataset  # noqa: E402
from sentence_transformers.cross_encoder import (  # noqa: E402
    CrossEncoder, CrossEncoderTrainer, CrossEncoderTrainingArguments, losses,
)
from sentence_transformers.evaluation import SentenceEvaluator  # noqa: E402

OUT = PROJECT_ROOT / "data" / "evaluation" / "reranker_v1"
MODELS = PROJECT_ROOT / "data" / "models" / "reranker"
BASE = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
BASE_REVISION = "1427fd652930e4ba29e8149678df786c240d8825"
SEED = 20260907

PAIRWISE = {"BinaryCrossEntropyLoss"}
INBATCH = {"MultipleNegativesRankingLoss", "CachedMultipleNegativesRankingLoss"}
LISTWISE = {"LambdaLoss", "ListNetLoss", "PListMLELoss", "RankNetLoss", "ListMLELoss"}
DEFAULT_SWEEP = ["BinaryCrossEntropyLoss", "MultipleNegativesRankingLoss",
                 "LambdaLoss", "ListNetLoss", "PListMLELoss", "RankNetLoss"]


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def grouped_pairs(name: str = "train_pairs.jsonl") -> dict[str, dict]:
    """Mined pairs regrouped per query: {query, positives[], negatives[]}."""
    groups: dict[str, dict] = {}
    for row in read_jsonl(OUT / name):
        group = groups.setdefault(row["query_id"], {"query": row["query"], "positives": [], "negatives": []})
        (group["positives"] if row["label"] == 1 else group["negatives"]).append(row["text"])
    return groups


def build_dataset(loss_name: str, groups: dict[str, dict], rng: random.Random) -> Dataset:
    """One mined set, three shapes. Every shape carries the same texts, so a loss that wins
    here wins on the data and not on a different sample of it."""
    if loss_name in PAIRWISE:
        rows = {"query": [], "answer": [], "label": []}
        for group in groups.values():
            for text in group["positives"]:
                rows["query"].append(group["query"]); rows["answer"].append(text); rows["label"].append(1.0)
            for text in group["negatives"]:
                rows["query"].append(group["query"]); rows["answer"].append(text); rows["label"].append(0.0)
        return Dataset.from_dict(rows)

    if loss_name in INBATCH:
        # One row per positive; the negatives ride along as columns, so a query with two
        # positives contributes two rows sharing its negatives.
        width = min(len(group["negatives"]) for group in groups.values())
        rows: dict[str, list] = {"query": [], "positive": []}
        for index in range(width):
            rows[f"negative_{index + 1}"] = []
        for group in groups.values():
            for text in group["positives"]:
                rows["query"].append(group["query"]); rows["positive"].append(text)
                sample = rng.sample(group["negatives"], width)
                for index, negative in enumerate(sample):
                    rows[f"negative_{index + 1}"].append(negative)
        return Dataset.from_dict(rows)

    if loss_name in LISTWISE:
        width = min(len(group["positives"]) + len(group["negatives"]) for group in groups.values())
        rows = {"query": [], "docs": [], "labels": []}
        for group in groups.values():
            docs = list(group["positives"]) + list(group["negatives"])
            labels = [1] * len(group["positives"]) + [0] * len(group["negatives"])
            order = list(range(len(docs))); rng.shuffle(order)
            order = order[:width]
            # Every list must keep at least one positive or the query teaches nothing.
            if not any(labels[i] for i in order):
                positive = next(i for i, label in enumerate(labels) if label)
                order[-1] = positive
            rows["query"].append(group["query"])
            rows["docs"].append([docs[i] for i in order])
            rows["labels"].append([labels[i] for i in order])
        return Dataset.from_dict(rows)

    raise SystemExit(f"khong biet dinh dang du lieu cho {loss_name}")


class DevDocumentEvaluator(SentenceEvaluator):
    """Acc@1 / Acc@3 / recall@5 / MRR over the mined dev pool, scored by document identity.

    The same contract as `training/common/eval_heldout.py`: a hit is a chunk whose article
    is one the question is judged against. No chunk labels are needed or used.
    """

    def __init__(self, pool: list[dict], batch_size: int = 64, name: str = "dev") -> None:
        super().__init__()
        self.pool, self.batch_size, self.name = pool, batch_size, name
        self.primary_metric = f"{name}_acc@1"
        reachable = sum(1 for row in pool if any(c["doc_id"] in set(row["positive_ids"]) for c in row["candidates"]))
        self.ceiling = reachable / len(pool) if pool else 0.0

    def __call__(self, model, output_path=None, epoch=-1, steps=-1) -> dict[str, float]:
        pairs, spans = [], []
        for row in self.pool:
            spans.append((len(pairs), len(row["candidates"])))
            pairs.extend([row["query"], c["text"]] for c in row["candidates"])
        scores = model.predict(pairs, batch_size=self.batch_size, show_progress_bar=False, convert_to_numpy=True)
        at1 = at3 = at5 = 0
        reciprocal = 0.0
        for row, (start, width) in zip(self.pool, spans):
            wanted = set(row["positive_ids"])
            order = np.argsort(-scores[start:start + width])
            ranked = [row["candidates"][int(i)]["doc_id"] in wanted for i in order]
            hit = next((n for n, ok in enumerate(ranked) if ok), None)
            if hit is None:
                continue
            reciprocal += 1.0 / (hit + 1)
            at1 += hit < 1; at3 += hit < 3; at5 += hit < 5
        total = max(len(self.pool), 1)
        metrics = {f"{self.name}_acc@1": at1 / total, f"{self.name}_acc@3": at3 / total,
                   f"{self.name}_recall@5": at5 / total, f"{self.name}_mrr": reciprocal / total,
                   f"{self.name}_pool_ceiling": self.ceiling}
        self.store_metrics_in_model_card_data(model, metrics, epoch, steps)
        return metrics


def evaluate(model, evaluator: DevDocumentEvaluator) -> dict[str, float]:
    started = time.perf_counter()
    metrics = evaluator(model)
    metrics["seconds"] = round(time.perf_counter() - started, 1)
    return metrics


def run(loss_name: str, groups: dict[str, dict], evaluator: DevDocumentEvaluator,
        arguments: argparse.Namespace) -> dict:
    torch.manual_seed(SEED)
    rng = random.Random(SEED)
    model = CrossEncoder(BASE, revision=BASE_REVISION, num_labels=1, max_length=512)
    dataset = build_dataset(loss_name, groups, rng)
    kwargs = {}
    if loss_name == "BinaryCrossEntropyLoss" and arguments.pos_weight is not None:
        kwargs["pos_weight"] = torch.tensor(arguments.pos_weight)
    loss = getattr(losses, loss_name)(model, **kwargs)

    run_dir = MODELS / f"{arguments.tag}-{loss_name}"
    training_args = CrossEncoderTrainingArguments(
        output_dir=str(run_dir / "trainer"),
        num_train_epochs=arguments.epochs,
        per_device_train_batch_size=arguments.batch_size,
        learning_rate=arguments.learning_rate,
        warmup_ratio=0.1,
        fp16=torch.cuda.is_available(),
        seed=SEED,
        logging_steps=200,
        save_strategy="no",          # the sweep keeps only what it measures; --save writes once at the end
        eval_strategy="no",
        report_to=[],
        dataloader_num_workers=0,    # Windows: workers pay a spawn per epoch and lose to the GPU
    )
    if torch.cuda.is_available():
        # Without this the high-water mark carries over from the previous run in the sweep,
        # so every run after the first reports the same number — and in the 07/09 sweep that
        # number was 26 798 MiB on a 16 311 MiB card, which is how the listwise losses were
        # found to be spilling into system RAM (15-40x slower, same gradients).
        torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    trainer = CrossEncoderTrainer(model=model, args=training_args, train_dataset=dataset, loss=loss)
    trainer.train()
    seconds = time.perf_counter() - started
    peak = torch.cuda.max_memory_allocated() / 2**20 if torch.cuda.is_available() else 0.0

    metrics = evaluate(model, evaluator)
    result = {"loss": loss_name, "rows": len(dataset), "columns": list(dataset.column_names),
              "epochs": arguments.epochs, "batch_size": arguments.batch_size,
              "learning_rate": arguments.learning_rate, "pos_weight": arguments.pos_weight,
              "train_seconds": round(seconds),
              "peak_vram_mib": round(peak), **{k: round(v, 4) for k, v in metrics.items()}}
    if arguments.save:
        model.save_pretrained(str(run_dir))
        result["path"] = str(run_dir.relative_to(PROJECT_ROOT))
    del model, trainer, loss
    torch.cuda.empty_cache()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loss", nargs="+", default=["all"],
                        help="Loss class names from sentence_transformers.cross_encoder.losses, or 'all'.")
    parser.add_argument("--epochs", type=float, default=1.0)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--tag", default=time.strftime("run-%Y%m%d-%H%M"))
    parser.add_argument("--save", action="store_true", help="Keep the checkpoint of every loss run.")
    parser.add_argument("--pairs", default="train_pairs.jsonl",
                        help="Mined pairs file under data/evaluation/reranker_v1/. train_pairs_clean.jsonl is the same set with the negatives the untrained model calls "
                             "confident positives removed — see mine_negatives.py --drop-above.")
    parser.add_argument("--pos-weight", type=float, default=None,
                        help="BinaryCrossEntropyLoss only: weight on the positive class. The mined set is "
                             "1 positive to 9 negatives, so the default (1.0) lets the negatives dominate.")
    parser.add_argument("--baseline-only", action="store_true", help="Score the untrained model on dev and stop.")
    arguments = parser.parse_args()

    pool = read_jsonl(OUT / "dev_pool.jsonl")
    dev_ids = {row["query_id"] for row in read_jsonl(OUT / "zalo_legal_dev.jsonl")}
    dropped = len(pool) - sum(1 for row in pool if row["query_id"] in dev_ids)
    pool = [row for row in pool if row["query_id"] in dev_ids]
    evaluator = DevDocumentEvaluator(pool)
    print(f"dev: {len(pool)} cau (bo {dropped} cau dung tai lieu cua train) · "
          f"tran cua pool BM25: {evaluator.ceiling:.4f}")

    if arguments.baseline_only:
        model = CrossEncoder(BASE, revision=BASE_REVISION, num_labels=1, max_length=512)
        metrics = evaluate(model, evaluator)
        print("chua train :", {k: round(v, 4) for k, v in metrics.items()})
        return 0

    groups = grouped_pairs(arguments.pairs)
    sizes = collections.Counter(len(g["negatives"]) for g in groups.values())
    print(f"train: {len(groups)} cau · {sum(len(g['positives']) for g in groups.values())} duong · "
          f"{sum(len(g['negatives']) for g in groups.values())} am · am moi cau {dict(sorted(sizes.items()))}")

    model = CrossEncoder(BASE, revision=BASE_REVISION, num_labels=1, max_length=512)
    untrained = evaluate(model, evaluator)
    del model; torch.cuda.empty_cache()
    print(f"\nchua train: acc@1 {untrained['dev_acc@1']:.4f} · mrr {untrained['dev_mrr']:.4f}\n")

    names = DEFAULT_SWEEP if arguments.loss == ["all"] else arguments.loss
    results = []
    for name in names:
        print(f"--- {name} ---", flush=True)
        try:
            results.append(run(name, groups, evaluator, arguments))
        except Exception as error:                      # a loss that will not fit is a result too
            print(f"    LOI: {type(error).__name__}: {str(error)[:200]}", flush=True)
            results.append({"loss": name, "error": f"{type(error).__name__}: {error}"})
            torch.cuda.empty_cache()
            continue
        row = results[-1]
        print(f"    acc@1 {row['dev_acc@1']:.4f} ({row['dev_acc@1'] - untrained['dev_acc@1']:+.4f}) · "
              f"mrr {row['dev_mrr']:.4f} · {row['train_seconds']}s · {row['peak_vram_mib']} MiB", flush=True)

    report = {"created_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "base": BASE, "base_revision": BASE_REVISION,
              "seed": SEED, "dev_queries": len(pool), "pool_ceiling": round(evaluator.ceiling, 4),
              "pairs_file": arguments.pairs,
              "untrained": {k: round(v, 4) for k, v in untrained.items()}, "runs": results,
              "mining": json.loads((OUT / "mining_manifest.json").read_text(encoding="utf-8"))}
    path = OUT / f"loss_comparison_{arguments.tag}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\n{'ham mat mat':34}{'acc@1':>8}{'Δ':>9}{'acc@3':>8}{'mrr':>8}{'giay':>7}{'MiB':>7}")
    print(f"{'chua train':34}{untrained['dev_acc@1']:>8.4f}{'':>9}{untrained['dev_acc@3']:>8.4f}{untrained['dev_mrr']:>8.4f}")
    for row in sorted((r for r in results if "error" not in r), key=lambda r: -r["dev_acc@1"]):
        print(f"{row['loss']:34}{row['dev_acc@1']:>8.4f}{row['dev_acc@1'] - untrained['dev_acc@1']:>+9.4f}"
              f"{row['dev_acc@3']:>8.4f}{row['dev_mrr']:>8.4f}{row['train_seconds']:>7}{row['peak_vram_mib']:>7}")
    for row in (r for r in results if "error" in r):
        print(f"{row['loss']:34}{'LOI':>8}  {row['error'][:70]}")
    print(f"\nbao cao -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
