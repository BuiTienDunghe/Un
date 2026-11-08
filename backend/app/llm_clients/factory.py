"""Construct clients without resolving models or broadening a caller's provider scope."""
from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from app.llm_clients.anthropic_client import AnthropicClient
from app.llm_clients.deepseek_client import DeepSeekClient
from app.llm_clients.gemini_client import GeminiClient
from app.llm_clients.ollama_client import OllamaClient

if TYPE_CHECKING:
    from app.config.settings import Settings

Client = OllamaClient | GeminiClient | DeepSeekClient | AnthropicClient
PROVIDERS = ("ollama", "gemini", "deepseek", "anthropic")


def create_llm_clients(settings: Settings, *, providers: Iterable[str]) -> dict[str, Client]:
    """Only construct explicitly requested providers; cloud clients also require a key.

    The API requests every provider. Workers, rebuilds and evals keep their own
    allowlists; in particular an eval never gains cloud access just because a
    key exists. Model resolution, overrides and embedding refusal stay with callers.
    """
    requested = tuple(dict.fromkeys(providers))
    unknown = set(requested) - set(PROVIDERS)
    if unknown:
        raise ValueError(f"Unknown LLM providers: {', '.join(sorted(unknown))}")
    clients: dict[str, Client] = {}
    for provider in requested:
        if provider == "ollama":
            clients[provider] = OllamaClient(
                settings.ollama_base_url, settings.ollama_chat_timeout_seconds,
                settings.ollama_health_timeout_seconds, settings.ollama_retry_count,
            )
        elif provider == "gemini" and settings.gemini_api_key:
            clients[provider] = GeminiClient(
                api_key=settings.gemini_api_key,
                chat_timeout=settings.gemini_chat_timeout_seconds,
                retry_count=settings.gemini_retry_count,
            )
        elif provider == "deepseek" and settings.deepseek_api_key:
            clients[provider] = DeepSeekClient(
                api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url,
                chat_timeout=settings.deepseek_chat_timeout_seconds,
                retry_count=settings.deepseek_retry_count,
            )
        elif provider == "anthropic" and settings.anthropic_api_key:
            clients[provider] = AnthropicClient(
                api_key=settings.anthropic_api_key,
                chat_timeout=settings.anthropic_chat_timeout_seconds,
                retry_count=settings.anthropic_retry_count,
            )
    return clients
