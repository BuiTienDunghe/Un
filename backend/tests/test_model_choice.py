"""Ticket 31: the Model screen picks the answer model for this machine. The pick is a file the
launcher loads as a shell pin, so the registry file, and with it every eval, stays untouched."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config.settings import get_settings
from app.services import model_choice

REPO = Path(__file__).resolve().parents[2]
REGISTRY = REPO / "backend" / "app" / "config" / "model_versions.yaml"
HAIKU = "general-haiku-v1"
QWEN = "general-v0"


@pytest.fixture
def choice_file(monkeypatch, tmp_path) -> Path:
    path = tmp_path / "data" / "model_choice.env"
    monkeypatch.setattr(model_choice, "CHOICE_PATH", path)
    return path


def versions_by_id(row: dict) -> dict[str, dict]:
    return {version["id"]: version for version in row["versions"]}


def test_nothing_picked_reads_empty(tmp_path) -> None:
    assert model_choice.read_choices(tmp_path / "absent.env") == {}


def test_a_pick_round_trips_and_can_be_dropped(tmp_path) -> None:
    path = tmp_path / "data" / "model_choice.env"
    model_choice.save_choice(path, "general", HAIKU)
    assert path.read_bytes() == b"MODEL_VERSION_GENERAL=general-haiku-v1\r\n"
    assert model_choice.read_choices(path) == {"general": HAIKU}
    model_choice.save_choice(path, "general", None)
    assert path.read_bytes() == b"MODEL_VERSION_GENERAL=\r\n"
    assert model_choice.read_choices(path) == {"general": ""}


def test_models_offers_the_switch_only_on_the_answer_role(mock_ollama, client, choice_file) -> None:
    registry = client.get("/models").json()["registry"]
    assert registry["general"]["switchable"] is True
    assert registry["general"]["chosen"] == QWEN
    versions = versions_by_id(registry["general"])
    assert versions[QWEN]["status"] == "active" and versions[QWEN]["cloud"] is False
    assert versions[HAIKU]["status"] == "candidate" and versions[HAIKU]["cloud"] is True
    for role in ("embedding", "reranker", "extractor", "ocr"):
        assert "switchable" not in registry[role] and "versions" not in registry[role]


def test_a_pick_waits_for_the_restart_and_leaves_the_registry_alone(mock_ollama, client, choice_file) -> None:
    before = REGISTRY.read_bytes()
    response = client.post("/models/general/promote", json={"version": HAIKU})
    assert response.status_code == 200
    assert model_choice.read_choices(choice_file) == {"general": HAIKU}
    assert REGISTRY.read_bytes() == before
    row = response.json()
    assert row["chosen"] == HAIKU and row["loaded"] == QWEN
    versions = versions_by_id(row)
    assert versions[HAIKU]["status"] == "pending"
    assert versions[QWEN]["status"] == "serving"
    # The pick survives into the next read of the screen.
    assert client.get("/models").json()["registry"]["general"]["chosen"] == HAIKU
    # What this process serves does not change before the restart.
    assert client.get("/models").json()["models"]["general"]["name"] != "claude-haiku-5-5"


def test_picking_the_default_or_reverting_drops_the_pick(mock_ollama, client, choice_file) -> None:
    client.post("/models/general/promote", json={"version": HAIKU})
    assert client.post("/models/general/promote", json={"version": QWEN}).status_code == 200
    assert model_choice.read_choices(choice_file) == {"general": ""}
    client.post("/models/general/promote", json={"version": HAIKU})
    row = client.post("/models/general/revert").json()
    assert model_choice.read_choices(choice_file) == {"general": ""}
    assert row["chosen"] == QWEN


def test_a_shell_pin_with_no_pick_is_not_shown_as_waiting_for_a_restart(mock_ollama, client, choice_file, monkeypatch) -> None:
    view = {"general": {"active": QWEN, "requested": HAIKU, "loaded": HAIKU, "source": "env", "fallback": False}}
    monkeypatch.setattr(client.app.state.model_registry, "registry_view", lambda: view)
    row = client.get("/models").json()["registry"]["general"]
    assert row["chosen"] == HAIKU
    assert versions_by_id(row)[HAIKU]["status"] == "active"
    assert versions_by_id(row)[QWEN]["status"] == "candidate"


@pytest.mark.parametrize(
    ("role", "version", "status", "code"),
    [
        ("nope", QWEN, 404, "MODEL_ROLE_NOT_FOUND"),
        ("general", "nope", 404, "MODEL_VERSION_NOT_FOUND"),
        ("embedding", "embedding-v0", 409, "MODEL_ROLE_NOT_SWITCHABLE"),
        ("extractor", "extractor-v0", 409, "MODEL_ROLE_NOT_SWITCHABLE"),
    ],
)
def test_a_bad_pick_changes_nothing(mock_ollama, client, choice_file, role, version, status, code) -> None:
    response = client.post(f"/models/{role}/promote", json={"version": version})
    assert response.status_code == status
    assert code in response.text
    assert not choice_file.exists()


def test_a_pick_needs_the_api_key_when_one_is_set(mock_ollama, client, choice_file, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "local_ai_api_key", "secret-key-for-this-test")
    assert client.post("/models/general/promote", json={"version": HAIKU}).status_code == 401
    assert client.post("/models/general/revert").status_code == 401
    assert client.get("/models/check").status_code == 401
    assert not choice_file.exists()


def test_check_reports_the_shipped_registry_as_valid(mock_ollama, client) -> None:
    body = client.get("/models/check").json()
    assert body["ok"] is True and body["problems"] == []
    assert isinstance(body["output"], str)


def test_the_launcher_loads_the_pick_before_anything_starts() -> None:
    launcher = (REPO / "run-local-ai-core.bat").read_text(encoding="utf-8")
    loaded = launcher.index('"data\\model_choice.env"')
    assert 'set "%%A=%%B"' in launcher
    assert loaded < launcher.index("--ollama-pull-list") < launcher.index("uvicorn app.main:app")
    assert loaded < launcher.index("scripts.memory_worker")


def test_the_pick_stays_out_of_git() -> None:
    assert "data/model_choice.env" in (REPO / ".gitignore").read_text(encoding="utf-8")
