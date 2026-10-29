"""Claude (Anthropic Messages API) as a provider for the ``general`` role.

The fourth provider beside Ollama, Gemini and DeepSeek, and the first cloud one that
also serves the agent's tool rounds: ``chat_tools`` translates the Ollama-shaped
conversation the agent keeps (OpenAI-style ``{"type": "function"}`` schemas, an assistant
message carrying ``tool_calls``, one ``{"role": "tool"}`` message per result) into
Anthropic content blocks and back, so ``AgentService`` runs unchanged on either provider.

Uses the official ``anthropic`` SDK with its own retries OFF: the retry loop below is the
same shape as the Gemini client's, so ticket 16's turn deadline (``deadline.py``) bounds
every attempt and every back-off sleep. The SDK's built-in retries would stack to
timeout x 3 behind the agent's back.

Sampling knobs are never sent: the Claude 5.x models reject ``temperature`` / ``top_p``
with a 400, and ``effort`` (``output_config``) is the depth knob instead. ``max_tokens``
is mandatory on this API, so the version record carries one.
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from typing import Any

import anthropic
from loguru import logger

from app.llm_clients.deadline import ModelCallTimeoutError, can_wait, request_timeout, spent
from app.llm_clients.usage import record_usage


class AnthropicUnavailableError(Exception):
    """Could not get an answer: connection, server-side error, or a request the API rejected."""


class AnthropicTimeoutError(ModelCallTimeoutError):
    pass


class AnthropicAuthError(Exception):
    pass


class AnthropicRefusalError(Exception):
    """``stop_reason == "refusal"``: the safety classifiers declined. Never retried, never an
    empty answer: the caller must know the turn produced nothing."""


DEFAULT_MAX_TOKENS = 4096

# Errors worth a second attempt: the API is there, this request just did not get through.
_RETRYABLE = (
    anthropic.RateLimitError,
    anthropic.OverloadedError,
    anthropic.InternalServerError,
    anthropic.ServiceUnavailableError,
)


# The block types chat_tools hands back as raw_tool_calls; an Ollama tool call may carry a
# `type` key too ("function"), so the test is on the value, not the key.
_CONTENT_BLOCK_TYPES = frozenset({"text", "tool_use", "thinking", "redacted_thinking"})


def _text_of(blocks: list[Any]) -> str:
    return "".join(getattr(block, "text", "") for block in blocks if getattr(block, "type", None) == "text")


def _new_tool_use_id() -> str:
    return f"toolu_{uuid.uuid4().hex[:24]}"


def convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """OpenAI-style ``{"type": "function", "function": {name, description, parameters}}``
    (what ``ToolRegistry.schemas()`` produces) -> Anthropic ``{name, description, input_schema}``.
    A schema already in Anthropic shape passes through."""
    converted: list[dict[str, Any]] = []
    for tool in tools:
        function = tool.get("function") if tool.get("type") == "function" else None
        if isinstance(function, dict):
            schema = function.get("parameters")
            converted.append({
                "name": str(function["name"]),
                "description": str(function.get("description") or ""),
                "input_schema": schema if isinstance(schema, dict) else {"type": "object", "properties": {}},
            })
        elif "input_schema" in tool:
            converted.append(tool)
        else:
            raise ValueError(f"Unrecognised tool schema: {sorted(tool)}")
    return converted


def convert_messages(messages: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
    """Ollama-shaped conversation -> (top-level system, Anthropic messages).

    - Leading ``system`` messages become the top-level ``system`` string.
    - A later ``system`` message (the agent's "answer now" / retry instruction) stays a
      system-role message where the API allows one (right after a user turn, and last or
      followed by an assistant turn) and is folded into a user message anywhere else.
    - An assistant message whose ``tool_calls`` are the Anthropic blocks ``chat_tools``
      returned (``raw_tool_calls``) is replayed VERBATIM, thinking blocks included; an
      Ollama-shaped ``tool_calls`` list (history written by the other provider) is rebuilt
      as ``tool_use`` blocks with fresh ids.
    - ``{"role": "tool"}`` messages become ``tool_result`` blocks, matched to the previous
      assistant's ``tool_use`` ids by name then by order, and consecutive results share ONE
      user message (the API trains on that shape).
    """
    system_parts: list[str] = []
    out: list[dict[str, Any]] = []
    pending: list[tuple[str, str]] = []  # (tool_use_id, name) the next tool results answer

    def fold_into_user(text: str) -> None:
        out.append({"role": "user", "content": text})

    for message in messages:
        role = str(message.get("role") or "user")
        content = message.get("content")
        text = content if isinstance(content, str) else ("" if content is None else str(content))
        if role == "system":
            if not out:
                system_parts.append(text)
            elif out[-1]["role"] == "user":
                out.append({"role": "system", "content": text})
            else:
                fold_into_user(text)
            continue
        if role == "assistant":
            calls = message.get("tool_calls")
            calls = calls if isinstance(calls, list) else []
            pending = []
            blocks: list[dict[str, Any]] = []
            if calls and all(isinstance(call, dict) and call.get("type") in _CONTENT_BLOCK_TYPES for call in calls):
                for block in calls:  # our own raw_tool_calls: the response content, replayed as produced
                    if block.get("type") == "text" and not str(block.get("text") or "").strip():
                        continue
                    blocks.append(block)
                    if block.get("type") == "tool_use":
                        pending.append((str(block["id"]), str(block["name"])))
            else:
                if text.strip():
                    blocks.append({"type": "text", "text": text})
                for call in calls:
                    function = call.get("function") if isinstance(call, dict) else None
                    if not isinstance(function, dict) or not function.get("name"):
                        continue
                    arguments = function.get("arguments")
                    tool_id = _new_tool_use_id()
                    blocks.append({"type": "tool_use", "id": tool_id, "name": str(function["name"]),
                                   "input": arguments if isinstance(arguments, dict) else {}})
                    pending.append((tool_id, str(function["name"])))
            if blocks:
                out.append({"role": "assistant", "content": blocks})
            continue
        if role == "tool":
            name = str(message.get("tool_name") or "")
            match = next((entry for entry in pending if entry[1] == name), pending[0] if pending else None)
            if match is None:
                fold_into_user(f"[Kết quả công cụ {name}]\n{text}" if name else text)
                continue
            pending.remove(match)
            block = {"type": "tool_result", "tool_use_id": match[0], "content": text}
            previous = out[-1] if out else None
            if (previous and previous["role"] == "user" and isinstance(previous["content"], list)
                    and previous["content"] and previous["content"][-1].get("type") == "tool_result"):
                previous["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
            continue
        out.append({"role": "user", "content": text})

    # A mid-conversation system message must be last or followed by an assistant turn.
    for index in range(len(out) - 1):
        if out[index]["role"] == "system" and out[index + 1]["role"] != "assistant":
            out[index] = {"role": "user", "content": out[index]["content"]}

    system = "\n\n".join(part for part in system_parts if part) or None
    return system, out


class AnthropicClient:
    def __init__(
        self,
        api_key: str,
        chat_timeout: float = 60.0,
        retry_count: int = 2,
        *,
        sdk_client: Any | None = None,
    ) -> None:
        self.chat_timeout = chat_timeout
        self.retry_count = retry_count
        # max_retries=0: the loop below retries, under the agent turn's deadline.
        self._client = sdk_client if sdk_client is not None else anthropic.Anthropic(
            api_key=api_key, max_retries=0, timeout=chat_timeout,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _request_kwargs(
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int | None,
        effort: str | None,
    ) -> dict[str, Any]:
        system, converted = convert_messages(messages)
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": int(max_tokens) if max_tokens else DEFAULT_MAX_TOKENS,
            "messages": converted,
        }
        if system:
            kwargs["system"] = system
        if effort:
            kwargs["output_config"] = {"effort": str(effort)}
        return kwargs

    @staticmethod
    def _record(response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        prompt = ((usage.input_tokens or 0) + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
                  + (getattr(usage, "cache_read_input_tokens", 0) or 0))
        record_usage(prompt, usage.output_tokens)

    @staticmethod
    def _check_stop(response: Any, model: str) -> None:
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details is not None else None
            raise AnthropicRefusalError(f"{model} declined to answer (category {category!r})")
        if response.stop_reason == "max_tokens":
            # Parity with Ollama's chat(): the partial text is returned, the cap is visible in the log.
            logger.bind(event="anthropic_max_tokens", model=model).warning("Claude hit max_tokens before ending its turn")

    def _create(self, **kwargs: Any) -> Any:
        """One ``messages.create`` under the turn deadline, with the Gemini client's retry shape."""
        model = kwargs.get("model")
        for attempt in range(self.retry_count + 1):
            timeout = request_timeout(self.chat_timeout)
            if timeout is None:
                raise AnthropicTimeoutError("Claude was not called: the agent turn's time budget is spent")
            try:
                return self._client.with_options(timeout=timeout).messages.create(**kwargs)
            except anthropic.AuthenticationError as error:
                raise AnthropicAuthError("Invalid Anthropic API key") from error
            except anthropic.APITimeoutError as error:
                if attempt == self.retry_count or spent():
                    raise AnthropicTimeoutError("Claude did not answer before the timeout") from error
            except _RETRYABLE as error:
                if attempt == self.retry_count:
                    raise AnthropicUnavailableError(f"Claude API unavailable ({error.status_code})") from error
            except anthropic.APIStatusError as error:
                # 4xx other than 429: the request itself is wrong; a retry would send it again.
                raise AnthropicUnavailableError(f"Claude API rejected the request ({error.status_code}): {error.message}") from error
            except anthropic.APIConnectionError as error:
                if attempt == self.retry_count:
                    raise AnthropicUnavailableError("Cannot connect to the Claude API") from error
            if not can_wait(1 + attempt * 2):
                raise AnthropicTimeoutError("Claude did not answer within the agent turn's time budget")
            time.sleep(1 + attempt * 2)
        raise AnthropicUnavailableError(f"Cannot connect to the Claude API ({model})")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
        effort: str | None = None,
    ) -> str:
        response = self._create(**self._request_kwargs(model, messages, max_tokens, effort))
        self._record(response)
        self._check_stop(response, model)
        return _text_of(response.content)

    def chat_tools(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int | None = None,
        effort: str | None = None,
    ) -> dict[str, Any]:
        """One function-calling turn in the shape ``OllamaClient.chat_tools`` returns:
        ``{"content", "tool_calls": [{name, arguments}], "raw_tool_calls"}``. Here
        ``raw_tool_calls`` is the whole response content (thinking, text, tool_use blocks)
        so the agent's verbatim echo replays exactly what the model produced.

        ``cache_control`` caches the request prefix: round 2 of an agent turn re-sends round
        1's prompt, tools and messages byte for byte, so it is read from the cache instead
        of being billed again (``usage.cache_read_input_tokens`` says how much)."""
        kwargs = self._request_kwargs(model, messages, max_tokens, effort)
        kwargs["tools"] = convert_tools(tools)
        kwargs["cache_control"] = {"type": "ephemeral"}
        response = self._create(**kwargs)
        self._record(response)
        self._check_stop(response, model)
        raw = [block.model_dump(exclude_none=True) for block in response.content]
        tool_calls = [
            {"name": str(block.name), "arguments": block.input if isinstance(block.input, dict) else {}}
            for block in response.content
            if getattr(block, "type", None) == "tool_use"
        ]
        return {"content": _text_of(response.content), "tool_calls": tool_calls, "raw_tool_calls": raw}

    def stream_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
        effort: str | None = None,
    ) -> Iterator[str]:
        """Text deltas as they arrive; usage recorded from the final message. One attempt,
        like the other providers' streams: a retry would replay text the client already has."""
        kwargs = self._request_kwargs(model, messages, max_tokens, effort)
        timeout = request_timeout(self.chat_timeout)
        if timeout is None:
            raise AnthropicTimeoutError("Claude was not called: the agent turn's time budget is spent")
        try:
            with self._client.with_options(timeout=timeout).messages.stream(**kwargs) as stream:
                for event in stream:
                    if getattr(event, "type", None) == "text" and event.text:
                        yield event.text
                final = stream.get_final_message()
        except anthropic.AuthenticationError as error:
            raise AnthropicAuthError("Invalid Anthropic API key") from error
        except anthropic.APITimeoutError as error:
            raise AnthropicTimeoutError("Claude did not finish streaming before the timeout") from error
        except anthropic.APIStatusError as error:
            raise AnthropicUnavailableError(f"Claude API error while streaming ({error.status_code}): {error.message}") from error
        except anthropic.APIConnectionError as error:
            raise AnthropicUnavailableError("Cannot connect to the Claude API for streaming") from error
        self._record(final)
        self._check_stop(final, model)
