import os
from pathlib import Path

os.environ["DB_PATH"] = str(Path(__file__).parent / "test_local_ai_core.db")
os.environ["LOG_DIR"] = str(Path(__file__).parent / "test_logs")

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def mock_ollama(monkeypatch):
    def fake_chat(self, model, messages, options, keep_alive, think=None):
        return f"Mock response from {model}"

    monkeypatch.setattr("app.llm_clients.ollama_client.OllamaClient.chat", fake_chat)
    monkeypatch.setattr("app.llm_clients.ollama_client.OllamaClient.embed", lambda self, model, text: [0.1, 0.2, 0.3])
    monkeypatch.setattr("app.llm_clients.ollama_client.OllamaClient.healthcheck", lambda self: True)
