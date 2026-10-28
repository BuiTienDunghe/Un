"""AnthropicClient: the Ollama-shaped conversation the agent keeps, translated to the
Messages API and back, under ticket 16's deadline. The SDK is replaced by a scripted fake:
nothing here touches the network."""
from __future__ import annotations

import time
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from anthropic.types import TextBlock, ToolUseBlock

from app.llm_clients import anthropic_client as module
from app.llm_clients.anthropic_client import (
    AnthropicAuthError,
    AnthropicClient,
    AnthropicRefusalError,
    AnthropicTimeoutError,
    AnthropicUnavailableError,
    convert_messages,
    convert_tools,
)
from app.llm_clients.deadline import call_deadline
from app.llm_clients.usage import consume_usage


def response(*blocks, stop_reason="end_turn", category=None, tokens=(10, 3, 0, 0)):
    input_tokens, output_tokens, cache_write, cache_read = tokens
    return SimpleNamespace(
        content=list(blocks),
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category=category) if stop_reason == "refusal" else None,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                              cache_creation_input_tokens=cache_write, cache_read_input_tokens=cache_read),
    )


def text(value):
    return TextBlock(type="text", text=value)


def tool_use(block_id, name, **arguments):
    return ToolUseBlock(type="tool_use", id=block_id, name=name, input=arguments)


class FakeStream:
    def __init__(self, deltas, final):
        self.deltas, self.final = deltas, final

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        for delta in self.deltas:
            yield SimpleNamespace(type="text", text=delta)
        yield SimpleNamespace(type="message_stop")

    def get_final_message(self):
        return self.final


