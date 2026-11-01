"""A small local HTTP service around the owner's decided model, run inside WSL with the Fine-tune
environment (see run-decided.bat): POST /classify {"text": ...} gives the compartment a message
belongs in, with probabilities.

Two processes, because unloading inside one leaves 459 MiB on the GPU and 1.6 GB of RAM (measured
31/10): this one only answers the door and never imports the model's libraries, and the model lives
in a child that starts on the first request and exits after IDLE_SECONDS without one. The GPU is
shared with the answer model and with games. Each message is asked four times with the options
rotated, since the order moved 7 of 48 answers in the first trial. Binds to loopback only.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

FINE_TUNE = Path(os.environ.get("DECIDED_FINE_TUNE", "/mnt/c/Users/dungbt06/Fine-tune"))
ADAPTER = FINE_TUNE / "results/train_2b/train/2b-gop-s1s2/adapter"
BASE = "Qwen/Qwen3-1.7B"
REVISION = "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e"
MODEL_NAME = "decided-2b-gop-s1s2"
PORT = 8377
IDLE_SECONDS = 300
# A cold start took 92.6 s; the worker gives up on a request at 180.
REPLY_TIMEOUT_SECONDS = 150.0
MAX_TEXT_CHARS = 2000
QUESTION = "Tin nhắn trên nên được xử lý thế nào trong trí nhớ của trợ lý?"
OPTIONS = {
    "fact": "Lưu lại: người viết cho biết một sự thật, sở thích hoặc thông tin lâu dài về bản thân",
    "decision": "Lưu lại: cả nhóm vừa chốt một quyết định hoặc quy ước chung",
    "joke": "Lưu vào kho câu đùa: đây là câu nói đùa, không phải sự thật",
    "ignore": "Không lưu: chào hỏi, câu hỏi hoặc chuyện qua đường",
}
KEYS = list(OPTIONS)


# ── the child: holds the model, and everything it holds goes when it exits ──
def _load() -> dict:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    sys.path.insert(0, str(FINE_TUNE / "scripts"))
    os.chdir(FINE_TUNE)
    from common import CONFIG, load_json, render_prompt

    tok = AutoTokenizer.from_pretrained(BASE, revision=REVISION)
    model = AutoModelForCausalLM.from_pretrained(BASE, revision=REVISION, dtype=torch.bfloat16, device_map="cuda", attn_implementation="sdpa")
    model = PeftModel.from_pretrained(model, str(ADAPTER)).merge_and_unload().eval()
    return dict(
        torch=torch, tok=tok, model=model, render=render_prompt, frames=load_json(CONFIG / "prompt_frames.json"),
        letters=[tok.encode(letter, add_special_tokens=False)[0] for letter in "ABCD"],
    )


def _classify(state: dict, text: str) -> dict:
    torch = state["torch"]
    totals = {key: 0.0 for key in KEYS}
    picks = []
    for shift in range(len(KEYS)):
        order = KEYS[shift:] + KEYS[:shift]
        row = {"state": text[:MAX_TEXT_CHARS], "question": QUESTION, "options": [OPTIONS[key] for key in order], "lang": "vi"}
        prompt = state["render"](row, state["tok"], state["frames"])
        inputs = state["tok"](prompt, return_tensors="pt", add_special_tokens=False).to(state["model"].device)
        with torch.no_grad():
            logits = state["model"](**inputs).logits[0, -1].float()
        probs = torch.softmax(logits[state["letters"]], -1).tolist()
        for key, value in zip(order, probs):
            totals[key] += value / len(KEYS)
        picks.append(order[max(range(len(KEYS)), key=lambda index: probs[index])])
    best = max(totals, key=totals.get)
    return {"label": best, "confidence": round(totals[best], 4), "stable": len(set(picks)) == 1,
            "probs": {key: round(value, 4) for key, value in totals.items()}, "model": MODEL_NAME}


def model_process() -> int:
    """Reads one message per line, replies one line each, and exits when the door closes the pipe."""
    replies = os.fdopen(os.dup(1), "w", encoding="utf-8")
    os.dup2(2, 1)  # A library printing to stdout must not land in the replies.
    state = _load()
    for line in sys.stdin:
        try:
            reply = _classify(state, json.loads(line)["text"])
        except state["torch"].cuda.OutOfMemoryError:
            raise  # The GPU, not the message: the door will say so, and the message waits.
        except Exception as error:  # This one message; the queue behind it must move.
            reply = {"error": type(error).__name__}
        replies.write(json.dumps(reply, ensure_ascii=False) + "\n")
        replies.flush()
    return 0


# ── the door ──
class ModelUnavailable(Exception):
    """The model could not answer, which says nothing about the message: it can be asked again later."""


class ModelProcess:
    def __init__(self, command: list[str], idle_seconds: float = IDLE_SECONDS, reply_timeout: float = REPLY_TIMEOUT_SECONDS, name: str = "decided") -> None:
        self.command = command
        self.name = name
        self.idle_seconds = idle_seconds
        self.reply_timeout = reply_timeout
        self._lock = threading.Lock()
        self._child: subprocess.Popen | None = None
        self._replies: queue.Queue = queue.Queue()
        self._last_used = 0.0

    @property
    def loaded(self) -> bool:
        return self._child is not None and self._child.poll() is None

    def _start(self) -> None:
        self._child = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, encoding="utf-8")
        self._replies = queue.Queue()
        # A thread, because a blocking read could not be given a deadline.
        threading.Thread(target=self._pump, args=(self._child, self._replies), daemon=True).start()

    @staticmethod
    def _pump(child: subprocess.Popen, replies: queue.Queue) -> None:
        for line in child.stdout:
            replies.put(line)
        replies.put(None)

    def _stop(self) -> None:
        child, self._child = self._child, None
        if child is None:
            return
        try:
            child.stdin.close()
            child.wait(timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            child.kill()
            child.wait()

    def classify(self, text: str) -> dict:
        return self.ask({"text": text})

    def ask(self, request: dict) -> dict:
        """One line out, one line back. The line stays small whatever the job (the voice door sends a
        path, never audio), since a write to a child that is not reading would block with the lock held."""
        with self._lock:
            if not self.loaded:
                self._stop()
                self._start()
            # Before the work, so a failure just after a slow load does not unload at once.
            self._last_used = time.monotonic()
            try:
                self._child.stdin.write(json.dumps(request) + "\n")
                self._child.stdin.flush()
                reply = self._replies.get(timeout=self.reply_timeout)
            except queue.Empty as error:
                self._child.kill()  # Hung: closing the pipe would not reach it.
                self._stop()
                raise ModelUnavailable("no reply in time") from error
            except OSError as error:
                self._stop()
                raise ModelUnavailable(type(error).__name__) from error
            if reply is None:
                self._stop()
                raise ModelUnavailable("the model process exited")
            self._last_used = time.monotonic()
            return json.loads(reply)

    def stop_if_idle(self) -> bool:
        with self._lock:
            if self.loaded and time.monotonic() - self._last_used > self.idle_seconds:
                self._stop()
                return True
            return False

    def watch_idle(self, every_seconds: float = 30) -> None:
        while True:
            time.sleep(every_seconds)
            if self.stop_if_idle():
                print(f"{self.name}: model process exited after idle", flush=True)


MODEL = ModelProcess([sys.executable, "-u", str(Path(__file__).resolve()), "--model-process"])


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._send(200, {"status": "ok", "model": MODEL_NAME, "loaded": MODEL.loaded})

    def do_POST(self) -> None:
        if self.path != "/classify":
            self._send(404, {"error": "not found"})
            return
        try:
            data = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 100_000)))
            text = str(data["text"]).strip()
            if not text:
                raise ValueError("empty text")
        except (ValueError, KeyError, TypeError) as error:
            self._send(422, {"error": str(error)})
            return
        try:
            reply = MODEL.classify(text)
        except ModelUnavailable as error:
            self._send(503, {"error": str(error)})
            return
        self._send(500 if "error" in reply else 200, reply)

    def log_message(self, *_args) -> None:
        pass  # A message's text never reaches a log.


if __name__ == "__main__":
    if "--model-process" in sys.argv:
        raise SystemExit(model_process())
    threading.Thread(target=MODEL.watch_idle, daemon=True).start()
    print(f"decided: listening on 127.0.0.1:{PORT}, the model starts on first use", flush=True)
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
