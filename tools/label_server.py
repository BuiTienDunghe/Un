"""The decided door's twin for a model served by Ollama (owner's pick 12/11, .scratch/memory-labels-2b/spec.md):
POST /classify {"text": ...} gives the same {label, confidence, stable, probs, model} as tools/decided_server.py,
so the labelling worker, and later the memory notes, change model by changing DECIDED_URL and nothing else.

Same question, same four options, imported from decided_server.py, and the same four rotations averaged.
The difference: decided reads its four letters' scores over the whole vocabulary, while Ollama returns only
the TOP_LOGPROBS likeliest first tokens, so a letter outside them counts as 0. The frame around the question
is this file's own, not the Fine-tune project's. Both differences go with every number comparing the two.

The worker waits on a 503 and marks the message failed on anything else, so which one is said matters.
Ollama out of reach, too slow, or cut off mid-reply: 503, it says nothing about the message. Ollama answering
with something unusable (an error code, no scores, no letter): one fixed PROBE message is asked, and if that
gets a letter the fault is this message's (500), if not it is the model's (503), so a model that never writes
a letter holds the queue instead of marking every message failed.

No model process here: Ollama holds the model and lets it go when idle. This door only asks and adds up.
Nothing a message says reaches a log. Binds to loopback only.
"""
from __future__ import annotations

import http.client
import json
import math
import os
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Run as a script, only tools/ is on the path; the decided door is a sibling package module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.decided_server import KEYS, MAX_TEXT_CHARS, OPTIONS, QUESTION  # noqa: E402
from tools.supervisor import LABEL_PORT, ROOT, read_env  # noqa: E402


def setting(name: str, default: str) -> str:
    """The window's environment first, then the repo's .env, the way the backend reads them: the supervisor
    decides from .env what to start but does not pass it to what it starts."""
    return os.environ.get(name) or read_env(ROOT / ".env").get(name) or default


PORT = LABEL_PORT  # The supervisor starts this door when DECIDED_URL names this port.
OLLAMA_URL = setting("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
MODEL = setting("LABEL_OLLAMA_MODEL", "qwen3.5:2b")
# general-small-v1's context and keep-alive in backend/app/config/model_versions.yaml, copied by hand: Ollama
# reloads a model asked for with another context, so while the answer model is the same qwen3.5:2b the two
# must ask alike to share one copy. Change both together.
NUM_CTX = int(setting("LABEL_OLLAMA_NUM_CTX", "16384"))
KEEP_ALIVE = "5m"
TOP_LOGPROBS = 20
LETTERS = "ABCD"
# Up to four asks and a probe per message; the worker gives up on a whole request at 180 s.
ASK_TIMEOUT_SECONDS = 35.0
MAX_BODY_BYTES = 100_000
CLIENT_TIMEOUT_SECONDS = 30.0
# Plainly a greeting, so any model that can answer the question at all answers it with a letter.
PROBE = "Chào cả nhà, chúc mọi người buổi sáng vui vẻ!"


class ModelUnavailable(Exception):
    """Ollama could not be heard from, which says nothing about the message: it can be asked again later."""


class BadReply(Exception):
    """Ollama answered with something that is not four scores: the probe decides whose fault it is."""


class NoLetter(BadReply):
    """The model's likeliest first tokens held none of A-D."""


class MessageFailed(Exception):
    """This message, and only this one, could not be labelled: the probe got its letter."""


def prompt(text: str, order: list[str]) -> str:
    options = "\n".join(f"{letter}. {OPTIONS[key]}" for letter, key in zip(LETTERS, order))
    return (
        f'Tin nhắn:\n"""\n{text}\n"""\n\n{QUESTION}\n{options}\n\n'
        "Chỉ trả lời bằng đúng một chữ cái: A, B, C hoặc D."
    )


def letter_probs(reply: dict) -> list[float]:
    """The first token's probability for each of A-D, renormalised over the four. A letter written with
    a space or in lower case counts as that letter; one outside the top tokens counts as 0."""
    logprobs = reply.get("logprobs") if isinstance(reply, dict) else None
    if not logprobs:
        raise BadReply("no logprobs in the reply")
    first = logprobs[0] if isinstance(logprobs, list) and isinstance(logprobs[0], dict) else {}
    candidates = first.get("top_logprobs") or [first]
    found = [0.0] * len(LETTERS)
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        token = str(candidate.get("token", "")).strip().upper()
        try:
            logprob = float(candidate["logprob"])
        except (KeyError, TypeError, ValueError):
            continue
        if len(token) == 1 and token in LETTERS:
            found[LETTERS.index(token)] += math.exp(logprob)
    total = sum(found)
    if total <= 0:
        raise NoLetter("no letter among the likeliest tokens")
    return [value / total for value in found]


def ask_ollama(content: str) -> dict:
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": content}],
        "stream": False,
        "think": False,
        "keep_alive": KEEP_ALIVE,
        "logprobs": True,
        "top_logprobs": TOP_LOGPROBS,
        "options": {"temperature": 0, "num_predict": 1, "num_ctx": NUM_CTX},
    }).encode("utf-8")
    request = urllib.request.Request(f"{OLLAMA_URL.rstrip('/')}/api/chat", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=ASK_TIMEOUT_SECONDS) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:  # Before URLError, which it is: Ollama heard and said no.
        raise BadReply(f"ollama said {error.code}") from error
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as error:
        raise ModelUnavailable(type(error).__name__) from error
    try:
        return json.loads(raw)
    except ValueError as error:
        raise BadReply("ollama reply is not JSON") from error


