"""The 2B labeller's door (.scratch/memory-labels-2b/spec.md), with a stand-in for Ollama: no model runs here."""
from __future__ import annotations

import http.client
import json
import math
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from tools import label_server, supervisor
from tools.decided_server import KEYS, OPTIONS, QUESTION
from tools.label_server import PROBE, BadReply, Door, MessageFailed, ModelUnavailable, NoLetter, classify, label, letter_probs, prompt

SECRET = "anh Ba thích ăn phở bò tái"


def reply(*tokens: tuple[str, float], content: str = "A") -> dict:
    """An Ollama /api/chat reply whose first token's top candidates are `tokens` (token, probability)."""
    top = [{"token": token, "logprob": math.log(p), "bytes": []} for token, p in tokens]
    return {"message": {"role": "assistant", "content": content}, "logprobs": [{"token": content, "logprob": top[0]["logprob"] if top else 0.0, "top_logprobs": top}]}


NO_LETTER = reply(("Xin", 0.6), ("Tôi", 0.3), content="Xin")


def always(letter: str):
    """A model that always picks `letter`, whatever the order of the options."""
    asked = []

    def ask(content: str) -> dict:
        asked.append(content)
        return reply((letter, 0.7), *[(other, 0.1) for other in "ABCD" if other != letter])

    return ask, asked


def favours(key: str):
    """A model that always picks the option whose text is `key`'s, wherever it stands."""
    def ask(content: str) -> dict:
        for letter in "ABCD":
            if f"{letter}. {OPTIONS[key]}" in content:
                return reply((letter, 0.9), *[(other, 0.1 / 3) for other in "ABCD" if other != letter])
        raise AssertionError("option missing from the prompt")

    return ask


def only_the_probe_works(broken):
    """The probe gets a fair answer; any other message gets `broken` (a reply, or an exception to raise)."""
    fine = favours("ignore")

    def ask(content: str) -> dict:
        if PROBE in content:
            return fine(content)
        if isinstance(broken, Exception):
            raise broken
        return broken

    return ask


# ── the sums ──
def test_the_reply_keeps_the_decided_contract() -> None:
    result = classify("hôm nay cả nhóm chốt họp thứ Hai", favours("decision"))
    assert set(result) == {"label", "confidence", "stable", "probs", "model"}
    assert result["label"] == "decision" and result["stable"] is True
    assert result["confidence"] == pytest.approx(0.9, abs=1e-3)
    assert set(result["probs"]) == set(KEYS) and sum(result["probs"].values()) == pytest.approx(1.0, abs=1e-3)
    assert result["model"] == f"ollama:{label_server.MODEL}"


def test_four_asks_each_with_the_options_turned_once_more() -> None:
    ask, asked = always("A")
    result = classify("chào cả nhà", ask)
    assert len(asked) == 4
    firsts = [next(key for key in KEYS if f"A. {OPTIONS[key]}" in content) for content in asked]
    assert firsts == KEYS
    # Always the first letter means a different option each time: not stable, and spread evenly.
    assert result["stable"] is False
    assert all(value == pytest.approx(0.25, abs=1e-3) for value in result["probs"].values())


def test_same_question_and_options_as_decided() -> None:
    text = prompt("xin chào", KEYS)
    assert QUESTION in text and all(OPTIONS[key] in text for key in KEYS)


def test_long_text_is_cut_like_decided() -> None:
    ask, asked = always("B")
    classify("x" * 5000, ask)
    assert all("x" * 2000 in content and "x" * 2001 not in content for content in asked)


def test_letters_outside_the_top_count_zero_and_spacing_or_case_count() -> None:
    probs = letter_probs(reply((" a", 0.5), ("B", 0.25), ("hello", 0.2)))
    assert probs == pytest.approx([2 / 3, 1 / 3, 0.0, 0.0])


def test_no_letter_or_no_scores_is_a_bad_reply() -> None:
    with pytest.raises(NoLetter):
        letter_probs(NO_LETTER)
    for broken in ({"message": {"role": "assistant", "content": "A"}}, {"message": {"content": ""}}, {"logprobs": "garbled"}):
        with pytest.raises(BadReply):
            letter_probs(broken)


