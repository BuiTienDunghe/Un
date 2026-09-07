"""eval_stack --model-version ROLE=ID: a pin that reaches the stack's env and nothing else."""
from __future__ import annotations

import os
import sys

import pytest

from app.config.model_registry import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from training.common.eval_stack import stack_env, version_pins  # noqa: E402


def test_version_pins_map_role_to_the_settings_variable():
    assert version_pins(["reranker=reranker-d2-v1", "Embedding=embedding-e5l-v1"]) == {
        "MODEL_VERSION_RERANKER": "reranker-d2-v1", "MODEL_VERSION_EMBEDDING": "embedding-e5l-v1",
    }
    assert version_pins(None) == {} and version_pins([]) == {}


@pytest.mark.parametrize("item", ["reranker", "=reranker-v0", "reranker=", " = "])
def test_a_malformed_pin_is_refused_before_anything_starts(item):
    with pytest.raises(SystemExit, match="ROLE=ID"):
        version_pins([item])


def test_stack_env_carries_the_pin_without_touching_this_process(monkeypatch):
    monkeypatch.delenv("MODEL_VERSION_RERANKER", raising=False)
    env = stack_env("lab", None, model_versions=["reranker=reranker-d2-v1"])
    assert env["MODEL_VERSION_RERANKER"] == "reranker-d2-v1"
    assert env["QDRANT_DOCUMENTS_COLLECTION"] == "documents_lab" and env["RAG_RERANKER_ENABLED"] == "true"
    assert "MODEL_VERSION_RERANKER" not in os.environ, "the pin belongs to the stack's env only"
    assert "MODEL_VERSION_RERANKER" not in stack_env("lab", None)


def test_stack_env_keeps_the_stacks_attention_marker_out_of_productions_log_dir(monkeypatch):
    """A candidate pinned on the stack that is rejected at warmup falls back and writes the
    ATTENTION marker; a clean stack boot deletes it. On production's data/logs either would
    lie to the morning check (invariant #6), so every profile gets a log dir of its own —
    whatever LOG_DIR the launching shell carries."""
    monkeypatch.setenv("LOG_DIR", "data/logs")
    assert stack_env("lab", None)["LOG_DIR"] == "data/logs/eval_lab"
    assert stack_env("chunkexp", None, model_versions=["reranker=reranker-d2-v1"])["LOG_DIR"] == "data/logs/eval_chunkexp"
