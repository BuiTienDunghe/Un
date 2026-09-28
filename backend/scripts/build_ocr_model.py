"""Build ocr-v1 (local-ai/glm-ocr:eot-v1) from the pulled glm-ocr:latest blob.

    pip install ".[ocr-build]"            # gguf==0.19.0, once
    cd backend && python -m scripts.build_ocr_model [--keep-gguf]

Why a rebuild and not a pull: upstream glm-ocr ends its turn with <|user|>, and
lists it only in tokenizer.ggml.eos_token_ids. The llama-server runner that
Ollama 0.34.x uses for this model reads the singular eos_token_id
(<|endoftext|>), so it never saw the turn end: every page looped until Ollama
aborted with "token repeat limit reached", and the OCR role failed on every
page while ingestion silently kept the native text. Declaring the same token as
eot_token_id is what llama.cpp's own GLM converter does; nothing else changes.

Both ends are pinned. The source must be the blob the registry's ocr-v0 was
measured on, and the written file must hash to ocr-v1's ollama.gguf_sha256, so
a different upstream blob or gguf version fails here instead of producing a
model the registry would then vouch for.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

from app.config.model_registry import load_registry
from app.config.settings import get_settings

UPSTREAM_TAG = "glm-ocr:latest"
UPSTREAM_BLOB_SHA256 = "65493e1f85b9ea4ba3ed793515fde13cbdbea7d74ad2c662b566b146eab0081e"
USER_TOKEN_ID = 59253                    # '<|user|>' in the glm-ocr vocabulary
VERSION_ID = "ocr-v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 24), b""):
            digest.update(block)
    return digest.hexdigest()


def _upstream_blob(base_url: str) -> Path:
    request = urllib.request.Request(f"{base_url}/api/show", data=json.dumps({"model": UPSTREAM_TAG}).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        modelfile = json.loads(response.read())["modelfile"]
    source = next((line[5:].strip() for line in modelfile.splitlines() if line.startswith("FROM ")), None)
    if source is None:
        raise SystemExit(f"{UPSTREAM_TAG}: /api/show returned no FROM line")
    path = Path(source)
    if not path.name.endswith(UPSTREAM_BLOB_SHA256):
        raise SystemExit(f"{UPSTREAM_TAG} is {path.name}, not sha256-{UPSTREAM_BLOB_SHA256}: upstream moved, re-measure before rebuilding")
    return path


def _write_patched(source: Path, target: Path) -> None:
    try:
        import gguf
        from gguf.scripts.gguf_new_metadata import MetadataDetails, copy_with_new_metadata, get_field_data
    except ImportError as error:
        raise SystemExit('needs the optional extra: pip install ".[ocr-build]"') from error
    # The same steps as `gguf_new_metadata --special-token-by-id eot 59253`, which is
    # how the pinned gguf_sha256 was first produced.
    reader = gguf.GGUFReader(source, "r")
    tokens = get_field_data(reader, gguf.Keys.Tokenizer.LIST)
    if tokens[USER_TOKEN_ID] != "<|user|>":
        raise SystemExit(f"token {USER_TOKEN_ID} is {tokens[USER_TOKEN_ID]!r}, expected '<|user|>'")
    writer = gguf.GGUFWriter(target, arch=get_field_data(reader, gguf.Keys.General.ARCHITECTURE), endianess=reader.endianess)
    alignment = get_field_data(reader, gguf.Keys.General.ALIGNMENT)
    if alignment is not None:
        writer.data_alignment = alignment
    new_metadata = {gguf.Keys.Tokenizer.EOT_ID: MetadataDetails(gguf.GGUFValueType.UINT32, USER_TOKEN_ID, f"= {tokens[USER_TOKEN_ID]}")}
    copy_with_new_metadata(reader, writer, new_metadata, [])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep-gguf", action="store_true", help="keep the 2.2 GB file beside the Modelfile (Ollama holds its own copy)")
    args = parser.parse_args()

    settings = get_settings()
    record = load_registry().get("ocr", VERSION_ID)
    if record.ollama.modelfile is None or record.ollama.gguf_sha256 is None:
        raise SystemExit(f"{VERSION_ID}: registry has no ollama.modelfile / gguf_sha256")
    tag = str(record.config["name"])
    target = record.ollama.modelfile.parent / "glm-ocr-eot.gguf"

    source = _upstream_blob(settings.ollama_base_url.rstrip("/"))
    print(f"source {source.name}", flush=True)
    _write_patched(source, target)
    written = _sha256(target)
    if written != record.ollama.gguf_sha256:
        target.unlink(missing_ok=True)
        raise SystemExit(f"wrote sha256 {written}, registry pins {record.ollama.gguf_sha256}; nothing was created")
    print(f"gguf   {target} sha256 {written}", flush=True)
    subprocess.run(["ollama", "create", tag, "-f", str(record.ollama.modelfile)], check=True)
    if not args.keep_gguf:
        target.unlink()
    print(f"built {tag}; restart the launcher processes for the resolver to probe it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
