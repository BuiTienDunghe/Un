import pytest

from app.llm_clients.ollama_client import OllamaClient
from app.services.model_router import ModelRouter


class FakeOllama(OllamaClient):
    def __init__(self):  # no HTTP setup; only the chat surface is exercised
        self.model = None
        self.options = None
        self.think = None

    def chat(self, model, messages, options, keep_alive, think=None):
        self.model = model
        self.options = options
        self.think = think
        return "answer"


def test_model_router_uses_general_model():
    client = FakeOllama()
    router = ModelRouter({"ollama": client}, {"general": {"name": "qwen3.5:9b", "context": 123, "temperature": 0.4}})

    answer, model_used = router.chat("general", [{"role": "user", "content": "Hello"}])

    assert answer == "answer"
    assert model_used == "qwen3.5:9b"
    assert client.model == "qwen3.5:9b"
    assert client.options["num_ctx"] == 123


def test_model_router_disables_thinking_when_configured():
    client = FakeOllama()
    router = ModelRouter({"ollama": client}, {"general": {"name": "qwen3.5:9b", "think": False}})

    router.chat("general", [{"role": "user", "content": "Hello"}])

    assert client.think is False


def test_model_router_rejects_removed_code_mode():
    router = ModelRouter({"ollama": FakeOllama()}, {"general": {"name": "qwen3.5:9b"}})

    with pytest.raises(ValueError):
        router.chat("code", [{"role": "user", "content": "Hello"}])