# ── whose fault: the message's (MessageFailed, 500) or the model's (ModelUnavailable, 503) ──
@pytest.mark.parametrize("broken", [NO_LETTER, {"message": {"content": "A"}}, BadReply("ollama said 500")])
def test_a_bad_reply_for_one_message_fails_only_that_message(broken) -> None:
    with pytest.raises(MessageFailed):
        label(SECRET, only_the_probe_works(broken))


@pytest.mark.parametrize("broken", [NO_LETTER, {"message": {"content": "A"}}, BadReply("ollama said 500")])
def test_a_model_that_answers_nothing_usable_holds_the_queue(broken) -> None:
    """think ignored, no scores, every message an error: the probe fails too, so the worker waits."""
    def ask(_content: str) -> dict:
        if isinstance(broken, Exception):
            raise broken
        return broken

    with pytest.raises(ModelUnavailable, match="probe failed too"):
        label(SECRET, ask)


def test_out_of_reach_is_unavailable_without_a_probe() -> None:
    asked = []

    def ask(content: str) -> dict:
        asked.append(content)
        raise ModelUnavailable("URLError")

    with pytest.raises(ModelUnavailable, match="URLError"):
        label(SECRET, ask)
    assert len(asked) == 1


# ── Ollama itself ──
def test_ollama_down_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(label_server, "OLLAMA_URL", "http://127.0.0.1:1")
    monkeypatch.setattr(label_server, "ASK_TIMEOUT_SECONDS", 5.0)
    with pytest.raises(ModelUnavailable):
        label_server.ask_ollama("A?")


class FakeOllama(BaseHTTPRequestHandler):
    seen: list[dict] = []
    mode = "ok"

    def do_POST(self) -> None:
        FakeOllama.seen.append({"path": self.path, "body": json.loads(self.rfile.read(int(self.headers["Content-Length"])))})
        if FakeOllama.mode == "cut":
            # Says a long body is coming, then dies a few bytes in, as a model process killed mid-reply.
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            self.wfile.write(b'{"mess')
            self.wfile.flush()
            self.close_connection = True
            return
        if FakeOllama.mode == "notjson":
            body, status = b"<html>proxy</html>", 200
        elif FakeOllama.mode == "missing":
            body, status = json.dumps({"error": "model not found"}).encode(), 404
        else:
            body, status = json.dumps(reply(("C", 0.8), ("A", 0.2), content="C")).encode(), 200
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args) -> None:
        pass


@pytest.fixture
def fake_ollama(monkeypatch: pytest.MonkeyPatch):
    FakeOllama.seen, FakeOllama.mode = [], "ok"
    server = HTTPServer(("127.0.0.1", 0), FakeOllama)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(label_server, "OLLAMA_URL", f"http://127.0.0.1:{server.server_address[1]}")
    monkeypatch.setattr(label_server, "ASK_TIMEOUT_SECONDS", 10.0)
    yield FakeOllama
    server.shutdown()
    server.server_close()


def test_what_is_sent_to_ollama(fake_ollama) -> None:
    label_server.ask_ollama("Tin nhắn: A?")
    sent = fake_ollama.seen[0]
    assert sent["path"] == "/api/chat"
    body = sent["body"]
    assert body["model"] == label_server.MODEL and body["stream"] is False and body["think"] is False
    assert body["logprobs"] is True and body["top_logprobs"] == label_server.TOP_LOGPROBS
    assert body["options"] == {"temperature": 0, "num_predict": 1, "num_ctx": label_server.NUM_CTX}
    assert body["keep_alive"] == label_server.KEEP_ALIVE
    assert body["messages"] == [{"role": "user", "content": "Tin nhắn: A?"}]


def test_an_error_code_or_a_page_that_is_not_json_is_a_bad_reply(fake_ollama) -> None:
    fake_ollama.mode = "missing"
    with pytest.raises(BadReply, match="404"):
        label_server.ask_ollama("A?")
    fake_ollama.mode = "notjson"
    with pytest.raises(BadReply, match="not JSON"):
        label_server.ask_ollama("A?")


def test_a_reply_cut_off_midway_is_unavailable_not_the_message(fake_ollama) -> None:
    fake_ollama.mode = "cut"
    with pytest.raises(ModelUnavailable):
        label_server.ask_ollama("A?")


