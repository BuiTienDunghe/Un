"""What chat_tools says when Ollama answers with an error (ticket 27).

A tool call Ollama could not parse is its own error, raised at once: at temperature 0 the same
request writes the same call, so sending it again only costs the back-off. Any other error
answer is retried as before, and the last error says what Ollama answered; only a request that
never reached Ollama says "Cannot connect". No network: httpx.post and time.sleep are fakes.
"""
from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.llm_clients.ollama_client import OllamaClient, OllamaToolCallParseError, OllamaUnavailableError
from app.routers.chat import _stream_failure

URL = "http://ollama.test"
PARSE = {"error": "XML syntax error on line 12: element <function> closed by </parameter>"}
OK = {"message": {"content": "xong", "tool_calls": []}, "prompt_eval_count": 10, "eval_count": 2}


class Wire:
    """Stands in for httpx.post and time.sleep; `answers` are (status, body) or an exception, in order."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.posts = 0
        self.sleeps: list[float] = []

    def post(self, url, json=None, timeout=None):
        self.posts += 1
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        status, body = answer
        request = httpx.Request("POST", url)
        if isinstance(body, str):
            return httpx.Response(status, text=body, request=request)
        return httpx.Response(status, json=body, request=request)

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


def call(monkeypatch, answers) -> tuple[Wire, object]:
    wire = Wire(answers)
    monkeypatch.setattr(httpx, "post", wire.post)
    monkeypatch.setattr("app.llm_clients.ollama_client.time.sleep", wire.sleep)
    client = OllamaClient(URL, chat_timeout=120.0, health_timeout=1.0, retry_count=2)
    try:
        return wire, client.chat_tools("qwen3.5:9b", [{"role": "user", "content": "x"}], [], {}, "5m")
    except Exception as error:
        return wire, error


def test_a_call_ollama_could_not_parse_is_raised_at_once_with_the_servers_words(monkeypatch):
    wire, error = call(monkeypatch, [(500, PARSE), (200, OK), (200, OK)])

    assert isinstance(error, OllamaToolCallParseError) and isinstance(error, OllamaUnavailableError)
    assert PARSE["error"] in str(error) and "Cannot connect" not in str(error)
    assert (wire.posts, wire.sleeps) == (1, []), "never sent again as is"


def test_another_server_error_is_retried_and_the_last_one_says_what_ollama_answered(monkeypatch):
    crashed = (500, {"error": "llama runner process has terminated"})
    wire, error = call(monkeypatch, [crashed, crashed, crashed])

    assert type(error) is OllamaUnavailableError
    assert str(error) == "Ollama answered 500: llama runner process has terminated"
    assert (wire.posts, wire.sleeps) == (3, [1, 3])


def test_a_retried_server_error_that_clears_answers_as_before(monkeypatch):
    wire, result = call(monkeypatch, [(503, "<html>busy</html>"), (200, OK)])

    assert result["content"] == "xong" and (wire.posts, wire.sleeps) == (2, [1])


def test_a_body_that_is_not_json_is_quoted_from_its_start(monkeypatch):
    _, error = call(monkeypatch, [(502, "Bad Gateway")] * 3)

    assert str(error) == "Ollama answered 502: Bad Gateway"


def test_the_parse_mark_on_a_client_error_is_not_a_parse_error(monkeypatch):
    wire, error = call(monkeypatch, [(400, PARSE)] * 3)

    assert type(error) is OllamaUnavailableError and str(error).startswith("Ollama answered 400: XML syntax error")
    assert wire.posts == 3


def test_only_a_request_that_never_reached_ollama_says_cannot_connect(monkeypatch):
    refused = httpx.ConnectError("refused")
    wire, error = call(monkeypatch, [refused, refused, refused])

    assert type(error) is OllamaUnavailableError and str(error) == "Cannot connect to Ollama"
    assert wire.posts == 3


def test_the_chat_stream_still_answers_ollama_unavailable_for_it():
    logged: list[tuple] = []
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(logging_service=SimpleNamespace(log_request=lambda *args, **kwargs: logged.append(args)))))

    failure = _stream_failure(request, OllamaToolCallParseError(PARSE["error"]), 0.0)

    assert failure["error_code"] == "OLLAMA_UNAVAILABLE" and logged[0][-1] == "OLLAMA_UNAVAILABLE"
