from __future__ import annotations

import time
import json
from collections.abc import Iterator
from typing import Any

import httpx

from app.llm_clients.usage import record_usage


class OllamaUnavailableError(Exception):
    pass


class OllamaModelNotLoadedError(Exception):
    pass


class OllamaTimeoutError(Exception):
    pass


class OllamaClient:
    def __init__(self, base_url: str, chat_timeout: float, health_timeout: float, retry_count: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.chat_timeout = chat_timeout
        self.health_timeout = health_timeout
        self.retry_count = retry_count

    def healthcheck(self) -> bool:
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=self.health_timeout)
            return response.is_success
        except httpx.HTTPError:
            return False

    def chat(self, model: str, messages: list[dict[str, str]], options: dict[str, Any], keep_alive: str, think: bool | None = None) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": options,
            "keep_alive": keep_alive,
        }
        if think is not None:
            payload["think"] = think
        for attempt in range(self.retry_count + 1):
            try:
                response = httpx.post(
                    f"{self.base_url}/api/chat", json=payload, timeout=self.chat_timeout
                )
                if response.status_code == 404:
                    raise OllamaModelNotLoadedError(
                        f"Model {model} is unavailable. Run: ollama pull {model}"
                    )
                response.raise_for_status()
                body = response.json()
                content = body.get("message", {}).get("content")
                if not isinstance(content, str):
                    raise OllamaUnavailableError("Ollama returned an invalid chat response")
                # D4-lite: the counts were always in this body; they were
                # parsed and thrown away while "was the 16 s prompt-eval or
                # generation?" stayed unanswerable.
                record_usage(body.get("prompt_eval_count"), body.get("eval_count"))
                return content
            except OllamaModelNotLoadedError:
                raise
            except httpx.TimeoutException as error:
                if attempt == self.retry_count:
                    raise OllamaTimeoutError("Ollama did not answer before the timeout") from error
            except httpx.HTTPError as error:
                if attempt == self.retry_count:
                    raise OllamaUnavailableError("Cannot connect to Ollama") from error
            time.sleep(1 + attempt * 2)
        raise OllamaUnavailableError("Cannot connect to Ollama")

    def chat_tools(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        options: dict[str, Any],
        keep_alive: str,
        think: bool | None = None,
    ) -> dict[str, Any]:
        """One non-streaming chat turn with function-calling enabled.

        Returns ``{"content", "tool_calls", "raw_tool_calls"}``: `tool_calls`
        is normalised to `{name, arguments}`, `raw_tool_calls` is the exact
        payload Ollama produced — the follow-up request must echo it back in
        the assistant message so the model can see its own calls.
        """
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": options,
            "keep_alive": keep_alive,
            "tools": tools,
        }
        if think is not None:
            payload["think"] = think
        for attempt in range(self.retry_count + 1):
            try:
                response = httpx.post(
                    f"{self.base_url}/api/chat", json=payload, timeout=self.chat_timeout
                )
                if response.status_code == 404:
                    raise OllamaModelNotLoadedError(
                        f"Model {model} is unavailable. Run: ollama pull {model}"
                    )
                response.raise_for_status()
                message = response.json().get("message", {})
                content = message.get("content")
                if not isinstance(content, str):
                    raise OllamaUnavailableError("Ollama returned an invalid chat response")
                raw_tool_calls = message.get("tool_calls")
                raw_tool_calls = raw_tool_calls if isinstance(raw_tool_calls, list) else []
                tool_calls = []
                for call in raw_tool_calls:
                    function = call.get("function") if isinstance(call, dict) else None
                    if not isinstance(function, dict):
                        continue
                    name = function.get("name")
                    arguments = function.get("arguments")
                    if isinstance(name, str) and name:
                        tool_calls.append({
                            "name": name,
                            "arguments": arguments if isinstance(arguments, dict) else {},
                        })
                return {"content": content, "tool_calls": tool_calls, "raw_tool_calls": raw_tool_calls}
            except OllamaModelNotLoadedError:
                raise
            except httpx.TimeoutException as error:
                if attempt == self.retry_count:
                    raise OllamaTimeoutError("Ollama did not answer before the timeout") from error
            except httpx.HTTPError as error:
                if attempt == self.retry_count:
                    raise OllamaUnavailableError("Cannot connect to Ollama") from error
            time.sleep(1 + attempt * 2)
        raise OllamaUnavailableError("Cannot connect to Ollama")

    def embed(self, model: str, text: str) -> list[float]:
        for attempt in range(self.retry_count + 1):
            try:
                response = httpx.post(
                    f"{self.base_url}/api/embed", json={"model": model, "input": text}, timeout=self.chat_timeout
                )
                if response.status_code == 404:
                    raise OllamaModelNotLoadedError(f"Model {model} is unavailable. Run: ollama pull {model}")
                response.raise_for_status()
                embeddings = response.json().get("embeddings")
                if not isinstance(embeddings, list) or not embeddings or not isinstance(embeddings[0], list):
                    raise OllamaUnavailableError("Ollama returned an invalid embedding response")
                return [float(value) for value in embeddings[0]]
            except OllamaModelNotLoadedError:
                raise
            except httpx.TimeoutException as error:
                if attempt == self.retry_count:
                    raise OllamaTimeoutError("Ollama embedding did not finish before the timeout") from error
            except httpx.HTTPError as error:
                if attempt == self.retry_count:
                    raise OllamaUnavailableError("Cannot connect to Ollama for embedding") from error
            time.sleep(1 + attempt * 2)
        raise OllamaUnavailableError("Cannot connect to Ollama for embedding")

    def vision_chat(self, model: str, prompt: str, images_base64: list[str], options: dict[str, Any], keep_alive: str) -> str:
        """Send a vision/multimodal chat request with base64-encoded images."""
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": images_base64,
                }
            ],
            "stream": False,
            "options": options,
            "keep_alive": keep_alive,
        }
        for attempt in range(self.retry_count + 1):
            try:
                response = httpx.post(
                    f"{self.base_url}/api/chat", json=payload, timeout=self.chat_timeout
                )
                if response.status_code == 404:
                    raise OllamaModelNotLoadedError(
                        f"Model {model} is unavailable. Run: ollama pull {model}"
                    )
                response.raise_for_status()
                content = response.json().get("message", {}).get("content")
                if not isinstance(content, str):
                    raise OllamaUnavailableError("Ollama returned an invalid vision chat response")
                return content
            except OllamaModelNotLoadedError:
                raise
            except httpx.TimeoutException as error:
                if attempt == self.retry_count:
                    raise OllamaTimeoutError("Ollama vision chat did not answer before the timeout") from error
            except httpx.HTTPError as error:
                if attempt == self.retry_count:
                    raise OllamaUnavailableError("Cannot connect to Ollama for vision chat") from error
            time.sleep(1 + attempt * 2)
        raise OllamaUnavailableError("Cannot connect to Ollama for vision chat")

    def stream_chat(self, model: str, messages: list[dict[str, str]], options: dict[str, Any], keep_alive: str, think: bool | None = None) -> Iterator[str]:
        payload = {"model": model, "messages": messages, "stream": True, "options": options, "keep_alive": keep_alive}
        if think is not None:
            payload["think"] = think
        try:
            with httpx.stream("POST", f"{self.base_url}/api/chat", json=payload, timeout=self.chat_timeout) as response:
                if response.status_code == 404:
                    raise OllamaModelNotLoadedError(f"Model {model} is unavailable. Run: ollama pull {model}")
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if chunk.get("done"):
                        # Usage arrives only on the final chunk. Recorded from
                        # the same thread that iterates, so the ContextVar is
                        # readable right after the loop by whoever consumes it.
                        record_usage(chunk.get("prompt_eval_count"), chunk.get("eval_count"))
                    content = chunk.get("message", {}).get("content")
                    if isinstance(content, str) and content:
                        yield content
        except OllamaModelNotLoadedError:
            raise
        except httpx.TimeoutException as error:
            raise OllamaTimeoutError("Ollama did not finish streaming before the timeout") from error
        except httpx.HTTPError as error:
            raise OllamaUnavailableError("Cannot connect to Ollama for streaming") from error
