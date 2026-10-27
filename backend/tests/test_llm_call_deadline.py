"""Model calls inside an agent turn honour its deadline (ticket 16, commit 2).

Before this, a call waited chat_timeout (120 s) and was retried retry_count (2) times,
so one call could take 360 s and an agent answer ~24 minutes. Under call_deadline a
request waits at most what is left, no retry starts after the deadline, and no
back-off sleep runs past it. Outside one, nothing changes. No network: httpx.post,
time.sleep and the deadline's clock are fakes.
"""
from __future__ import annotations

import httpx
import pytest

from app.llm_clients import deadline as deadline_module
from app.llm_clients.deadline import ModelCallTimeoutError, call_deadline, request_timeout
from app.llm_clients.deepseek_client import DeepSeekClient, DeepSeekTimeoutError
from app.llm_clients.gemini_client import GeminiClient, GeminiTimeoutError
from app.llm_clients.ollama_client import OllamaClient, OllamaTimeoutError

OK = {"message": {"content": "xong", "tool_calls": []}}


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Wire:
    """Stands in for httpx.post and time.sleep; `answers` are returned or raised in order."""

    def __init__(self, clock: Clock, answers: list, cost: float = 0.0) -> None:
        self.clock, self.answers, self.cost = clock, list(answers), cost
        self.timeouts: list[float] = []
        self.sleeps: list[float] = []

    def post(self, url, json=None, timeout=None, **kwargs):
        self.timeouts.append(timeout)
        self.clock.now += self.cost
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(200, json=answer, request=httpx.Request("POST", url))

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.clock.now += seconds


@pytest.fixture
def clock(monkeypatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(deadline_module.time, "monotonic", fake)
    return fake


def wire(monkeypatch, clock: Clock, answers: list, cost: float = 0.0) -> Wire:
    fake = Wire(clock, answers, cost)
    monkeypatch.setattr(httpx, "post", fake.post)
    monkeypatch.setattr("app.llm_clients.ollama_client.time.sleep", fake.sleep)
    monkeypatch.setattr("app.llm_clients.gemini_client.time.sleep", fake.sleep)
    monkeypatch.setattr("app.llm_clients.deepseek_client.time.sleep", fake.sleep)
    return fake


def ollama() -> OllamaClient:
    return OllamaClient("http://ollama", chat_timeout=120.0, health_timeout=5.0, retry_count=2)


def test_without_a_deadline_a_call_waits_its_own_timeout(monkeypatch, clock):
    calls = wire(monkeypatch, clock, [OK])
    ollama().chat("m", [], {}, "5m")
    assert calls.timeouts == [120.0]


def test_inside_a_deadline_a_call_waits_only_what_is_left(monkeypatch, clock):
    calls = wire(monkeypatch, clock, [OK, OK])
    with call_deadline(clock.now + 7.5):
        ollama().chat("m", [], {}, "5m")
        ollama().chat_tools("m", [], [], {}, "5m")
    assert calls.timeouts == [7.5, 7.5]


def test_a_passed_deadline_sends_nothing(monkeypatch, clock):
    calls = wire(monkeypatch, clock, [OK])
    with call_deadline(clock.now - 1), pytest.raises(OllamaTimeoutError, match="budget is spent"):
        ollama().chat_tools("m", [], [], {}, "5m")
    assert calls.timeouts == []


def test_no_retry_starts_once_a_timeout_has_used_up_the_deadline(monkeypatch, clock):
    timed_out = httpx.ReadTimeout("slow")
    calls = wire(monkeypatch, clock, [timed_out, timed_out, timed_out], cost=10.0)
    with call_deadline(clock.now + 10), pytest.raises(OllamaTimeoutError):
        ollama().chat("m", [], {}, "5m")
    assert len(calls.timeouts) == 1 and calls.sleeps == []


def test_outside_a_deadline_the_old_retries_are_untouched(monkeypatch, clock):
    timed_out = httpx.ReadTimeout("slow")
    calls = wire(monkeypatch, clock, [timed_out, timed_out, timed_out])
    with pytest.raises(OllamaTimeoutError):
        ollama().chat("m", [], {}, "5m")
    assert calls.timeouts == [120.0] * 3 and calls.sleeps == [1, 3]


def test_no_back_off_sleeps_past_the_deadline(monkeypatch, clock):
    refused = httpx.ConnectError("refused")
    calls = wire(monkeypatch, clock, [refused, refused, refused])
    # 2 s left: the 1 s back-off fits, the 3 s one does not.
    with call_deadline(clock.now + 2), pytest.raises(OllamaTimeoutError, match="time budget"):
        ollama().chat("m", [], {}, "5m")
    assert calls.sleeps == [1] and len(calls.timeouts) == 2


@pytest.mark.parametrize(
    ("client", "error"),
    [
        (GeminiClient("key", chat_timeout=60.0), GeminiTimeoutError),
        (DeepSeekClient("key", chat_timeout=60.0), DeepSeekTimeoutError),
    ],
)
def test_the_cloud_clients_honour_it_too(monkeypatch, clock, client, error):
    calls = wire(monkeypatch, clock, [])
    with call_deadline(clock.now - 1), pytest.raises(error):
        client.chat("m", [{"role": "user", "content": "chào"}])
    assert calls.timeouts == []


def test_every_provider_timeout_is_one_kind_of_error():
    for error in (OllamaTimeoutError, GeminiTimeoutError, DeepSeekTimeoutError):
        assert issubclass(error, ModelCallTimeoutError)


def test_the_deadline_ends_with_its_block(clock):
    with call_deadline(clock.now + 3):
        assert request_timeout(120.0) == 3
    assert request_timeout(120.0) == 120.0
