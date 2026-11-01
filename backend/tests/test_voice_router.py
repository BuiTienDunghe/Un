"""Ticket 49: POST /voice/transcribe hands a recording to the local speech service. Off without VOICE_URL,
and a service that is down, slow or wrong is an answer for the bot, never a crash. No database: the
router is mounted on its own small app, and the speech service is a stand-in."""
from __future__ import annotations

import base64
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.routers import voice


def make_client(url: str | None = "http://127.0.0.1:8378", api_key: str = "") -> TestClient:
    app = FastAPI()
    app.include_router(voice.router)
    app.state.settings = SimpleNamespace(voice_url=url, local_ai_api_key=api_key, local_ai_auth_enabled=False)
    return TestClient(app)


def audio(size: int = 100) -> dict:
    return {"audio_base64": base64.b64encode(b"x" * size).decode("ascii")}


class Upstream:
    def __init__(self, response: httpx.Response | Exception) -> None:
        self.response = response
        self.calls: list[tuple[str, bytes]] = []

    def __call__(self, url: str, *, content: bytes, timeout: float) -> httpx.Response:
        self.calls.append((url, content))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def with_upstream(monkeypatch: pytest.MonkeyPatch, response: httpx.Response | Exception) -> Upstream:
    upstream = Upstream(response)
    monkeypatch.setattr(voice.httpx, "post", upstream)
    return upstream


def test_off_by_default() -> None:
    assert Settings.model_fields["voice_url"].default is None
    response = make_client(url=None).post("/voice/transcribe", json=audio())
    assert response.status_code == 501
    assert response.json()["detail"]["error_code"] == "VOICE_NOT_ENABLED"


def test_the_recording_goes_to_the_service_as_bytes_and_the_words_come_back(monkeypatch) -> None:
    upstream = with_upstream(monkeypatch, httpx.Response(200, json={"text": "  mai trời mưa không  ", "model": "m"}))
    response = make_client("http://127.0.0.1:8378/").post("/voice/transcribe", json=audio(321))
    assert response.status_code == 200 and response.json() == {"text": "mai trời mưa không"}
    assert upstream.calls == [("http://127.0.0.1:8378/transcribe", b"x" * 321)]


def test_a_service_that_is_down_is_a_502_not_a_crash(monkeypatch) -> None:
    with_upstream(monkeypatch, httpx.ConnectError("refused"))
    response = make_client().post("/voice/transcribe", json=audio())
    assert response.status_code == 502 and response.json()["detail"]["error_code"] == "VOICE_UNAVAILABLE"


def test_a_service_that_times_out_is_a_502(monkeypatch) -> None:
    with_upstream(monkeypatch, httpx.ReadTimeout("slow"))
    assert make_client().post("/voice/transcribe", json=audio()).status_code == 502


@pytest.mark.parametrize("status_code", [500, 503])
def test_a_service_that_fails_is_a_502(monkeypatch, status_code: int) -> None:
    with_upstream(monkeypatch, httpx.Response(status_code, json={"error": "the model process exited"}))
    response = make_client().post("/voice/transcribe", json=audio())
    assert response.status_code == 502 and response.json()["detail"]["error_code"] == "VOICE_FAILED"


@pytest.mark.parametrize("body", [{"text": 5}, {"words": "x"}, ["x"]])
def test_an_unreadable_answer_is_a_502(monkeypatch, body) -> None:
    with_upstream(monkeypatch, httpx.Response(200, json=body))
    assert make_client().post("/voice/transcribe", json=audio()).status_code == 502
    with_upstream(monkeypatch, httpx.Response(200, content=b"<html>"))
    assert make_client().post("/voice/transcribe", json=audio()).status_code == 502


def test_silence_is_an_empty_text_not_an_error(monkeypatch) -> None:
    with_upstream(monkeypatch, httpx.Response(200, json={"text": ""}))
    assert make_client().post("/voice/transcribe", json=audio()).json() == {"text": ""}


def test_a_recording_too_large_never_reaches_the_service(monkeypatch) -> None:
    upstream = with_upstream(monkeypatch, httpx.Response(200, json={"text": "x"}))
    response = make_client().post("/voice/transcribe", json=audio(voice.MAX_AUDIO_BYTES + 1))
    assert response.status_code == 413 and upstream.calls == []


def test_something_that_is_not_base64_never_reaches_the_service(monkeypatch) -> None:
    upstream = with_upstream(monkeypatch, httpx.Response(200, json={"text": "x"}))
    response = make_client().post("/voice/transcribe", json={"audio_base64": "***not base64***"})
    assert response.status_code == 422 and upstream.calls == []


def test_the_api_key_is_required_when_one_is_set(monkeypatch) -> None:
    upstream = with_upstream(monkeypatch, httpx.Response(200, json={"text": "x"}))
    client = make_client(api_key="secret-key")
    assert client.post("/voice/transcribe", json=audio()).status_code == 401
    assert upstream.calls == []
    assert client.post("/voice/transcribe", json=audio(), headers={"X-API-Key": "secret-key"}).status_code == 200
