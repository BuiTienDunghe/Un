"""eval_stack --model-version ROLE=ID: a pin that reaches the stack's env and nothing else.
Also --collection-base NAME: one stack's documents collection base, inside its profile's namespace."""
from __future__ import annotations

import os
import sys

import pytest

from app.config.model_registry import PROJECT_ROOT

# The one sys.path patch kept on purpose. This suite runs from backend/, and
# `training` is deliberately not part of the installed package: the product never
# imports it, and from the repository root, where training runs, it already
# imports. Mapping it into pyproject.toml would put training/ into the product's
# install to save this one test a line.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config.model_registry import ModelRegistryError  # noqa: E402
from app.config.settings import Settings  # noqa: E402
from training.common.eval_stack import PROFILES, documents_collection, stack_env, version_pins  # noqa: E402


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


@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_without_a_collection_base_every_profile_keeps_its_own_collection(profile):
    assert stack_env(profile, None)["QDRANT_DOCUMENTS_COLLECTION"] == PROFILES[profile]["collection"]
    assert documents_collection(profile, PROFILES[profile]["collection"]) == PROFILES[profile]["collection"]


@pytest.mark.parametrize("base", ["documents", "documents_qi", "documents_lab_r2", "documents_drill_heldout", "documents_drill_heldoutr2", ""])
def test_a_base_outside_the_profiles_namespace_is_refused_before_anything_starts(base):
    """`documents_drill_heldout` itself is not refused for heldout but is for lab: the
    namespace is the profile's collection, so no stack can search or write production's."""
    profile = "heldout" if base != "documents_drill_heldout" else "lab"
    with pytest.raises(SystemExit, match="--collection-base"):
        documents_collection(profile, base)


def _collections_seen_by_the_stack(monkeypatch, env):
    for key in ("QDRANT_DOCUMENTS_COLLECTION", "QDRANT_MEMORIES_COLLECTION", "MODEL_VERSION_EMBEDDING"):
        monkeypatch.delenv(key, raising=False)
    for key in ("QDRANT_DOCUMENTS_COLLECTION", "MODEL_VERSION_EMBEDDING"):
        if key in env:
            monkeypatch.setenv(key, env[key])
    return Settings(_env_file=None).qdrant_collections()


@pytest.mark.parametrize("profile, base", [("heldout", "documents_drill_heldout_r2"), ("lab", "documents_lab_r2")])
def test_both_arms_of_an_embedding_ab_land_under_one_base(monkeypatch, profile, base):
    """The ticket 09 shape (m3-preregistration.md, Bổ sung 2): v0 and the qi candidate
    started with the same base search NAME and NAME_qi, i.e. two collections rebuilt
    side by side on one runtime — on the held-out drill and on the lab gate alike."""
    v0 = stack_env(profile, None, collection_base=base)
    qi = stack_env(profile, None, collection_base=base, model_versions=["embedding=embedding-v0-qi"])
    assert _collections_seen_by_the_stack(monkeypatch, v0).documents == base
    assert _collections_seen_by_the_stack(monkeypatch, qi).documents == base + "_qi"


def test_a_base_that_aliases_a_versions_suffix_is_refused_by_the_registry(monkeypatch):
    """`documents_drill_heldout_qi` is inside heldout's namespace, so the flag lets it
    through; served by v0 it would read the qi collection as v0's. The registry refuses
    that base when the API boots, which `start` prints from the log tail."""
    env = stack_env("heldout", None, collection_base="documents_drill_heldout_qi")
    with pytest.raises(ModelRegistryError, match="_qi"):
        _collections_seen_by_the_stack(monkeypatch, env)
