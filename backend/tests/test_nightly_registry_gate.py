"""nightly_eval and the model registry: exit 94 and the stripped pins (design §4).

Pure functions only — the nightly's process management is exercised by the
Scheduled Task, not here. What is locked: which /models views the nightly refuses
to grade, what its ATTENTION text says, and that no MODEL_VERSION_* pin from the
task's shell can reach the lab API.
"""
from __future__ import annotations

from scripts.nightly_eval import lab_environment, registry_verdict


def row(version: str, **overrides) -> dict:
    """One /models.registry row: `version` is the pointer, served as itself unless overridden."""
    base = {"active": version, "requested": version, "loaded": version, "source": "registry", "status": "active",
            "reason": None, "verified": True, "name": version, "digest": None, "fallback": False}
    return {**base, **overrides}


def shipped() -> dict:
    return {
        "registry": {
            "general": row("general-v0"), "condenser": row("condenser-v0", loaded=None, status="off"), "embedding": row("embedding-v0"),
            "vision": row("vision-v0", active=None, requested=None, loaded=None, status="unconfigured"),
            "ocr": row("ocr-v0"), "reranker": row("reranker-v0"),
            "extractor": row("extractor-v0", loaded=None, status="off"), "verifier": row("verifier-v0", loaded=None, status="off"),
        },
        "rag": {"contextual_retrieval": True, "reranker": True, "retrieval_mode": "hybrid"},
    }


def test_the_shipped_configuration_is_graded():
    assert registry_verdict(shipped()) is None


def test_off_and_unconfigured_roles_are_decisions_even_from_a_pin():
    models = shipped()
    # An off role pinned by an ad-hoc tag never serves; it must not block the night.
    models["registry"]["extractor"] = row("env:qwen3.5:9b", source="env_tag", loaded=None, status="off")
    assert registry_verdict(models) is None


def test_a_fallback_role_refuses_with_the_reason_and_the_view():
    models = shipped()
    models["registry"]["reranker"] = row("reranker-d2-v1", loaded="reranker-v0", status="fallback", fallback=True,
                                         reason="reranker-d2-v1 load: no weights; serving reranker-v0")
    text = registry_verdict(models)
    assert text is not None and text.startswith("Refusing to grade")
    assert "reranker: fallback — reranker-d2-v1 load: no weights; serving reranker-v0" in text
    assert "reranker: requested=reranker-d2-v1 loaded=reranker-v0 source=registry status=fallback fallback=True" in text
    assert text.splitlines()[-1].startswith("rag: ")
    assert len(text.splitlines()) <= 40, "finish() keeps the last 40 lines; the whole verdict must fit"


def test_a_pinned_serving_role_refuses_even_when_it_serves_its_pointer():
    models = shipped()
    models["registry"]["embedding"] = row("embedding-e5l-v1", source="env")
    text = registry_verdict(models)
    assert text is not None and "embedding: source=env" in text


def test_degraded_and_incomplete_embedding_refuse_like_a_fallback():
    for status in ("degraded", "incomplete", "missing", "disabled"):
        models = shipped()
        models["registry"]["embedding"] = row("embedding-v0", status=status, fallback=True, reason=f"{status} for the test")
        assert f"embedding: {status}" in (registry_verdict(models) or ""), status


def test_a_shipped_flag_that_is_off_refuses():
    for flag in ("reranker", "contextual_retrieval"):
        models = shipped()
        models["rag"][flag] = False
        text = registry_verdict(models)
        assert text is not None and f"rag.{flag} is False" in text, flag


def test_a_server_without_a_registry_refuses():
    text = registry_verdict({"models": {}, "tokenizer_version": "pyvi-0.1.1"})
    assert text is not None and "no model registry" in text


def test_lab_environment_drops_every_pin_and_gives_the_lab_api_its_own_log_dir():
    environ = {"PATH": "x", "MODEL_VERSION_RERANKER": "reranker-d2-v1", "MODEL_VERSION_EMBEDDING": "embedding-e5l-v1",
               "MODEL_STARTUP_PROBES": "true", "DATABASE_URL": "postgresql+psycopg://x",
               "DISCORD_MEMORY_EXTRACTOR_MODEL": "local-ai/extractor-student:d2", "LOG_DIR": "data/logs"}
    assert lab_environment(environ) == {
        "PATH": "x", "MODEL_STARTUP_PROBES": "true", "DATABASE_URL": "postgresql+psycopg://x",
        # The D2 tag pin (.env or shell) never reaches the lab API: "" reads as unset.
        "DISCORD_MEMORY_EXTRACTOR_MODEL": "", "DISCORD_MEMORY_VERIFIER_MODEL": "",
        # Its ATTENTION marker and app log live apart from production's data/logs.
        "LOG_DIR": "data/logs/lab",
    }


def test_the_lab_env_reads_as_no_tag_pin_and_a_lab_log_dir_through_settings(monkeypatch):
    """What lab_environment sets has to survive pydantic-settings: an empty tag pin outranks
    the .env line and maps to None (no env_tag row, so registry_verdict has nothing to refuse
    over a role no retrieval number depends on), and LOG_DIR lands in Settings.logs_path,
    where write_attention_marker writes and deletes the marker."""
    from app.config.model_registry import PROJECT_ROOT, overrides_from_settings
    from app.config.settings import Settings

    for key, value in lab_environment({"DISCORD_MEMORY_EXTRACTOR_MODEL": "local-ai/extractor-student:d2"}).items():
        monkeypatch.setenv(key, value)
    settings = Settings(database_url="postgresql+psycopg://user:password@localhost/test", _env_file=None)
    assert settings.discord_memory_extractor_model is None and settings.discord_memory_verifier_model is None
    assert overrides_from_settings(settings).raw_tags == {}
    assert settings.logs_path == PROJECT_ROOT / "data" / "logs" / "lab"
