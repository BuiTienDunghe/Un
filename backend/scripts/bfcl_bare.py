"""The bare arm: BFCL's own inference loop straight to Qwen 9B, no Ún harness. Runs in bfcl-venv.

    C:/Users/dungbt06/tools/bfcl-venv/Scripts/python.exe backend/scripts/bfcl_bare.py <run_dir>
    C:/Users/dungbt06/tools/bfcl-venv/Scripts/python.exe backend/scripts/bfcl_score.py <run_dir> --model-dir qwen-bare-ollama

scripts.bfcl_run measures the model inside Ún's agent loop. This measures the same model on the
same 33 ids through BFCL's own OpenAICompletionsHandler (the FC loop the leaderboard uses), so the
difference between the two is what the harness adds or costs. The model is reached through
Ollama's OpenAI endpoint. Three things are set to match the harness arm, and nothing else:

- context 16 384 and seed 42: the endpoint ignores `options`, so they live in an Ollama model made
  from qwen3.5:9b (ALIAS; same weights and template, only those two parameters added);
- thinking off: `reasoning_effort: "none"` on every request (the harness arm sends think=false);
- the model is unloaded before each task, as the harness arm's --unload-between-tasks.

Temperature 0 goes through BFCL's own --temperature. What the bare loop has that the harness does
not is the point of the comparison and is not removed: up to 20 rounds per turn (harness 3), the
earlier turns' tool calls and results carried to the next turn (harness: text only), no
AGENT_GUIDE, no answer check, no figure check.

Not written to import `app`: it must run in an environment that has only BFCL.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REGISTRY = "qwen-bare-ollama"
ALIAS = "un-bare-qwen9b"
BASE_MODEL = "qwen3.5:9b"
ALIAS_PARAMETERS = {"num_ctx": 16384, "seed": 42}
OLLAMA = "http://localhost:11434"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
IDS_PATH = PROJECT_ROOT / "data" / "benchmarks" / "bfcl" / "ids_v1.json"
CLONE_COMMIT = "6ea5797"


def ollama(path: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(OLLAMA + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=600) as response:
        return json.loads(response.read() or b"{}")


def unload() -> None:
    ollama("/api/generate", {"model": ALIAS, "keep_alive": 0})


def make_alias() -> dict:
    """Create (or recreate, idempotent) the alias and return what Ollama says it is."""
    ollama("/api/create", {"model": ALIAS, "from": BASE_MODEL, "parameters": ALIAS_PARAMETERS, "stream": False})
    shown = ollama("/api/show", {"model": ALIAS})
    return {"parameters": shown.get("parameters", ""), "base_digest": digest_of(BASE_MODEL), "alias_digest": digest_of(ALIAS)}


def digest_of(name: str) -> str:
    for model in ollama("/api/tags").get("models", []):
        if model["name"] in (name, f"{name}:latest"):
            return model["digest"]
    return ""


def loaded_context() -> int | None:
    for model in ollama("/api/ps").get("models", []):
        if model["name"].startswith(ALIAS):
            return model.get("context_length")
    return None


def register() -> None:
    from bfcl_eval.constants.model_config import MODEL_CONFIG_MAPPING, ModelConfig
    from bfcl_eval.model_handler.api_inference.openai_completion import OpenAICompletionsHandler

    class BareOllamaHandler(OpenAICompletionsHandler):
        def generate_with_backoff(self, **kwargs):
            kwargs["reasoning_effort"] = "none"
            return super().generate_with_backoff(**kwargs)

        def inference(self, test_entry, include_input_log, exclude_state_log):
            unload()
            return super().inference(test_entry, include_input_log, exclude_state_log)

    MODEL_CONFIG_MAPPING[REGISTRY] = ModelConfig(
        model_name=ALIAS,
        display_name="Qwen3.5 9B bare (Ollama, BFCL's own loop)",
        url="https://ollama.com/library/qwen3.5",
        org="local-ai-core",
        license="n/a",
        model_handler=BareOllamaHandler,
        input_price=None,
        output_price=None,
        is_fc_model=True,
        underscore_to_dot=True,
    )


def preflight() -> int | None:
    """One tiny request through the very endpoint, then the context Ollama loaded it with."""
    from openai import OpenAI

    client = OpenAI(base_url=os.environ["OPENAI_BASE_URL"], api_key=os.environ["OPENAI_API_KEY"])
    client.chat.completions.create(model=ALIAS, messages=[{"role": "user", "content": "ok"}], temperature=0,
                                   reasoning_effort="none", max_tokens=1)
    context = loaded_context()
    unload()
    return context


def gpu() -> str:
    try:
        return subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu,utilization.gpu,memory.used",
                               "--format=csv,noheader"], capture_output=True, text=True, timeout=20).stdout.strip()
    except OSError:
        return ""


def git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, capture_output=True, text=True).stdout.strip()


def main(argv: list[str] | None = None) -> int:
    if not sys.flags.utf8_mode and argv is None:
        return subprocess.run([sys.executable, "-X", "utf8", *sys.argv]).returncode
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--ids", type=Path, default=IDS_PATH, help="{category: [ids]}, as BFCL's test_case_ids_to_generate.json")
    args = parser.parse_args(argv)
    run_dir = args.run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    os.environ["BFCL_PROJECT_ROOT"] = str(run_dir / "bfcl")
    os.environ["OPENAI_BASE_URL"] = OLLAMA + "/v1"
    os.environ["OPENAI_API_KEY"] = "ollama"  # the SDK wants one; Ollama ignores it
    (run_dir / "bfcl").mkdir(exist_ok=True)
    (run_dir / "bfcl" / "test_case_ids_to_generate.json").write_text(args.ids.read_text(encoding="utf-8"), encoding="utf-8")

    alias = make_alias()
    context = preflight()
    if context != ALIAS_PARAMETERS["num_ctx"]:
        print(f"the alias loaded with context {context}, not {ALIAS_PARAMETERS['num_ctx']}: not run", file=sys.stderr)
        return 3
    manifest = {
        "arm": "bare", "runner": "bfcl-bare-v1", "commit": git_commit(), "bfcl_clone": CLONE_COMMIT,
        "ids_file": str(args.ids), "ids": {c: len(v) for c, v in json.loads(args.ids.read_text(encoding="utf-8")).items()}, "model": BASE_MODEL, "alias": ALIAS, **alias,
        "loaded_context": context, "ollama_version": ollama("/api/version").get("version"),
        "temperature": 0.0, "reasoning_effort": "none", "unload_between_tasks": True,
        "started_at": datetime.now(UTC).isoformat(), "gpu_at_start": gpu(),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    sys.dont_write_bytecode = True
    from bfcl_eval import _llm_response_generation as generation

    register()
    sys.argv = ["bfcl", "--model", REGISTRY, "--temperature", "0", "--run-ids", "--include-input-log",
                "--num-threads", "1", "--result-dir", str(run_dir / "result")]
    generation.main(generation.get_args())
    unload()
    manifest["finished_at"] = datetime.now(UTC).isoformat()
    manifest["gpu_at_end"] = gpu()
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
