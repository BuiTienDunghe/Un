"""Build embedding-e5l-v1 (local-ai/multilingual-e5-large:q8) from a downloaded HF checkpoint.

    cd backend && python -m scripts.build_embedding_model \\
        --checkpoint <dir from huggingface-cli download intfloat/multilingual-e5-large> \\
        --converter <llama.cpp checkout>/convert_hf_to_gguf.py [--python <interpreter>] [--dry-run]

Converts the checkpoint to a Q8_0 GGUF with llama.cpp's converter, writes the Modelfile
beside it, and prints the `ollama create` command — it does not run it, and it never
downloads anything: the checkpoint and the converter are inputs.

Both ends are pinned, as in build_ocr_model.py, but this model has no measured build to
pin against yet, so the first build RECORDS and every later one VERIFIES — the shape of
training/reranker/export_checkpoint.py --record and its tracked export.json:

  - first build (the registry's gguf_sha256 is null): hash every source file, convert,
    hash the GGUF, and write export.json beside the Modelfile — repo, revision, source
    hashes, converter commit, interpreter, outtype, GGUF hash. Paste the printed
    `gguf_sha256:` line into model_versions.yaml; `--check` then holds the registry to it.
  - every later build: a source file, the converter commit or the outtype that differs
    from export.json is refused BEFORE converting, and a GGUF whose hash differs from the
    registry's pin is deleted. A different checkpoint or converter cannot quietly produce
    a model the registry then vouches for.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HF_REPO = "intfloat/multilingual-e5-large"
VERSION_ID = "embedding-e5l-v1"
OUTTYPE = "q8_0"
GGUF_NAME = "multilingual-e5-large-q8_0.gguf"
# What the converter reads for an XLM-RoBERTa checkpoint: weights, config, the
# SentencePiece vocabulary and the sentence-transformers pooling files (e5 is
# mean-pooled; without them the GGUF would not say so). To be confirmed against
# convert_hf_to_gguf.py at the first build — written here from the repo layout.
SOURCE_FILES = (
    "config.json",
    "model.safetensors",
    "sentencepiece.bpe.model",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "modules.json",
    "1_Pooling/config.json",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 24), b""):
            digest.update(block)
    return digest.hexdigest()


def converter_commit(converter: Path) -> str | None:
    """llama.cpp's HEAD when the converter sits at the root of a checkout, else None."""
    def git(*args: str) -> str | None:
        try:
            result = subprocess.run(["git", "-C", str(converter.parent), *args], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    top = git("rev-parse", "--show-toplevel")
    if top is None or Path(top).resolve() != converter.parent.resolve():
        return None
    return git("rev-parse", "HEAD")


def modelfile_text() -> str:
    return "\n".join((
        f"# {VERSION_ID} — {HF_REPO}, {OUTTYPE.upper()}, served through Ollama's embed endpoint.",
        "#",
        "# Built by  cd backend && python -m scripts.build_embedding_model --checkpoint <dir> --converter <convert_hf_to_gguf.py>",
        f"# which writes {GGUF_NAME} beside this file (gitignored) and export.json (tracked:",
        "# what it was built from). The registry pins the GGUF's sha256; e5 needs \"query: \" /",
        "# \"passage: \" on each side, which the registry's config carries, not this file.",
        f"FROM ./{GGUF_NAME}",
        "",
    ))


def build(
    checkpoint: Path,
    converter: Path,
    *,
    python: str,
    revision: str | None,
    modelfile: Path,
    tag: str,
    pinned_gguf: str | None,
    dry_run: bool,
) -> int:
    missing = [name for name in SOURCE_FILES if not (checkpoint / name).is_file()]
    if missing:
        raise SystemExit(f"{checkpoint}: missing {', '.join(missing)} — not the {HF_REPO} checkpoint layout")
    if not converter.is_file():
        raise SystemExit(f"converter not found: {converter}")
    target = modelfile.parent / GGUF_NAME
    record_path = modelfile.parent / "export.json"
    command = [python, str(converter), str(checkpoint), "--outfile", str(target), "--outtype", OUTTYPE]
    create = f'ollama create {tag} -f "{modelfile}"'

    if dry_run:
        print("dry run: nothing hashed, converted or written")
        print("sources  " + ", ".join(SOURCE_FILES))
        print("convert  " + subprocess.list2cmdline(command))
        print(f"gguf     {target}  (registry pin: {pinned_gguf or 'none yet: first build records it'})")
        print(f"modelfile {modelfile}\n{modelfile_text()}")
        print(f"then     {create}")
        return 0

    sources = {name: sha256(checkpoint / name) for name in SOURCE_FILES}
    commit = converter_commit(converter)
    recorded = json.loads(record_path.read_text(encoding="utf-8")) if record_path.is_file() else None
    if recorded is not None:
        drift = [name for name in SOURCE_FILES if recorded.get("sources", {}).get(name) != sources[name]]
        if drift:
            raise SystemExit(f"source differs from export.json: {', '.join(drift)} — a different checkpoint; nothing was converted")
        if recorded.get("converter_commit") != commit or recorded.get("outtype") != OUTTYPE:
            raise SystemExit(f"converter {commit} / outtype {OUTTYPE} differ from export.json ({recorded.get('converter_commit')} / {recorded.get('outtype')}); nothing was converted")

    modelfile.parent.mkdir(parents=True, exist_ok=True)
    print("convert  " + subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, check=True)
    written = sha256(target)
    expected = pinned_gguf or (recorded or {}).get("gguf_sha256")
    if expected is not None and written != expected:
        target.unlink(missing_ok=True)
        raise SystemExit(f"wrote sha256 {written}, pinned {expected}; the GGUF was deleted and nothing else written")

    modelfile.write_text(modelfile_text(), encoding="utf-8", newline="\n")
    record = {
        "version_id": VERSION_ID,
        "hf_repo": HF_REPO,
        "revision": revision,
        "sources": sources,
        "converter_commit": commit,
        "python": python,
        "outtype": OUTTYPE,
        "gguf_sha256": written,
    }
    record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"gguf     {target} sha256 {written}")
    if pinned_gguf is None:
        print(f"first build: set roles.embedding {VERSION_ID} ollama.gguf_sha256: {written}  (model_versions.yaml), then --check")
    print(f"then     {create}")
    return 0


def main() -> int:
    from app.config.model_registry import load_registry

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--checkpoint", type=Path, required=True, help=f"local snapshot of {HF_REPO}")
    parser.add_argument("--converter", type=Path, required=True, help="llama.cpp's convert_hf_to_gguf.py")
    parser.add_argument("--python", default=sys.executable, help="interpreter for the converter (needs torch, transformers, gguf-py); recorded")
    parser.add_argument("--revision", default=None, help="the HF commit the checkpoint was downloaded at; recorded")
    parser.add_argument("--dry-run", action="store_true", help="check the inputs and print the plan; write nothing")
    args = parser.parse_args()

    record = load_registry().get("embedding", VERSION_ID)
    if record.ollama.modelfile is None:
        raise SystemExit(f"{VERSION_ID}: the registry names no ollama.modelfile")
    return build(
        args.checkpoint, args.converter,
        python=args.python, revision=args.revision,
        modelfile=record.ollama.modelfile, tag=str(record.config["name"]),
        pinned_gguf=record.ollama.gguf_sha256, dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
