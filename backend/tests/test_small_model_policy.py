from types import SimpleNamespace

import pytest

from app.config.model_registry import Overrides
from app.config.small_model_policy import validate_small_model_routes


def registry(name, provider="ollama"):
    return SimpleNamespace(roles={"general":object()},
        chain=lambda role, pin=None: [SimpleNamespace(name=name, provider=provider)])


@pytest.mark.parametrize("tag", ["qwen3.5:9b", "un-bare-qwen9b:latest", "renamed-model:latest", "qwen3:8b"])
def test_large_models_and_unknown_aliases_are_refused(tag):
    with pytest.raises(ValueError, match="Small-model branch refuses"):
        validate_small_model_routes(registry(tag), Overrides())


def test_only_explicit_small_local_routes_are_allowed():
    validate_small_model_routes(registry("qwen3.5:2b"), Overrides())
    validate_small_model_routes(registry("lfm3:1.7b"), Overrides())
    with pytest.raises(ValueError):
        validate_small_model_routes(registry("cloud", "anthropic"), Overrides())


def test_disabled_raw_override_cannot_smuggle_large_model():
    with pytest.raises(ValueError):
        validate_small_model_routes(registry("qwen3.5:2b"), Overrides(
            disabled_roles=frozenset({"extractor"}), raw_tags={"extractor":"qwen3.5:9b"}))


def test_refusal_happens_before_probe_construction(monkeypatch):
    from app.config.settings import Settings
    monkeypatch.setattr(Settings, "registry", lambda self: registry("qwen3.5:9b"))
    calls = []
    monkeypatch.setattr("app.config.settings.ProductionProbes", lambda *args: calls.append(args))
    settings = Settings(database_url="postgresql+psycopg://x:y@localhost/policy_test", _env_file=None,
                        model_startup_probes=True)
    with pytest.raises(ValueError):
        settings.resolve_models()
    assert calls == []
