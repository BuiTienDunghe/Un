from __future__ import annotations

from typing import Any
from collections.abc import Iterator

from app.llm_clients.ollama_client import OllamaClient


class ModelRouter:
    def __init__(self, client: OllamaClient, models: dict[str, dict[str, Any]]) -> None:
        self.client = client
        self.models = models

    def chat(self, mode: str, messages: list[dict[str, str]]) -> tuple[str, str]:
        if mode not in {"general", "code"}:
            raise ValueError(f"Unsupported model mode: {mode}")
        config = self.models[mode]
        model_name = str(config["name"])
        options = {key: config[key] for key in ("temperature", "top_p") if key in config}
        if "context" in config:
            options["num_ctx"] = config["context"]
        answer = self.client.chat(
            model=model_name,
            messages=messages,
            options=options,
            keep_alive=str(config.get("keep_alive", "5m")),
            think=config.get("think") if isinstance(config.get("think"), bool) else None,
        )
        return answer, model_name

    def embed(self, text: str) -> tuple[list[float], str]:
        config = self.models["embedding"]
        model_name = str(config["name"])
        return self.client.embed(model_name, text), model_name

    def stream_chat(self, mode: str, messages: list[dict[str, str]]) -> tuple[Iterator[str], str]:
        if mode not in {"general", "code"}:
            raise ValueError(f"Unsupported model mode: {mode}")
        config = self.models[mode]
        model_name = str(config["name"])
        options = {key: config[key] for key in ("temperature", "top_p") if key in config}
        if "context" in config:
            options["num_ctx"] = config["context"]
        return self.client.stream_chat(
            model_name,
            messages,
            options,
            str(config.get("keep_alive", "5m")),
            think=config.get("think") if isinstance(config.get("think"), bool) else None,
        ), model_name

    def ocr(self, image_base64: str) -> tuple[str, str]:
        """Extract text from a base64-encoded image using the OCR vision model."""
        config = self.models.get("ocr")
        if config is None or not config.get("enabled", False):
            raise ValueError("OCR fallback is disabled or not configured in models.yaml")
        model_name = str(config["name"])
        options: dict[str, Any] = {}
        if "temperature" in config:
            options["temperature"] = config["temperature"]
        if "context" in config:
            options["num_ctx"] = config["context"]
        prompt = "Text Recognition:"
        answer = self.client.vision_chat(
            model=model_name,
            prompt=prompt,
            images_base64=[image_base64],
            options=options,
            keep_alive=str(config.get("keep_alive", "5m")),
        )
        return answer, model_name
