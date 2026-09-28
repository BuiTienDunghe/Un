"""An OCR answer that never ended its turn is rejected, not indexed.

On Ollama 0.34.x (measured 0.34.2 and 0.34.4, 09/2026) glm-ocr:latest ignored its real end token and
looped: dense pages came back as a 500 "token repeat limit reached", sparse ones
as 200 with tens of thousands of repeated characters. Both are deterministic at
OCR temperatures, so they are never retried, and the page keeps its native text.
"""
from pathlib import Path

import httpx
import pytest
from loguru import logger

from app.llm_clients.ollama_client import OllamaClient, OllamaIncompleteOutputError
from app.parsers.smart_parser import SmartParser
from app.services.model_router import ModelRouter


class _Reply:
    def __init__(self, status_code: int, body: dict, text: str = "") -> None:
        self.status_code, self._body, self.text = status_code, body, text

    def json(self) -> dict:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=httpx.Request("POST", "http://x"), response=httpx.Response(self.status_code))


def _client(monkeypatch, *replies: _Reply) -> tuple[OllamaClient, list[dict]]:
    sent: list[dict] = []
    queue = list(replies)

    def fake_post(url, json, timeout):
        sent.append(json)
        return queue.pop(0)

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr("app.llm_clients.ollama_client.time.sleep", lambda seconds: None)
    return OllamaClient("http://ollama", chat_timeout=5, health_timeout=1, retry_count=2), sent


def test_answer_that_ran_to_num_predict_is_rejected_once(monkeypatch):
    client, sent = _client(monkeypatch, _Reply(200, {"done_reason": "length", "message": {"content": "page\n```\n```\n```"}}))
    with pytest.raises(OllamaIncompleteOutputError, match="num_predict"):
        client.vision_chat("m", "Text Recognition:", ["png"], {"num_predict": 4096}, "5m")
    assert len(sent) == 1, "a loop is deterministic; retrying costs the same minute again"


def test_repeat_limit_abort_is_rejected_without_retry(monkeypatch):
    body = '{"error":"prediction aborted, token repeat limit reached"}'
    client, sent = _client(monkeypatch, _Reply(500, {}, text=body))
    with pytest.raises(OllamaIncompleteOutputError, match="repeat limit"):
        client.vision_chat("m", "Text Recognition:", ["png"], {}, "5m")
    assert len(sent) == 1


def test_other_server_errors_are_still_retried(monkeypatch):
    client, sent = _client(monkeypatch, _Reply(500, {}, text="out of memory"), _Reply(200, {"done_reason": "stop", "message": {"content": "ok"}}))
    assert client.vision_chat("m", "Text Recognition:", ["png"], {}, "5m") == "ok"
    assert len(sent) == 2


def test_router_sends_the_ocr_cap_as_num_predict(monkeypatch):
    client, sent = _client(monkeypatch, _Reply(200, {"done_reason": "stop", "message": {"content": "text"}}))
    router = ModelRouter({"ollama": client}, {"ocr": {"name": "local-ai/glm-ocr:eot-v1", "enabled": True, "context": 16384, "temperature": 0.1, "max_tokens": 4096}})
    assert router.ocr("png") == ("text", "local-ai/glm-ocr:eot-v1")
    assert sent[0]["options"] == {"temperature": 0.1, "num_ctx": 16384, "num_predict": 4096}


def test_rejected_page_keeps_native_text_and_leaves_a_log_line(monkeypatch, tmp_path: Path):
    parser = SmartParser.__new__(SmartParser)
    parser.ocr_service = object(); parser.ocr_config = {"enabled": True, "min_text_characters": 80, "min_alphanumeric_ratio": 0.45}; parser.last_warnings = []

    def looping(self, path, numbers):
        raise OllamaIncompleteOutputError("m reached num_predict without ending its turn (38778 chars discarded)")

    monkeypatch.setattr("app.parsers.ocr_parser.OcrParser.parse_pages", looping)
    lines: list[str] = []
    sink = logger.add(lambda message: lines.append(str(message)), level="WARNING")
    try:
        result = parser._apply_ocr_fallback(tmp_path / "x.pdf", [(1, "cover", "native")])
    finally:
        logger.remove(sink)
    assert result == [(1, "cover", "native")]
    assert parser.last_warnings and "38778 chars discarded" in parser.last_warnings[0]
    assert any("OCR failed on page 1" in line for line in lines)
