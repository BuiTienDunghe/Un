"""Score a run of scripts.bfcl_run with BFCL's own checker (ticket 42). Runs in bfcl-venv, not in Ún's.

    C:/Users/dungbt06/tools/bfcl-venv/Scripts/python.exe backend/scripts/bfcl_score.py <run_dir>

BFCL's `evaluate` refuses a model name that is not in its MODEL_CONFIG_MAPPING and imports every
vendor's handler to build that table. Rather than edit the clone or the package, this script
adds one ModelConfig for the harness at run time and calls the checker's own main() in the same
process. The handler needs only the two decoders: the FC branch of openai_completion.py, since
bfcl_run writes results in the form BFCL's FC handlers store ({name: json-arguments}). The
checker is the package installed in this venv (a copy of the clone at 6ea5797).

Everything BFCL writes goes under <run_dir>/bfcl (BFCL_PROJECT_ROOT), never next to the package.
The scores are printed and kept in <run_dir>/scores.json. They compare two versions of the
harness on this fixed set and are not to be put beside the leaderboard.

Not written to import `app`: it must run in an environment that has only BFCL.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

MODEL_DIR = "un-harness"
GROUPS = ("non_live", "multi_turn")


def categories_in(result_root: Path) -> list[str]:
    """The categories with a result file, from the file names BFCL_v4_<category>_result.json."""
    found = []
    for path in sorted((result_root / MODEL_DIR).rglob("BFCL_v4_*_result.json")):
        found.append(path.name.removeprefix("BFCL_v4_").removesuffix("_result.json"))
    return found


def register_harness() -> None:
    from bfcl_eval.constants.model_config import MODEL_CONFIG_MAPPING, ModelConfig
    from bfcl_eval.model_handler.base_handler import BaseHandler
    from bfcl_eval.model_handler.utils import convert_to_function_call

    class UnHarnessHandler(BaseHandler):
        def decode_ast(self, result, language, has_tool_call_tag):
            decoded = []
            for invoked_function in result:
                name = list(invoked_function.keys())[0]
                decoded.append({name: json.loads(invoked_function[name])})
            return decoded

        def decode_execute(self, result, has_tool_call_tag):
            return convert_to_function_call(result)

    MODEL_CONFIG_MAPPING[MODEL_DIR] = ModelConfig(
        model_name=MODEL_DIR,
        display_name="Ún harness (local, agent loop)",
        url="https://github.com/",
        org="local-ai-core",
        license="n/a",
        model_handler=UnHarnessHandler,
        input_price=None,
        output_price=None,
        is_fc_model=True,
        underscore_to_dot=True,
    )


def read_scores(score_root: Path, categories: list[str]) -> dict[str, dict[str, object]]:
    scores: dict[str, dict[str, object]] = {}
    for category in categories:
        for path in (score_root / MODEL_DIR).rglob(f"BFCL_v4_{category}_score.json"):
            header = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            failed = [json.loads(line)["id"] for line in path.read_text(encoding="utf-8").splitlines()[1:] if line.strip()]
            scores[category] = {
                "accuracy": header["accuracy"],
                "correct": header["correct_count"],
                "total": header["total_count"],
                "failed_ids": failed,
            }
    return scores


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args(argv)
    run_dir = args.run_dir.resolve()
    result_root = run_dir / "result"
    categories = categories_in(result_root)
    if not categories:
        print(f"no result files under {result_root / MODEL_DIR}", file=sys.stderr)
        return 2
    # Set before bfcl_eval is imported: its eval_config reads it, and creates the folders at import.
    os.environ["BFCL_PROJECT_ROOT"] = str(run_dir / "bfcl")
    sys.dont_write_bytecode = True
    from bfcl_eval.eval_checker import eval_runner

    register_harness()
    score_root = run_dir / "bfcl" / "score"
    eval_runner.main([MODEL_DIR], categories, str(result_root), str(score_root), partial_eval=True)
    scores = read_scores(score_root, categories)
    (run_dir / "scores.json").write_text(json.dumps(scores, ensure_ascii=False, indent=2), encoding="utf-8")
    for category, score in scores.items():
        print(f"{category:<24} {score['correct']}/{score['total']}  failed: {', '.join(score['failed_ids']) or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
