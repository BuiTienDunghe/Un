"""Record what every evaluation artifact IS, so a later leak check has an authority.

A number is only worth putting on a CV if the set it was measured on is known
not to overlap the set the model was trained on. Today that is true by accident:
nothing has been trained yet. The moment the first training set is generated,
"by accident" stops being an argument, and reconstructing provenance after the
fact is exactly the kind of thing nobody manages to do honestly.

So this records provenance now, while it is still free:

  role       gate | train | dev | heldout — what the file is allowed to be used
             for. A file may hold exactly one role; the checker refuses a file
             that is both trained on and measured on.
  sha256     content hash. A fixture that changes silently invalidates every
             number ever measured against it, and the hash is what notices.
  generator  what produced the file: `human` for text a person wrote,
             otherwise the model or script that generated it.
  template   the prompt/template identifier a generator ran under. Two sets
             built by the same generator under the same template are not
             independent, no matter that their rows differ — that is the
             failure mode a held-out set is supposed to prevent and the one
             most easily fooled by "I generated 200 more".

Usage:
    python -m training.common.split_manifest --write     # from the repo root
    python -m training.common.split_manifest --check     # CI / pre-training
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = PROJECT_ROOT / "data" / "evaluation" / "split_manifest.json"

VALID_ROLES = {"gate", "train", "dev", "heldout"}

# The artifacts that exist today. Extend this list when a set is added; the
# checker fails on an entry whose file is gone, so the list cannot rot quietly.
#
# `local_ai_core_baseline.txt` is called out deliberately: it is a near-twin of
# the multidoc fixtures (the same project documentation, chunked differently),
# so a training set built from repo documentation would contaminate BOTH the
# 47-question and the 82-question evals at once.
ARTIFACTS: list[dict] = [
    {
        "path": "data/evaluation/fixtures/multidoc",
        "role": "gate",
        "generator": "human",
        "template": None,
        "note": "D1 corpus: 5 snapshotted project documents. The 82-question gate is scored against these.",
    },
    {
        "path": "data/evaluation/rag_multidoc_eval.jsonl",
        "role": "gate",
        "generator": "human",
        "template": None,
        "note": "82 questions with verbatim expected terms, written by hand against chunk text.",
    },
    {
        "path": "data/evaluation/fixtures/local_ai_core_baseline.txt",
        "role": "gate",
        "generator": "human",
        "template": None,
        "note": "Twin of the multidoc corpus (same source documentation). Contaminating one contaminates both.",
    },
    {
        "path": "data/evaluation/rag_eval.jsonl",
        "role": "gate",
        "generator": "human",
        "template": None,
        "note": "47 single-document questions, the older eval; still runnable.",
    },
    {
        "path": "data/evaluation/rag_conversation_eval.jsonl",
        "role": "gate",
        "generator": "human",
        "template": None,
        "note": "10 follow-up pairs measuring the condense step.",
    },
    {
        "path": "data/evaluation/redteam_injection.jsonl",
        "role": "gate",
        "generator": "human",
        "template": None,
        "note": "12 prompt-injection cases. Marker-scored, so leaked markers would silently inflate the defense.",
    },
    {
        "path": "data/evaluation/fixtures/redteam",
        "role": "gate",
        "generator": "human",
        "template": None,
        "note": "Trap documents carrying live injection text. Never a training source.",
    },
    {
        "path": "backend/tests/fixtures/discord_memory_extractor_benchmark_v1.json",
        "role": "gate",
        "generator": "human",
        "template": None,
        "note": "150-case extractor benchmark. This is the D2 gate: a distilled student must never train on it.",
    },
    {
        "path": "backend/tests/fixtures/discord_memory_e2e_v1.jsonl",
        "role": "gate",
        "generator": "human",
        "template": None,
        "note": "End-to-end memory pipeline eval: the P/R/forged gate a distilled student must clear.",
    },
    {
        "path": "backend/tests/fixtures/discord_memory_rule_filter_v1.json",
        "role": "gate",
        "generator": "human",
        "template": None,
        "note": "Rule-filter cases. The filter decides what the extractor ever sees, so its fixtures gate the pipeline's input.",
    },
]


def digest(path: Path) -> tuple[str, int]:
    """sha256 of a file, or of a directory's files in sorted name order."""
    hasher = hashlib.sha256()
    size = 0
    files = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
    for item in files:
        # Name goes into the hash too: renaming a fixture changes the corpus
        # even when the bytes are untouched.
        hasher.update(item.relative_to(path if path.is_dir() else path.parent).as_posix().encode())
        data = item.read_bytes()
        hasher.update(data)
        size += len(data)
    return hasher.hexdigest(), size


def build() -> dict:
    entries = []
    for artifact in ARTIFACTS:
        path = PROJECT_ROOT / artifact["path"]
        if not path.exists():
            if artifact.get("optional"):
                continue
            raise SystemExit(f"Manifest lists {artifact['path']}, which does not exist. Fix the list or restore the file.")
        if artifact["role"] not in VALID_ROLES:
            raise SystemExit(f"{artifact['path']}: role {artifact['role']!r} is not one of {sorted(VALID_ROLES)}")
        sha, size = digest(path)
        entries.append({k: v for k, v in artifact.items() if k != "optional"} | {"sha256": sha, "bytes": size, "files": sum(1 for _ in path.rglob("*") if _.is_file()) if path.is_dir() else 1})
    return {
        "note": "Provenance of every set a number is measured on. See training/common/split_manifest.py.",
        "artifacts": entries,
    }


def check() -> int:
    if not MANIFEST.exists():
        print(f"No manifest at {MANIFEST}. Run: python -m training.common.split_manifest --write")
        return 1
    recorded = {entry["path"]: entry for entry in json.loads(MANIFEST.read_text(encoding="utf-8"))["artifacts"]}
    current = {entry["path"]: entry for entry in build()["artifacts"]}
    problems: list[str] = []
    for path, entry in current.items():
        was = recorded.get(path)
        if was is None:
            problems.append(f"{path}: present now, absent from the manifest — record it before measuring against it")
        elif was["sha256"] != entry["sha256"]:
            problems.append(f"{path}: content changed (manifest {was['sha256'][:12]}…, now {entry['sha256'][:12]}…) — every number measured against it is stale")
    for path in recorded.keys() - current.keys():
        problems.append(f"{path}: in the manifest but missing on disk")
    # A set that is both trained on and measured on is the leak that needs no
    # n-gram analysis to find.
    for path, entry in recorded.items():
        if entry["role"] == "train" and path in {p for p, e in recorded.items() if e["role"] in {"gate", "heldout"}}:
            problems.append(f"{path}: declared both train and gate/heldout")
    if problems:
        print("split_manifest FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"split_manifest OK: {len(current)} artifacts, hashes match.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true", help="Record the current state as the manifest.")
    group.add_argument("--check", action="store_true", help="Fail if anything drifted from the manifest.")
    arguments = parser.parse_args()
    if arguments.write:
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {MANIFEST}")
        return 0
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