class FakeSDK:
    """Stands in for anthropic.Anthropic: records every request, answers from a script."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls: list[dict] = []
        self.timeouts: list[float] = []
        self.messages = self

    def with_options(self, timeout):
        self.timeouts.append(timeout)
        return self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        return self.script.pop(0)


def client(*script, **kwargs):
    sdk = FakeSDK(*script)
    return AnthropicClient("key", sdk_client=sdk, **kwargs), sdk


def status_error(kind, status, message="nope"):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    body = {"error": {"type": "x", "message": message}}
    return kind(message, response=httpx2.Response(status, request=request, json=body), body=None)


SCHEMA = {"type": "function", "function": {
    "name": "search_documents", "description": "Tìm",
    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
}}
USER = {"role": "user", "content": "q"}


def test_chat_splits_the_system_prompt_and_sends_no_sampling_knobs():
    api, sdk = client(response(text("Xin chào")))
    consume_usage()
    messages = [{"role": "system", "content": "S1"}, {"role": "system", "content": "S2"}, {"role": "user", "content": "hi"}]
    assert api.chat("claude-haiku-5-5", messages, max_tokens=4096, effort="low") == "Xin chào"
    call = sdk.calls[0]
    assert call["system"] == "S1\n\nS2"
    assert call["messages"] == [{"role": "user", "content": "hi"}]
    assert call["max_tokens"] == 4096 and call["output_config"] == {"effort": "low"}
    assert not {"temperature", "top_p", "thinking", "tools"} & set(call)
    assert sdk.timeouts == [60.0]
    assert consume_usage() == {"tokens_in": 10, "tokens_out": 3}


def test_usage_counts_cached_prompt_tokens_as_prompt_tokens():
    api, _ = client(response(text("a"), tokens=(100, 7, 20, 300)))
    api.chat("m", [USER])
    assert consume_usage() == {"tokens_in": 420, "tokens_out": 7}


def test_convert_tools_translates_openai_function_schemas():
    assert convert_tools([SCHEMA]) == [{"name": "search_documents", "description": "Tìm", "input_schema": SCHEMA["function"]["parameters"]}]
    anthropic_shaped = {"name": "x", "description": "", "input_schema": {"type": "object", "properties": {}}}
    assert convert_tools([anthropic_shaped]) == [anthropic_shaped]
    with pytest.raises(ValueError):
        convert_tools([{"bogus": 1}])


def test_chat_tools_returns_the_ollama_shape_and_replays_its_own_blocks_verbatim():
    first = response(text("Để tôi tìm."), tool_use("toolu_1", "search_documents", query="nghỉ tết"), stop_reason="tool_use")
    api, sdk = client(first, response(text("Xong.")))
    result = api.chat_tools("m", [{"role": "system", "content": "S"}, USER], [SCHEMA], max_tokens=4096)
    assert result["content"] == "Để tôi tìm."
    assert result["tool_calls"] == [{"name": "search_documents", "arguments": {"query": "nghỉ tết"}}]
    assert result["raw_tool_calls"] == [
        {"type": "text", "text": "Để tôi tìm."},
        {"type": "tool_use", "id": "toolu_1", "name": "search_documents", "input": {"query": "nghỉ tết"}},
    ]
    assert sdk.calls[0]["tools"] == convert_tools([SCHEMA]) and sdk.calls[0]["cache_control"] == {"type": "ephemeral"}

    # Round 2, exactly as AgentService appends it.
    working = [
        {"role": "system", "content": "S"}, USER,
        {"role": "assistant", "content": result["content"], "tool_calls": result["raw_tool_calls"]},
        {"role": "tool", "tool_name": "search_documents", "content": "[kết quả]"},
    ]
    api.chat_tools("m", working, [SCHEMA])
    assert sdk.calls[1]["messages"] == [
        USER,
        {"role": "assistant", "content": result["raw_tool_calls"]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "[kết quả]"}]},
    ]


def test_two_results_share_one_user_message_and_match_ids_by_name_then_order():
    raw = [
        {"type": "tool_use", "id": "toolu_a", "name": "a", "input": {}},
        {"type": "tool_use", "id": "toolu_b", "name": "b", "input": {}},
        {"type": "tool_use", "id": "toolu_c", "name": "b", "input": {}},
    ]
    _, out = convert_messages([
        USER,
        {"role": "assistant", "content": "", "tool_calls": raw},
        {"role": "tool", "tool_name": "b", "content": "B1"},
        {"role": "tool", "tool_name": "a", "content": "A"},
        {"role": "tool", "tool_name": "b", "content": "B2"},
    ])
    assert out[1] == {"role": "assistant", "content": raw}
    assert out[2] == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_b", "content": "B1"},
        {"type": "tool_result", "tool_use_id": "toolu_a", "content": "A"},
        {"type": "tool_result", "tool_use_id": "toolu_c", "content": "B2"},
    ]}
    assert len(out) == 3


def test_ollama_shaped_history_is_rebuilt_with_fresh_ids():
    _, out = convert_messages([
        USER,
        {"role": "assistant", "content": "Tìm nhé", "tool_calls": [{"function": {"name": "search_documents", "arguments": {"query": "x"}}}]},
        {"role": "tool", "tool_name": "search_documents", "content": "r"},
    ])
    blocks = out[1]["content"]
    assert blocks[0] == {"type": "text", "text": "Tìm nhé"}
    assert blocks[1]["type"] == "tool_use" and blocks[1]["id"].startswith("toolu_") and blocks[1]["input"] == {"query": "x"}
    assert out[2]["content"] == [{"type": "tool_result", "tool_use_id": blocks[1]["id"], "content": "r"}]


def test_mid_conversation_system_stays_system_only_where_the_api_allows_it():
    # After tool results and last — the agent's "answer now": a real system message.
    _, out = convert_messages([
        {"role": "system", "content": "S"}, USER,
        {"role": "assistant", "content": "", "tool_calls": [{"type": "tool_use", "id": "t", "name": "a", "input": {}}]},
        {"role": "tool", "tool_name": "a", "content": "r"},
        {"role": "system", "content": "Trả lời ngay"},
    ])
    assert out[-1] == {"role": "system", "content": "Trả lời ngay"}
    # After an assistant message — the retry instruction: folded into a user turn.
    _, out = convert_messages([USER, {"role": "assistant", "content": "a"}, {"role": "system", "content": "retry"}])
    assert out[-1] == {"role": "user", "content": "retry"}
    # Followed by a user turn: folded too.
    _, out = convert_messages([USER, {"role": "system", "content": "x"}, {"role": "user", "content": "y"}])
    assert [message["role"] for message in out] == ["user", "user", "user"]


def test_refusal_raises_instead_of_returning_empty_text():
    api, _ = client(response(stop_reason="refusal", category="cyber"))
    with pytest.raises(AnthropicRefusalError, match="cyber"):
        api.chat("m", [USER])


def test_max_tokens_keeps_the_partial_text():
    api, _ = client(response(text("một phần"), stop_reason="max_tokens"))
    assert api.chat("m", [USER]) == "một phần"


def test_a_spent_turn_budget_skips_the_call():
    api, sdk = client(response(text("late")))
    with call_deadline(time.monotonic() - 1):
        with pytest.raises(AnthropicTimeoutError):
            api.chat("m", [USER])
    assert sdk.calls == []


def test_the_turn_deadline_bounds_the_request_timeout():
    api, sdk = client(response(text("ok")))
    with call_deadline(time.monotonic() + 5):
        api.chat("m", [USER])
    assert 0 < sdk.timeouts[0] <= 5


def test_rate_limit_is_retried_and_auth_or_bad_request_is_not(monkeypatch):
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    api, sdk = client(status_error(anthropic.RateLimitError, 429), response(text("ok")))
    assert api.chat("m", [USER]) == "ok" and len(sdk.calls) == 2

    api, sdk = client(status_error(anthropic.AuthenticationError, 401))
    with pytest.raises(AnthropicAuthError):
        api.chat("m", [USER])
    assert len(sdk.calls) == 1

    api, sdk = client(status_error(anthropic.BadRequestError, 400, "temperature is not supported"))
    with pytest.raises(AnthropicUnavailableError, match="temperature"):
        api.chat("m", [USER])
    assert len(sdk.calls) == 1

    limited = [status_error(anthropic.RateLimitError, 429) for _ in range(3)]
    api, sdk = client(*limited)
    with pytest.raises(AnthropicUnavailableError):
        api.chat("m", [USER])
    assert len(sdk.calls) == 3


def test_timeouts_retry_until_the_last_attempt(monkeypatch):
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    api, sdk = client(*[anthropic.APITimeoutError(request) for _ in range(3)])
    with pytest.raises(AnthropicTimeoutError):
        api.chat("m", [USER])
    assert len(sdk.calls) == 3


def test_stream_chat_yields_text_deltas_and_records_usage():
    final = response(text("xin chào"), tokens=(5, 2, 0, 0))
    api, sdk = client(FakeStream(["xin ", "chào"], final))
    consume_usage()
    deltas = list(api.stream_chat("m", [{"role": "system", "content": "S"}, USER], max_tokens=64, effort="low"))
    assert deltas == ["xin ", "chào"]
    assert sdk.calls[0]["system"] == "S" and sdk.calls[0]["max_tokens"] == 64
    assert consume_usage() == {"tokens_in": 5, "tokens_out": 2}
