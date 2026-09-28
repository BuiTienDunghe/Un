"""Turn a trained checkpoint into a registry version the production runtime can load.

Two runtimes, on purpose. Training happens under `sentence-transformers` 5.7.0; the API
serves under 3.4.1 (`pyproject.toml` pins `<4.0`). A 5.x export loads under 3.4.1 but its
`config.json` carries no `sbert_ce_default_activation_function`, so 3.4.1 falls back to
**Sigmoid** and every score saturates at logit >= 17 — a model that loads, runs, and
ranks by a flattened scale. `.scratch/reranker-finetune/spec.md` condition 6 exists for
exactly this: "a checkpoint that only loads in the trainer is not a shippable model".

So the two halves run in different environments and must agree:

    .venv-train  python -m training.reranker.export_checkpoint --record <dir>
                 scores the registry's probe pairs under 5.7.0, hashes the weights AS
                 WRITTEN (re-saving changes bytes even with identical tensors) and writes
                 export.json — the file `--check` compares the registry record against.

    .venv        python -m training.reranker.export_checkpoint --verify <dir>
                 loads under 3.4.1 the way the registry loader will (local_files_only,
                 activation forced from export.json), re-scores the same pairs, and fails
                 when any score moves by more than the tolerance.

The probe pairs are reranker-v0's, taken from the registry rather than invented here, so
a candidate and the model it must beat are measured on the same three questions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = PROJECT_ROOT / "backend" / "app" / "config" / "model_versions.yaml"
TOLERANCE = 0.05


def probe_pairs() -> list[list[str]]:
    import yaml
    document = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    for version in document["roles"]["reranker"]["versions"]:
        pairs = (version.get("probe") or {}).get("pairs")
        if pairs:
            return [list(pair) for pair in pairs]
    raise SystemExit("khong tim thay probe.pairs nao trong registry")


def git_sha() -> str | None:
    try:
        return subprocess.run(["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=20).stdout.strip() or None
    except Exception:
        return None


def weights_digest(directory: Path) -> tuple[str, str]:
    for name in ("model.safetensors", "pytorch_model.bin"):
        candidate = directory / name
        if candidate.exists():
            return name, hashlib.sha256(candidate.read_bytes()).hexdigest()
    raise SystemExit(f"khong thay trong so trong {directory}")


def load(directory: Path, *, activation: str | None, local_only: bool):
    import torch
    from sentence_transformers import CrossEncoder
    kwargs: dict[str, object] = {"max_length": 512}
    if local_only:
        kwargs["local_files_only"] = True
    if activation:
        kwargs["default_activation_function"] = {"identity": torch.nn.Identity(),
                                                 "sigmoid": torch.nn.Sigmoid()}[activation]
    return CrossEncoder(str(directory), **kwargs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--record", action="store_true", help="Run under .venv-train (sentence-transformers 5.x).")
    mode.add_argument("--verify", action="store_true", help="Run under .venv (the production runtime).")
    parser.add_argument("--activation", default="identity", choices=["identity", "sigmoid"])
    parser.add_argument("--train-data", type=Path,
                        default=PROJECT_ROOT / "data" / "evaluation" / "reranker_v1" / "train_pairs.jsonl")
    arguments = parser.parse_args()

    directory = arguments.directory if arguments.directory.is_absolute() else PROJECT_ROOT / arguments.directory
    if not directory.is_dir():
        raise SystemExit(f"khong co thu muc {directory}")
    pairs = probe_pairs()
    export_path = directory / "export.json"

    import sentence_transformers as st
    major = int(st.__version__.split(".")[0])

    if arguments.record:
        if major < 4:
            raise SystemExit(f"--record phai chay trong .venv-train; day la sentence-transformers {st.__version__}")
        model = load(directory, activation=arguments.activation, local_only=True)
        scores = [round(float(s), 4) for s in model.predict(pairs, convert_to_numpy=True)]
        name, digest = weights_digest(directory)
        payload = {
            "activation_fn": arguments.activation,
            "probe_pairs": pairs,
            "scores": scores,
            "tolerance": TOLERANCE,
            "digest_file": name,
            "model_safetensors_sha256": digest,
            "exported_with": f"sentence-transformers=={st.__version__}",
            "base": "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
            "base_revision": "1427fd652930e4ba29e8149678df786c240d8825",
            "git_sha": git_sha(),
            "train_data_sha256": hashlib.sha256(arguments.train_data.read_bytes()).hexdigest()
            if arguments.train_data.exists() else None,
        }
        export_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"ghi {export_path}")
        print(f"  activation {arguments.activation} · {name} sha256 {digest[:16]}…")
        print(f"  diem probe (5.x): {scores}")
        print("\nDan vao registry roles.reranker.versions[<id>]:")
        print(f"  digest: {{file: {name}, sha256: {digest}}}")
        print(f"  probe:  {{scores: {scores}, tolerance: {TOLERANCE}}}")
        return 0

    if major >= 4:
        raise SystemExit(f"--verify phai chay trong .venv (runtime san pham); day la {st.__version__}")
    if not export_path.exists():
        raise SystemExit(f"chua co {export_path}; chay --record trong .venv-train truoc")
    recorded = json.loads(export_path.read_text(encoding="utf-8"))

    name, digest = weights_digest(directory)
    if digest != recorded["model_safetensors_sha256"]:
        raise SystemExit(f"trong so da doi sau khi xuat: {digest[:16]}… != {recorded['model_safetensors_sha256'][:16]}…")

    model = load(directory, activation=recorded["activation_fn"], local_only=True)
    scores = [float(s) for s in model.predict([list(p) for p in recorded["probe_pairs"]], convert_to_numpy=True)]
    tolerance = float(recorded.get("tolerance", TOLERANCE))
    drift = [abs(a - b) for a, b in zip(scores, recorded["scores"])]
    print(f"sentence-transformers {st.__version__} · activation {recorded['activation_fn']}")
    print(f"  ghi khi xuat : {[round(s, 4) for s in recorded['scores']]}")
    print(f"  doc lai      : {[round(s, 4) for s in scores]}")
    print(f"  lech lon nhat: {max(drift):.4f} (nguong {tolerance})")
    window = getattr(model, "max_length", None)
    labels = getattr(getattr(model, "config", None), "num_labels", None)
    print(f"  max_length {window} · num_labels {labels}")
    if max(drift) > tolerance:
        raise SystemExit("LECH QUA NGUONG: checkpoint nay khong nap dung duoi runtime san pham")
    if window != 512 or labels != 1:
        raise SystemExit(f"cua so hoac dau ra khong nhu ghi trong registry: max_length={window}, num_labels={labels}")
    print("\nOK — nap duoc duoi runtime san pham, diem trung khop trong nguong.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
