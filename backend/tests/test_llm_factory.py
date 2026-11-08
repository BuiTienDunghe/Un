"""Provider construction stays explicit and preserves each process's configuration."""
from types import SimpleNamespace

import pytest

from app.llm_clients import factory


def settings(**overrides):
    values = dict(
        ollama_base_url="http://local:11434", ollama_chat_timeout_seconds=41,
        ollama_health_timeout_seconds=3, ollama_retry_count=2,
        gemini_api_key="gemini-test", gemini_chat_timeout_seconds=42, gemini_retry_count=3,
        deepseek_api_key="deepseek-test", deepseek_base_url="http://deepseek-test",
        deepseek_chat_timeout_seconds=43, deepseek_retry_count=4,
        anthropic_api_key="anthropic-test", anthropic_chat_timeout_seconds=44, anthropic_retry_count=5,
    )
    return SimpleNamespace(**(values | overrides))


def capture_constructors(monkeypatch):
    calls = {}
    for provider, name in [("ollama", "OllamaClient"), ("gemini", "GeminiClient"),
                           ("deepseek", "DeepSeekClient"), ("anthropic", "AnthropicClient")]:
        def construct(*args, _provider=provider, **kwargs):
            calls[_provider] = (args, kwargs)
            return SimpleNamespace(provider=_provider)
        monkeypatch.setattr(factory, name, construct)
    return calls


def test_api_preserves_constructor_parameters(monkeypatch):
    calls = capture_constructors(monkeypatch)
    clients = factory.create_llm_clients(settings(), providers=factory.PROVIDERS)
    assert list(clients) == ["ollama", "gemini", "deepseek", "anthropic"]
    assert calls == {
        "ollama": (("http://local:11434", 41, 3, 2), {}),
        "gemini": ((), {"api_key": "gemini-test", "chat_timeout": 42, "retry_count": 3}),
        "deepseek": ((), {"api_key": "deepseek-test", "base_url": "http://deepseek-test", "chat_timeout": 43, "retry_count": 4}),
        "anthropic": ((), {"api_key": "anthropic-test", "chat_timeout": 44, "retry_count": 5}),
    }


def test_ollama_only_callers_do_not_gain_cloud_clients_when_keys_exist(monkeypatch):
    calls = capture_constructors(monkeypatch)
    clients = factory.create_llm_clients(settings(), providers=("ollama",))
    assert list(clients) == list(calls) == ["ollama"]


def test_unrequested_providers_do_not_require_their_settings(monkeypatch):
    calls = capture_constructors(monkeypatch)
    clients = factory.create_llm_clients(SimpleNamespace(
        gemini_api_key="condenser-key", gemini_chat_timeout_seconds=9, gemini_retry_count=1,
    ), providers=("gemini",))
    assert list(clients) == list(calls) == ["gemini"]


def test_missing_cloud_keys_keep_those_clients_unregistered(monkeypatch):
    calls = capture_constructors(monkeypatch)
    clients = factory.create_llm_clients(settings(gemini_api_key="", deepseek_api_key="", anthropic_api_key=""), providers=factory.PROVIDERS)
    assert list(clients) == list(calls) == ["ollama"]


def test_unknown_provider_is_rejected_before_any_client_is_created(monkeypatch):
    calls = capture_constructors(monkeypatch)
    with pytest.raises(ValueError, match="Unknown LLM providers"):
        factory.create_llm_clients(settings(), providers=("ollama", "typo"))
    assert calls == {}
