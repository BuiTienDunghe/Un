from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

import httpx


class GeminiUnavailableError(Exception):
    pass


class GeminiTimeoutError(Exception):
    pass


class GeminiAuthError(Exception):
    pass


class GeminiClient:
    """Client for the Google Gemini REST API (generateContent / streamGenerateContent).

    Uses the ``generativelanguage.googleapis.com`` v1beta endpoint directly so
    that no Google SDK is required.  Only *text* chat is supported here;
    embedding and vision can be wired up later.
    """

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(
        self,
        api_key: str,
        chat_timeout: float = 60.0,
        retry_count: int = 2,
    ) -> None:
        self.api_key = api_key
        self.chat_timeout = chat_timeout
        self.retry_count = retry_count

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _convert_messages(self, messages: list[dict[str, str]]) -> tuple[str | None, list[dict[str, Any]]]:
        """Split OpenAI-style messages into a Gemini system instruction + contents list."""
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role", "user")
            text = msg.get("content", "")
            if role == "system":
                system_parts.append(text)
            elif role == "assistant":
                contents.append({"role": "model", "parts": [{"text": text}]})
            else:
                contents.append({"role": "user", "parts": [{"text": text}]})

        system_instruction: str | None = "\n\n".join(system_parts) if system_parts else None
        return system_instruction, contents

    def _build_payload(
        self,
        messages: list[dict[str, str]],
        temperature: float | None,
        max_tokens: int | None,
        top_p: float | None,
    ) -> dict[str, Any]:
        system_instruction, contents = self._convert_messages(messages)
        payload: dict[str, Any] = {"contents": contents}
        if system_instruction:
            payload["system_instruction"] = {"parts": [{"text": system_instruction}]}
        generation_config: dict[str, Any] = {}
        if temperature is not None:
            generation_config["temperature"] = temperature
        if max_tokens is not None:
            generation_config["maxOutputTokens"] = max_tokens
        if top_p is not None:
            generation_config["topP"] = top_p
        if generation_config:
            payload["generationConfig"] = generation_config
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
        url = f"{self.BASE_URL}/models/{model}:generateContent?key={self.api_key}"
        payload = self._build_payload(messages, temperature, max_tokens, top_p)

        for attempt in range(self.retry_count + 1):
            try:
                response = httpx.post(url, json=payload, timeout=self.chat_timeout)
                if response.status_code == 401:
                    raise GeminiAuthError("Invalid Gemini API key")
                if response.status_code == 429:
                    # Rate limited – back off before retry
                    if attempt < self.retry_count:
                        time.sleep(2 + attempt * 3)
                        continue
                response.raise_for_status()
                data = response.json()
                text = (
                    data.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                )
                if not isinstance(text, str):
                    raise GeminiUnavailableError("Gemini returned an invalid response structure")
                return text
            except GeminiAuthError:
                raise
            except httpx.TimeoutException as error:
                if attempt == self.retry_count:
                    raise GeminiTimeoutError("Gemini did not answer before the timeout") from error
            except httpx.HTTPError as error:
                if attempt == self.retry_count:
                    raise GeminiUnavailableError("Cannot connect to Gemini API") from error
            time.sleep(1 + attempt * 2)
        raise GeminiUnavailableError("Cannot connect to Gemini API")

    def stream_chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
    ) -> Iterator[str]:
        """Stream a chat response token by token (server-sent events)."""
        url = f"{self.BASE_URL}/models/{model}:streamGenerateContent?alt=sse&key={self.api_key}"
        payload = self._build_payload(messages, temperature, max_tokens, top_p)

        try:
            with httpx.stream("POST", url, json=payload, timeout=self.chat_timeout) as response:
                if response.status_code == 401:
                    raise GeminiAuthError("Invalid Gemini API key")
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
                    text = (
                        chunk.get("candidates", [{}])[0]
                        .get("content", {})
                        .get("parts", [{}])[0]
                        .get("text", "")
                    )
                    if isinstance(text, str) and text:
                        yield text
        except GeminiAuthError:
            raise
        except httpx.TimeoutException as error:
            raise GeminiTimeoutError("Gemini did not finish streaming before the timeout") from error
        except httpx.HTTPError as error:
            raise GeminiUnavailableError("Cannot connect to Gemini API for streaming") from error
