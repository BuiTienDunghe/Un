"""A small local HTTP service that turns a voice message into text (ticket 49): POST /transcribe with the
audio file as the body gives {"text": ...}. Off unless VOICE_URL is set (see tools/supervisor.py).

Built like decided_server.py, whose door and model process it reuses: this process only answers the
door and never imports the speech model, which lives in a child that starts on the first request and
exits after IDLE_SECONDS without one, because the GPU is shared with the answer model and with games.
Audio is megabytes, so the door writes it to a temporary file and tells the child the path; the file
is deleted when the answer, or the failure, comes back. Nothing about a recording or its text is kept
or logged. Binds to loopback only.

The speech model is not chosen yet (.scratch/future-plan/voice-survey.md): _load below is the one place
that changes when it is. VOICE_MODEL_PYTHON names the interpreter the child runs in, for a model that
needs libraries this one does not have.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Run as a script, only tools/ is on the path; the decided door is a sibling package module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.decided_server import IDLE_SECONDS, ModelProcess, ModelUnavailable  # noqa: E402

PORT = 8378
# The bot refuses a recording above this before it ever gets here; the door does not trust that.
MAX_AUDIO_BYTES = 8 * 1024 * 1024
# A cold start loads the weights; the backend gives up on a request after 180.
REPLY_TIMEOUT_SECONDS = 150.0
# How long a client may stall mid-request. One slow upload must not hold the door shut.
CLIENT_TIMEOUT_SECONDS = 30.0


# â”€â”€ the child: holds the model, and everything it holds goes when it exits â”€â”€
def _load() -> dict:
    raise NotImplementedError("no speech model is chosen yet (ticket 49): see .scratch/future-plan/voice-survey.md")


def _transcribe(state: dict, path: str) -> dict:
    raise NotImplementedError


def model_process() -> int:
    """Reads one request per line ({"path": ...}), replies one line each, and exits when the door closes the pipe."""
    replies = os.fdopen(os.dup(1), "w", encoding="utf-8")
    os.dup2(2, 1)  # A library printing to stdout must not land in the replies.
    state = _load()
    for line in sys.stdin:
        try:
            reply = _transcribe(state, json.loads(line)["path"])
        except Exception as error:  # This one recording; the queue behind it must move.
            reply = {"error": type(error).__name__}
        replies.write(json.dumps(reply, ensure_ascii=False) + "\n")
        replies.flush()
    return 0


# â”€â”€ the door â”€â”€
def transcribe(model: ModelProcess, audio: bytes) -> dict:
    """The child's reply for these bytes. The temporary file is gone whichever way this ends."""
    handle = tempfile.NamedTemporaryFile(prefix="voice-", suffix=".audio", delete=False)
    try:
        with handle:
            handle.write(audio)
        return model.ask({"path": handle.name})
    finally:
        try:
            Path(handle.name).unlink(missing_ok=True)
        except OSError:
            pass  # Still open in a child that is being killed: the temp folder's cleanup gets it.


class Door(ThreadingHTTPServer):
    # Threads, so that /health answers while a long recording is being heard.
    daemon_threads = True

    def __init__(self, address: tuple[str, int], model: ModelProcess) -> None:
        super().__init__(address, Handler)
        self.model = model


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
        self._send(200, {"status": "ok", "loaded": self.server.model.loaded})

    def do_POST(self) -> None:
        if self.path != "/transcribe":
            self._send(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if length <= 0:
            self._send(422, {"error": "empty audio"})
            return
        if length > MAX_AUDIO_BYTES:
            self._send(413, {"error": "audio too large"})
            return
        try:
            audio = self.rfile.read(length)
        except OSError:  # Stalled past the timeout, or gone.
            self.close_connection = True
            return
        if len(audio) < length:
            self._send(422, {"error": "audio cut short"})
            return
        try:
            reply = transcribe(self.server.model, audio)
        except ModelUnavailable as error:
            self._send(503, {"error": str(error)})
            return
        except (OSError, ValueError) as error:  # No room for the temporary file, or a reply that is not JSON.
            self._send(500, {"error": type(error).__name__})
            return
        if not isinstance(reply, dict) or "error" in reply or not isinstance(reply.get("text"), str):
            self._send(500, {"error": reply.get("error", "bad reply") if isinstance(reply, dict) else "bad reply"})
            return
        self._send(200, reply)

    def log_message(self, *_args) -> None:
        pass  # What a person said never reaches a log.


MODEL = ModelProcess(
    [os.environ.get("VOICE_MODEL_PYTHON") or sys.executable, "-u", str(Path(__file__).resolve()), "--model-process"],
    idle_seconds=IDLE_SECONDS,
    reply_timeout=REPLY_TIMEOUT_SECONDS,
    name="voice",
)


if __name__ == "__main__":
    if "--model-process" in sys.argv:
        raise SystemExit(model_process())
    threading.Thread(target=MODEL.watch_idle, daemon=True).start()
    print(f"voice: listening on 127.0.0.1:{PORT}, the model starts on first use", flush=True)
    Door(("127.0.0.1", PORT), MODEL).serve_forever()
