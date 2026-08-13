from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

import httpx


class DeepSeekUnavailableError(Exception):
    pass


class DeepSeekTimeoutError(Exception):
    pass


class DeepSeekAuthError(Exception):
    pass


class DeepSeekClient:
    """Client for the DeepSeek API (OpenAI-compatible chat completions).

    Compatible with DeepSeek-V3 (``deepseek-chat``) and
    DeepSeek-R2/Reasoner (``deepseek-reasoner``).
    The base URL defaults to ``https://api.deepseek.com`` and can be
    overridden via settings for self-hosted deployments.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        chat_timeout: float = 90.0,
        retry_count: int = 2,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.chat_timeout = chat_timeout
        self.retry_count = retry_count

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float | None,
        max_tokens: int | None,
        top_p: float | None,
        stream: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if top_p is not None:
            payload["top_p"] = top_p
        return payload

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
    ) -> str:
        """Send a blocking chat request and return the text response."""
        url = f"{self.base_url}/chat/completions"
        payload = self._build_payload(model, messages, temperature, max_tokens, top_p, stream=False)

        for attempt in range(self.retry_count + 1):
            try:
                response = httpx.post(url, json=payload, headers=self._headers(), timeout=self.chat_timeout)
                if response.status_code == 401:
                    raise DeepSeekAuthError("Invalid DeepSeek API key")
                if response.status_code == 402:
                    raise DeepSeekAuthError("DeepSeek account has insufficient balance")
                if response.status_code == 429:
                    if attempt < self.retry_count:
                        time.sleep(2 + attempt * 3)
                        continue
                response.raise_for_status()
                data = response.json()
                content = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                if not isinstance(content, str):
                    raise DeepSeekUnavailableError("DeepSeek returned an invalid response structure")
                return content
            except DeepSeekAuthError:
                raise
            except httpx.TimeoutException as error:
                if attempt == self.retry_count:
                    raise DeepSeekTimeoutError("DeepSeek did not answer before the timeout") from error
            except httpx.HTTPError as error:
                if attempt == self.retry_count:
                    raise DeepSeekUnavailableError("Cannot connect to DeepSeek API") from error
            time.sleep(1 + attempt * 2)
        raise DeepSeekUnavailableError("Cannot connect to DeepSeek API")

    def stream_chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
    ) -> Iterator[str]:
        """Stream a chat response token by token (SSE, OpenAI-compatible)."""
        url = f"{self.base_url}/chat/completions"
        payload = self._build_payload(model, messages, temperature, max_tokens, top_p, stream=True)

        try:
            with httpx.stream("POST", url, json=payload, headers=self._headers(), timeout=self.chat_timeout) as response:
                if response.status_code == 401:
                    raise DeepSeekAuthError("Invalid DeepSeek API key")
                if response.status_code == 402:
                    raise DeepSeekAuthError("DeepSeek account has insufficient balance")
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    raw = line[len("data:"):].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    delta = (
                        chunk.get("choices", [{}])[0]
                        .get("delta", {})
                        .get("content", "")
                    )
                    if isinstance(delta, str) and delta:
                        yield delta
        except DeepSeekAuthError:
            raise
        except httpx.TimeoutException as error:
            raise DeepSeekTimeoutError("DeepSeek did not finish streaming before the timeout") from error
        except httpx.HTTPError as error:
            raise DeepSeekUnavailableError("Cannot connect to DeepSeek API for streaming") from error
