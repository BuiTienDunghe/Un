"""A small local HTTP service that turns a voice message into text (ticket 49): POST /transcribe with the
audio file as the body gives {"text": ...}. Off unless VOICE_URL is set (see tools/supervisor.py).

Built like decided_server.py, whose door and model process it reuses: this process only answers the
door and never imports the speech model, which lives in a child that starts on the first request and
exits after IDLE_SECONDS without one, because the GPU is shared with the answer model and with games.
Audio is megabytes, so the door writes it to a temporary file and tells the child the path; the file
is deleted when the answer, or the failure, comes back. Nothing about a recording or its text is kept
or logged. Binds to loopback only.

The speech model is PhoWhisper-medium (owner's pick 03/11, after small heard "alo alo" as "a rua rua lồ"
and "đếm từ 1 đến 10" as "điểm thứ một đến mời" on Discord; .scratch/future-plan/voice-survey.md), read through
transformers with PyAV decoding the recording. VOICE_MODEL_PYTHON names the interpreter the child runs
in, for a model that needs libraries this one does not have.

A sound with no speech in it (silence, a beep, a hum, noise) gets empty text, so the bot answers politely
that it heard nothing: a filter before the model (_speech_seconds) and one on what it wrote (_invented).
Both are plain signal and text arithmetic, with no extra model, and are only checked against generated
sounds: nothing here shows they keep every real voice or drop every invention.
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
# PhoWhisper-medium, pinned at 55a7e3e of vinai/PhoWhisper-medium (3,06 GB fp32 on disk, 2,2 GB on the card in fp16,
# 0,64 s for a 6 s clip warm; small was 0,8 GB and 0,32 s). Published WER, CMV-Vi / VIVOS: small 11,08 / 6,33, medium
# 8,27 / 4,97 (read speech, not Discord voices). On the owner's three Discord recordings (03/11) small heard 1 of 3
# right, medium 3 of 3, the same under fp32 and without chunking. data/ is not in the repo; small (a86b604) was deleted
# on the owner's word, and VOICE_MODEL_DIR still points the service at another folder.
MODEL_DIR = Path(os.environ.get("VOICE_MODEL_DIR") or Path(__file__).resolve().parent.parent / "data" / "models" / "phowhisper-medium")
SAMPLE_RATE = 16_000
MAX_RECORDING_SECONDS = 180.0
# What counts as a person talking (_speech_seconds). Set from synthetic sounds only, never tuned on a real
# voice; a quiet or unusual speaker may fall under them, so every one is a plain constant to change.
FRAME_SECONDS = 0.03
SPEECH_BAND = (100.0, 4000.0)
MIN_LEVEL_DBFS = -50.0
MIN_SPEECH_SECONDS = 0.3
# A frame is a steady tone when this share of its power sits within TONE_BINS bins of its strongest one.
TONE_SHARE = 0.85
TONE_BINS = 2
MIN_LEVEL_SPREAD_DB = 3.0
# What the model may write for the sound it was given (_invented).
MAX_LETTERS_PER_SECOND = 40.0
REPEATED_WORD_SHARE = 0.6
STOCK_PHRASE_SECONDS = 3.0
# Lines Whisper models are known to write for silence in Vietnamese, from the usual reports, not from this model.
STOCK_PHRASES = (
    "ghiền mì gõ",
    "đăng ký kênh",
    "subscribe cho kênh",
    "amara org",
    "hẹn gặp lại các bạn trong những video",
    "cảm ơn các bạn đã theo dõi",
)


# ── the child: holds the model, and everything it holds goes when it exits ──
class RecordingTooLong(Exception):
    """Longer than MAX_RECORDING_SECONDS by the file itself: what the sender's client declares proves nothing."""


def _decode(path: str, *, max_seconds: float = MAX_RECORDING_SECONDS) -> "numpy.ndarray":
    """The recording as 16 kHz mono floats, measured while decoding, so a long file stops here and never reaches the card."""
    import av
    import numpy

    limit = int(max_seconds * SAMPLE_RATE)
    pieces, total = [], 0
    with av.open(path) as container:
        resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
        for frame in container.decode(audio=0):
            for piece in resampler.resample(frame):
                samples = piece.to_ndarray().reshape(-1)
                total += samples.size
                if total > limit:
                    raise RecordingTooLong
                pieces.append(samples)
    return numpy.concatenate(pieces) if pieces else numpy.zeros(0, dtype=numpy.float32)


