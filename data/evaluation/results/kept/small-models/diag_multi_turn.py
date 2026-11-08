"""Exploratory count, not preregistered (08/11, after the scores were seen): of the multi_turn_base
tasks a small model passes bare and fails in the harness, how many hit the harness's 3-round cap in
some turn, and how many needed more than 3 rounds of calls in some turn when run bare.

    .venv/Scripts/python.exe -X utf8 data/evaluation/results/kept/small-models/diag_multi_turn.py
"""
from __future__ import annotations

import json
from pathlib import Path

RUN = Path(__file__).resolve().parents[2] / "small-models-run"


def rows(path: Path) -> dict[str, dict]:
    return {r["id"]: r for r in (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())}


def result(arm: str, model: str) -> dict[str, dict]:
    return rows(next((RUN / arm / model / "multi_turn_base" / "result").rglob("*multi_turn_base_result.json")))


def failed(arm: str, model: str) -> set[str]:
    path = RUN / arm / model / "multi_turn_base" / "scores.json"
    return set(json.loads(path.read_text(encoding="utf-8"))["multi_turn_base"]["failed_ids"])


for model in ("lfm3-1-7b", "qwen3-5-2b"):
    bare, harness = result("bare", model), result("harness", model)
    lost = {i for i in bare if i not in failed("bare", model) and i in failed("harness", model)}
    bare_over3 = {i for i, r in bare.items() if any(sum(isinstance(rnd, list) for rnd in turn) > 3 for turn in r["result"])}
    capped = {i for i in lost if any(isinstance(t, dict) and t.get("stop_reason") == "max_steps"
                                     for t in harness[i].get("inference_log", []))}
    print(f"{model}: bare passes, harness fails {len(lost)}; harness hit the 3-round cap {len(capped)}; "
          f"bare needed >3 call rounds in a turn {len(lost & bare_over3)}")
