"""build_embedding_model: record on the first build, verify on every later one (ticket 13).

No network, no Ollama, no llama.cpp: the checkpoint is a directory of small files and
the converter a ten-line script that writes a GGUF-shaped file derived from them, so a
changed source really changes the output. What is locked: --dry-run writes nothing;
the first build writes the Modelfile and export.json and prints the registry line; a
pinned build that matches passes and one that does not leaves nothing behind; a source
that changed since export.json is refused before anything converts; `ollama` is never run.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import build_embedding_model as build

FAKE_CONVERTER = '''
import hashlib, sys
from pathlib import Path
checkpoint, outfile = Path(sys.argv[1]), Path(sys.argv[sys.argv.index("--outfile") + 1])
outtype = sys.argv[sys.argv.index("--outtype") + 1]
digest = hashlib.sha256(outtype.encode())
for path in sorted(checkpoint.rglob("*")):
    if path.is_file():
        digest.update(path.relative_to(checkpoint).as_posix().encode() + path.read_bytes())
outfile.write_bytes(b"GGUF" + digest.digest())
'''


@pytest.fixture
def setup(tmp_path, monkeypatch):
    checkpoint = tmp_path / "e5-snapshot"
    for name in build.SOURCE_FILES:
        (checkpoint / name).parent.mkdir(parents=True, exist_ok=True)
        (checkpoint / name).write_text(f"fake {name}", encoding="utf-8")
    converter = tmp_path / "llama.cpp" / "convert_hf_to_gguf.py"
    converter.parent.mkdir()
    converter.write_text(FAKE_CONVERTER, encoding="utf-8")
    modelfile = tmp_path / "models" / "embedding-e5l-v1" / "Modelfile"
    commands: list[list[str]] = []
    real_run = subprocess.run

    def run(command, *args, **kwargs):
        commands.append([str(part) for part in command])
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(build.subprocess, "run", run)

    def go(pinned: str | None = None, dry_run: bool = False) -> int:
        return build.build(checkpoint, converter, python=sys.executable, revision="abc123", modelfile=modelfile,
                           tag="local-ai/multilingual-e5-large:q8", pinned_gguf=pinned, dry_run=dry_run)

    return {"checkpoint": checkpoint, "modelfile": modelfile, "gguf": modelfile.parent / build.GGUF_NAME,
            "record": modelfile.parent / "export.json", "commands": commands, "go": go}


def conversions(commands: list[list[str]]) -> int:
    return sum(1 for command in commands if command[1:2] and command[1].endswith("convert_hf_to_gguf.py"))


def test_a_dry_run_writes_nothing_and_runs_nothing(setup, capsys):
    assert setup["go"](dry_run=True) == 0
    assert not setup["modelfile"].parent.exists()
    assert setup["commands"] == []
    out = capsys.readouterr().out
    assert "--outtype q8_0" in out and "ollama create local-ai/multilingual-e5-large:q8" in out


def test_a_checkpoint_missing_a_file_is_refused_before_anything_runs(setup):
    (setup["checkpoint"] / "1_Pooling" / "config.json").unlink()
    with pytest.raises(SystemExit, match="1_Pooling/config.json"):
        setup["go"]()
    assert setup["commands"] == []


def test_the_first_build_records_what_it_was_built_from(setup, capsys):
    assert setup["go"]() == 0
    record = json.loads(setup["record"].read_text(encoding="utf-8"))
    written = build.sha256(setup["gguf"])

    assert record["gguf_sha256"] == written and record["revision"] == "abc123" and record["outtype"] == "q8_0"
    assert set(record["sources"]) == set(build.SOURCE_FILES)
    assert setup["modelfile"].read_text(encoding="utf-8").splitlines()[-1] == f"FROM ./{build.GGUF_NAME}"
    out = capsys.readouterr().out
    assert f"ollama.gguf_sha256: {written}" in out
    assert "ollama create local-ai/multilingual-e5-large:q8" in out
    assert not any(command[0] == "ollama" for command in setup["commands"]), "the build must print `ollama create`, not run it"


def test_a_build_matching_the_registry_pin_passes(setup):
    setup["go"]()
    pin = build.sha256(setup["gguf"])
    setup["record"].unlink()
    assert setup["go"](pinned=pin) == 0


def test_a_build_that_misses_the_registry_pin_leaves_nothing_behind(setup):
    with pytest.raises(SystemExit, match="pinned 0{64}"):
        setup["go"](pinned="0" * 64)
    assert not setup["gguf"].exists() and not setup["modelfile"].exists() and not setup["record"].exists()


def test_a_source_that_changed_since_the_record_is_refused_before_converting(setup):
    setup["go"]()
    before = conversions(setup["commands"])
    (setup["checkpoint"] / "model.safetensors").write_text("different weights", encoding="utf-8")

    with pytest.raises(SystemExit, match="model.safetensors"):
        setup["go"]()
    assert conversions(setup["commands"]) == before
