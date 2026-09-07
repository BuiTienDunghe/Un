"""docker-compose.yml and the model registry (design §4 "Docker workers").

A compose worker reads the registry baked into its image; the only per-container
inputs are the pass-throughs below. Every one of them must arrive EMPTY unless the
operator's shell says otherwise: a non-empty default would pin every container to
one tag or version forever, silently overriding the file's `active` pointer.
Settings maps "" to "unset" (the before-validator), which is what `${X:-}` sends.
"""
from __future__ import annotations

import yaml

from app.config.model_registry import PROJECT_ROOT

COMPOSE = PROJECT_ROOT / "docker-compose.yml"
WORKERS = ("worker-ocr", "worker-index", "worker-memory")
PINS = ("MODEL_VERSION_EXTRACTOR", "MODEL_VERSION_VERIFIER", "MODEL_VERSION_EMBEDDING")


def services() -> dict[str, dict]:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]


def environment(service: dict) -> dict[str, str]:
    block = service.get("environment") or {}
    # Compose accepts a mapping or a list of KEY=VALUE strings; the file uses the
    # mapping form, but the rule must hold whichever shape a future edit picks.
    if isinstance(block, list):
        return dict(item.split("=", 1) for item in block)
    return {str(key): str(value) for key, value in block.items()}


def test_no_model_or_version_line_carries_a_non_empty_default():
    offenders = []
    for name, service in services().items():
        for key, value in environment(service).items():
            if key.endswith("_MODEL") or key.startswith("MODEL_VERSION_"):
                if value != f"${{{key}:-}}":
                    offenders.append(f"{name}.{key}={value}")
    assert offenders == [], "a compose default would pin a model for every container: " + ", ".join(offenders)


def test_the_three_workers_pass_every_registry_pin_through_empty():
    for worker in WORKERS:
        env = environment(services()[worker])
        for pin in PINS:
            assert env.get(pin) == f"${{{pin}:-}}", f"{worker} must pass {pin} through empty"
    # The ad-hoc tag pin lost its qwen3.5:9b default with the registry: unset =
    # follow roles.extractor.active.
    assert environment(services()["worker-memory"])["DISCORD_MEMORY_EXTRACTOR_MODEL"] == "${DISCORD_MEMORY_EXTRACTOR_MODEL:-}"


def test_an_empty_pass_through_is_unset_for_settings(monkeypatch):
    """What `${X:-}` delivers is "", and Settings must read that as no pin at all."""
    from app.config.settings import Settings

    for key in (*PINS, "DISCORD_MEMORY_EXTRACTOR_MODEL"):
        monkeypatch.setenv(key, "")
    settings = Settings()
    assert settings.model_version_extractor is None
    assert settings.model_version_verifier is None
    assert settings.model_version_embedding is None
    assert settings.discord_memory_extractor_model is None