def classify(text: str, ask=ask_ollama) -> dict:
    text = text[:MAX_TEXT_CHARS]
    totals = {key: 0.0 for key in KEYS}
    picks = []
    for shift in range(len(KEYS)):
        order = KEYS[shift:] + KEYS[:shift]
        probs = letter_probs(ask(prompt(text, order)))
        for key, value in zip(order, probs):
            totals[key] += value / len(KEYS)
        picks.append(order[max(range(len(KEYS)), key=lambda index: probs[index])])
    best = max(totals, key=totals.get)
    return {"label": best, "confidence": round(totals[best], 4), "stable": len(set(picks)) == 1,
            "probs": {key: round(value, 4) for key, value in totals.items()}, "model": f"ollama:{MODEL}"}


def label(text: str, ask=ask_ollama) -> dict:
    """classify, with a BadReply sorted into the model's fault (ModelUnavailable) or this message's (MessageFailed)."""
    try:
        return classify(text, ask)
    except BadReply as failure:
        try:
            letter_probs(ask(prompt(PROBE, KEYS)))
        except (BadReply, ModelUnavailable) as probe_failure:
            raise ModelUnavailable(f"probe failed too: {probe_failure}") from failure
        raise MessageFailed(type(failure).__name__) from failure


class Door(ThreadingHTTPServer):
    # Threads, so that GET / answers while Ollama is loading the model for someone else.
    daemon_threads = True

    def __init__(self, address: tuple[str, int], ask=ask_ollama) -> None:
        super().__init__(address, Handler)
        self.ask = ask
        self._last_reason: str | None = None
        self._reason_lock = threading.Lock()

    def say_once(self, reason: str) -> None:
        """Why Ollama could not answer, printed when it changes: never the message, never every request."""
        with self._reason_lock:
            if reason != self._last_reason:
                print(f"label: waiting on Ollama ({reason})", flush=True)
            self._last_reason = reason

    def answered(self) -> None:
        with self._reason_lock:
            self._last_reason = None


class Handler(BaseHTTPRequestHandler):
    timeout = CLIENT_TIMEOUT_SECONDS

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if status >= 400:
            self.send_header("Connection", "close")  # An unread body must not be taken for the next request.
            self.close_connection = True
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._send(200, {"status": "ok", "model": f"ollama:{MODEL}"})

    def do_POST(self) -> None:
        if self.path != "/classify":
            self._send(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if length > MAX_BODY_BYTES:
            self._send(413, {"error": "body too large"})
            return
        try:
            data = json.loads(self.rfile.read(length) if length > 0 else b"")
            text = str(data["text"]).strip()
            if not text:
                raise ValueError("empty text")
        except OSError:  # Stalled past the timeout, or gone.
            self.close_connection = True
            return
        except (ValueError, KeyError, TypeError) as error:
            self._send(422, {"error": "empty text" if str(error) == "empty text" else type(error).__name__})
            return
        try:
            reply = label(text, self.server.ask)
        except ModelUnavailable as error:
            self.server.say_once(str(error))
            self._send(503, {"error": str(error)})
            return
        except Exception as error:  # MessageFailed, or a reply shaped like nothing above: this one message.
            # The worker records it at 0% and the queue behind it moves.
            if isinstance(error, MessageFailed):
                self.server.answered()  # The probe got its letter: the model is back, a later wait is news.
            self._send(500, {"error": str(error) if isinstance(error, MessageFailed) else type(error).__name__})
            return
        self.server.answered()
        self._send(200, reply)

    def log_message(self, *_args) -> None:
        pass  # A message's text never reaches a log.


if __name__ == "__main__":
    print(f"label: listening on 127.0.0.1:{PORT}, asking {MODEL} through Ollama", flush=True)
    Door(("127.0.0.1", PORT)).serve_forever()