def _speech_seconds(audio: "numpy.ndarray") -> float:
    """Seconds of `audio` that could be a person talking, 0.0 when none: loud enough, not a steady tone,
    and the loudness moves the way speech does. Whisper-family models write fluent words for a beep,
    a hum or a room's noise, so the model is not asked about a recording that fails here. Cheap
    (one FFT per 30 ms), and it measures the sound only, not the language or the voice."""
    import numpy

    size = int(FRAME_SECONDS * SAMPLE_RATE)
    frames = audio[: audio.size // size * size].reshape(-1, size)
    if frames.shape[0] == 0:
        return 0.0
    level = 20 * numpy.log10(numpy.sqrt(numpy.mean(frames**2, axis=1)) + 1e-10)
    spectrum = numpy.abs(numpy.fft.rfft(frames * numpy.hanning(size), axis=1)) ** 2
    hertz = numpy.fft.rfftfreq(size, 1 / SAMPLE_RATE)
    band = spectrum[:, (hertz >= SPEECH_BAND[0]) & (hertz <= SPEECH_BAND[1])]
    peak = band.argmax(axis=1)
    near = numpy.array([row[max(0, at - TONE_BINS) : at + TONE_BINS + 1].sum() for row, at in zip(band, peak)])
    tonal = near / (band.sum(axis=1) + 1e-20) > TONE_SHARE
    speechlike = (level > MIN_LEVEL_DBFS) & ~tonal
    seconds = float(speechlike.sum()) * FRAME_SECONDS
    # Speech goes loud and soft from syllable to syllable; a hum, a siren or white noise does not.
    if seconds < MIN_SPEECH_SECONDS or float(level[speechlike].std()) < MIN_LEVEL_SPREAD_DB:
        return 0.0
    return seconds


def _invented(text: str, speech_seconds: float) -> bool:
    """Text a speech model writes when it has nothing to hear: a word said over and over, more letters
    than anyone says in that many seconds, or the stock closing lines it learned from video subtitles."""
    letters = len(text.replace(" ", ""))
    if letters > MAX_LETTERS_PER_SECOND * max(speech_seconds, 1.0):
        return True
    words = text.lower().split()
    if len(words) >= 6 and max(words.count(word) for word in set(words)) / len(words) > REPEATED_WORD_SHARE:
        return True
    plain = " ".join("".join(c if c.isalnum() or c == " " else " " for c in text.lower()).split())
    return speech_seconds < STOCK_PHRASE_SECONDS and any(phrase in plain for phrase in STOCK_PHRASES)


def _load() -> dict:
    if not MODEL_DIR.is_dir():  # Named as a repository, a missing folder would go and fetch a gigabyte.
        raise FileNotFoundError(MODEL_DIR)
    import torch
    from transformers import pipeline

    gpu = torch.cuda.is_available()
    return {
        "hear": pipeline(
            "automatic-speech-recognition",
            model=str(MODEL_DIR),
            chunk_length_s=30,
            device=0 if gpu else -1,
            dtype=torch.float16 if gpu else torch.float32,
        )
    }


def _transcribe(state: dict, path: str) -> dict:
    audio = _decode(path)
    if audio.size == 0:
        return {"text": ""}
    speech = _speech_seconds(audio)
    if speech == 0.0:  # Not worth the card, and the model would only make words up.
        return {"text": ""}
    heard = state["hear"](
        {"raw": audio, "sampling_rate": SAMPLE_RATE},
        generate_kwargs={"language": "vietnamese", "task": "transcribe"},
    )
    text = heard["text"].strip()
    return {"text": "" if _invented(text, speech) else text}


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


# ── the door ──
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
        if isinstance(reply, dict) and reply.get("error") == RecordingTooLong.__name__:
            self._send(413, {"error": "recording too long"})
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
