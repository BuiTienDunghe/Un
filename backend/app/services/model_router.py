from __future__ import annotations

from typing import Any
from collections.abc import Iterator

from app.llm_clients.ollama_client import OllamaClient
from app.llm_clients.gemini_client import GeminiClient
from app.llm_clients.deepseek_client import DeepSeekClient


# Union type for all supported clients
LLMClient = OllamaClient | GeminiClient | DeepSeekClient


class ModelRouter:
    """Routes model requests to the correct LLM client based on ``provider`` in models.yaml.

    Supported providers
    -------------------
    - ``ollama``   – local Ollama inference server (default)
    - ``gemini``   – Google Gemini REST API
    - ``deepseek`` – DeepSeek API (OpenAI-compatible)

    To switch a model to a different provider, change the ``provider`` field
    in ``backend/app/config/models.yaml`` and restart the server.  The
    corresponding API key must be set in ``.env``.
    """

    def __init__(
        self,
        clients: dict[str, LLMClient],
        models: dict[str, dict[str, Any]],
    ) -> None:
        self.clients = clients
        self.models = models

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client(self, config: dict[str, Any]) -> LLMClient:
        provider = str(config.get("provider", "ollama")).lower()
        client = self.clients.get(provider)
        if client is None:
            available = ", ".join(self.clients.keys())
            raise RuntimeError(
                f"Provider '{provider}' is not configured. "
                f"Available providers: {available}. "
                f"Check that the corresponding API key is set in .env."
            )
        return client

    def _ollama_options(self, config: dict[str, Any]) -> dict[str, Any]:
        options = {key: config[key] for key in ("temperature", "top_p") if key in config}
        if "context" in config:
            options["num_ctx"] = config["context"]
        return options

    def _cloud_kwargs(self, config: dict[str, Any]) -> dict[str, Any]:
        """Extract keyword arguments understood by Gemini and DeepSeek clients."""
        kwargs: dict[str, Any] = {}
        if "temperature" in config:
            kwargs["temperature"] = config["temperature"]
        if "max_tokens" in config:
            kwargs["max_tokens"] = config["max_tokens"]
        if "top_p" in config:
            kwargs["top_p"] = config["top_p"]
        return kwargs

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(self, mode: str, messages: list[dict[str, str]]) -> tuple[str, str]:
        if mode not in {"general", "code"}:
            raise ValueError(f"Unsupported model mode: {mode}")
        config = self.models[mode]
        model_name = str(config["name"])
        client = self._get_client(config)

        if isinstance(client, OllamaClient):
            answer = client.chat(
                model=model_name,
                messages=messages,
                options=self._ollama_options(config),
                keep_alive=str(config.get("keep_alive", "5m")),
                think=config.get("think") if isinstance(config.get("think"), bool) else None,
            )
        elif isinstance(client, GeminiClient):
            answer = client.chat(model=model_name, messages=messages, **self._cloud_kwargs(config))
        elif isinstance(client, DeepSeekClient):
            answer = client.chat(model=model_name, messages=messages, **self._cloud_kwargs(config))
        else:
            raise RuntimeError(f"Unknown client type: {type(client)}")

        return answer, model_name

    def embed(self, text: str) -> tuple[list[float], str]:
        """Embedding always uses Ollama (cloud embedding not yet supported)."""
        config = self.models["embedding"]
        model_name = str(config["name"])
        # Embedding is only supported via Ollama regardless of provider field
        ollama = self.clients.get("ollama")
        if not isinstance(ollama, OllamaClient):
            raise RuntimeError("Embedding requires the 'ollama' provider to be configured")
        return ollama.embed(model_name, text), model_name

    def stream_chat(self, mode: str, messages: list[dict[str, str]]) -> tuple[Iterator[str], str]:
        if mode not in {"general", "code"}:
            raise ValueError(f"Unsupported model mode: {mode}")
        config = self.models[mode]
        model_name = str(config["name"])
        client = self._get_client(config)

        if isinstance(client, OllamaClient):
            stream = client.stream_chat(
                model_name,
                messages,
                self._ollama_options(config),
                str(config.get("keep_alive", "5m")),
                think=config.get("think") if isinstance(config.get("think"), bool) else None,
            )
        elif isinstance(client, GeminiClient):
            stream = client.stream_chat(model=model_name, messages=messages, **self._cloud_kwargs(config))
        elif isinstance(client, DeepSeekClient):
            stream = client.stream_chat(model=model_name, messages=messages, **self._cloud_kwargs(config))
        else:
            raise RuntimeError(f"Unknown client type: {type(client)}")

        return stream, model_name

    def ocr(self, image_base64: str, prompt: str = "Text Recognition:") -> tuple[str, str]:
        """Extract text from a base64-encoded image using the OCR vision model.

        OCR is always routed through Ollama (vision API requires local model).
        """
        config = self.models.get("ocr")
        if config is None or not config.get("enabled", False):
            raise ValueError("OCR fallback is disabled or not configured in models.yaml")
        model_name = str(config["name"])
        ollama = self.clients.get("ollama")
        if not isinstance(ollama, OllamaClient):
            raise RuntimeError("OCR requires the 'ollama' provider to be configured")
        options: dict[str, Any] = {}
        if "temperature" in config:
            options["temperature"] = config["temperature"]
        if "context" in config:
            options["num_ctx"] = config["context"]
        answer = ollama.vision_chat(
            model=model_name,
            prompt=prompt,
            images_base64=[image_base64],
            options=options,
            keep_alive=str(config.get("keep_alive", "5m")),
        )
        return answer, model_name
