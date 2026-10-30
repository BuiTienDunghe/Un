"""A small local HTTP service around the owner's decided model, run inside WSL with the Fine-tune
environment (see run-decided.bat): POST /classify {"text": ...} gives the compartment a message
belongs in, with probabilities. The weights load on the first request and leave the GPU after
IDLE_SECONDS without one, because the GPU is shared with the answer model and with games.
Each message is asked four times with the options rotated, since the order moved 7 of 48 answers
in the first trial. Binds to loopback only.
"""
from __future__ import annotations

import json
import os
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
MAX_TEXT_CHARS = 2000
QUESTION = "Tin nhắn trên nên được xử lý thế nào trong trí nhớ của trợ lý?"
OPTIONS = {
    "fact": "Lưu lại: người viết cho biết một sự thật, sở thích hoặc thông tin lâu dài về bản thân",
    "decision": "Lưu lại: cả nhóm vừa chốt một quyết định hoặc quy ước chung",
    "joke": "Lưu vào kho câu đùa: đây là câu nói đùa, không phải sự thật",
    "ignore": "Không lưu: chào hỏi, câu hỏi hoặc chuyện qua đường",
}
KEYS = list(OPTIONS)
_lock = threading.Lock()
_loaded: dict = {}
_last_used = 0.0


def _load() -> dict:
    if _loaded:
        return _loaded
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    sys.path.insert(0, str(FINE_TUNE / "scripts"))
    os.chdir(FINE_TUNE)
    from common import CONFIG, load_json, render_prompt

    tok = AutoTokenizer.from_pretrained(BASE, revision=REVISION)
    model = AutoModelForCausalLM.from_pretrained(BASE, revision=REVISION, dtype=torch.bfloat16, device_map="cuda", attn_implementation="sdpa")
    model = PeftModel.from_pretrained(model, str(ADAPTER)).merge_and_unload().eval()
    _loaded.update(
        torch=torch, tok=tok, model=model, render=render_prompt, frames=load_json(CONFIG / "prompt_frames.json"),
        letters=[tok.encode(letter, add_special_tokens=False)[0] for letter in "ABCD"],
    )
    return _loaded


def _unload_when_idle() -> None:
    global _last_used
    while True:
        time.sleep(30)
        with _lock:
            if _loaded and time.monotonic() - _last_used > IDLE_SECONDS:
                torch = _loaded["torch"]
                _loaded.clear()
                torch.cuda.empty_cache()
                print("decided: unloaded after idle", flush=True)


def classify(text: str) -> dict:
    global _last_used
    with _lock:
        state = _load()
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
        _last_used = time.monotonic()
    best = max(totals, key=totals.get)
    return {"label": best, "confidence": round(totals[best], 4), "stable": len(set(picks)) == 1,
            "probs": {key: round(value, 4) for key, value in totals.items()}, "model": MODEL_NAME}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._send(200, {"status": "ok", "model": MODEL_NAME, "loaded": bool(_loaded)})

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
        self._send(200, classify(text))

    def log_message(self, *_args) -> None:
        pass  # A message's text never reaches a log.


if __name__ == "__main__":
    threading.Thread(target=_unload_when_idle, daemon=True).start()
    print(f"decided: listening on 127.0.0.1:{PORT}, weights load on first use", flush=True)
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