# ── settings: the window first, then .env, then the default ──
def test_settings_come_from_the_window_then_dot_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text("LABEL_OLLAMA_MODEL=lfm3:1.7b\n", encoding="utf-8")
    monkeypatch.setattr(label_server, "ROOT", tmp_path)
    monkeypatch.delenv("LABEL_OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("LABEL_OLLAMA_NUM_CTX", raising=False)
    assert label_server.setting("LABEL_OLLAMA_MODEL", "qwen3.5:2b") == "lfm3:1.7b"
    assert label_server.setting("LABEL_OLLAMA_NUM_CTX", "16384") == "16384"
    monkeypatch.setenv("LABEL_OLLAMA_MODEL", "qwen3.5:2b-other")
    assert label_server.setting("LABEL_OLLAMA_MODEL", "qwen3.5:2b") == "qwen3.5:2b-other"


def test_the_door_listens_where_the_supervisor_looks() -> None:
    assert label_server.PORT == supervisor.LABEL_PORT


# ── the door ──
@pytest.fixture
def door():
    holder = {"ask": favours("fact")}
    server = Door(("127.0.0.1", 0), ask=lambda content: holder["ask"](content))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server, holder
    server.shutdown()
    server.server_close()


def call(server: Door, method: str, path: str, body: bytes | None = None) -> tuple[int, dict]:
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    connection.request(method, path, body=body, headers={"Content-Type": "application/json"} if body is not None else {})
    response = connection.getresponse()
    status, payload = response.status, json.loads(response.read())
    connection.close()
    return status, payload


def post(server: Door, text: str) -> tuple[int, dict]:
    return call(server, "POST", "/classify", json.dumps({"text": text}).encode())


def test_door_answers_like_decided(door) -> None:
    server, _ = door
    status, payload = post(server, SECRET)
    assert status == 200 and payload["label"] == "fact" and payload["stable"] is True
    status, payload = call(server, "GET", "/")
    assert status == 200 and payload["model"] == f"ollama:{label_server.MODEL}"


@pytest.mark.parametrize("body", [b"", b"not json", json.dumps({"text": "   "}).encode(), json.dumps({"nope": 1}).encode()])
def test_door_refuses_what_is_not_a_message(door, body: bytes) -> None:
    status, _ = call(door[0], "POST", "/classify", body)
    assert status == 422


def test_door_refuses_a_body_too_large(door, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(label_server, "MAX_BODY_BYTES", 10)
    assert call(door[0], "POST", "/classify", json.dumps({"text": "một câu dài hơn mười byte"}).encode())[0] == 413


def test_door_other_paths_are_not_found(door) -> None:
    assert call(door[0], "POST", "/label", json.dumps({"text": "x"}).encode())[0] == 404


def test_door_503_when_the_model_cannot_answer_500_for_one_bad_message(door) -> None:
    server, holder = door

    def down(_content: str) -> dict:
        raise ModelUnavailable("URLError")

    holder["ask"] = down
    assert post(server, "x") == (503, {"error": "URLError"})
    holder["ask"] = lambda _content: NO_LETTER
    status, payload = post(server, "x")
    assert status == 503 and payload["error"].startswith("probe failed too")
    holder["ask"] = only_the_probe_works(NO_LETTER)
    assert post(server, "x") == (500, {"error": "NoLetter"})
    holder["ask"] = only_the_probe_works(BadReply("ollama said 500"))
    assert post(server, "x") == (500, {"error": "BadReply"})


def test_a_message_never_reaches_the_console_or_an_error(door, capsys: pytest.CaptureFixture) -> None:
    server, holder = door
    assert SECRET not in json.dumps(post(server, SECRET)[1], ensure_ascii=False)

    def down(_content: str) -> dict:
        raise ModelUnavailable("URLError")

    holder["ask"] = down
    post(server, SECRET)
    post(server, SECRET)
    holder["ask"] = only_the_probe_works(NO_LETTER)
    assert SECRET not in json.dumps(post(server, SECRET)[1], ensure_ascii=False)
    out = capsys.readouterr()
    assert SECRET not in out.out and SECRET not in out.err
    assert out.out.count("waiting on Ollama") == 1  # Said when it changes, not on every request.


def test_the_door_imports_no_model_library() -> None:
    code = "import sys, tools.label_server; print([m for m in ('torch', 'transformers', 'peft', 'httpx') if m in sys.modules])"
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent)
    assert done.stdout.strip() == "[]", done.stderr
