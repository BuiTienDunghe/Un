"""The voice door (ticket 49), with a stand-in for the speech model: recordings reach the model as a
path, never through the pipe, and the temporary file is gone however the request ends."""
from __future__ import annotations

import http.client
import json
import socket
import sys
import tempfile
import textwrap
import threading
import time
from pathlib import Path

import pytest

from tools import voice_server
from tools.decided_server import ModelProcess
from tools.voice_server import MAX_AUDIO_BYTES, Door, Handler


def fake_model(tmp_path: Path, body: str, **options) -> ModelProcess:
    path = tmp_path / "model.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return ModelProcess([sys.executable, "-u", str(path)], **options)


# Hears "the recording is N bytes" by opening the file it was told about.
HEARS = """
    import json, sys
    for line in sys.stdin:
        path = json.loads(line)["path"]
        with open(path, "rb") as audio:
            size = len(audio.read())
        print(json.dumps({"text": f"nghe được {size} byte", "model": "fake"}), flush=True)
"""


@pytest.fixture
def spool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Where temporary files go, so a test can see whether one was left behind."""
    folder = tmp_path / "spool"
    folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(folder))
    return folder


@pytest.fixture
def serve():
    started: list[tuple[Door, ModelProcess]] = []

    def start(model: ModelProcess) -> Door:
        door = Door(("127.0.0.1", 0), model)
        threading.Thread(target=door.serve_forever, daemon=True).start()
        started.append((door, model))
        return door

    yield start
    for door, model in started:
        door.shutdown()
        door.server_close()
        model._stop()


def post(door: Door, body: bytes, path: str = "/transcribe") -> tuple[int, dict]:
    connection = http.client.HTTPConnection("127.0.0.1", door.server_address[1], timeout=60)
    try:
        connection.request("POST", path, body=body)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def test_a_recording_is_heard_and_its_file_is_gone(tmp_path: Path, spool: Path, serve) -> None:
    door = serve(fake_model(tmp_path, HEARS))
    status, reply = post(door, b"x" * 5000)
    assert (status, reply["text"]) == (200, "nghe được 5000 byte")
    assert list(spool.iterdir()) == []


def test_a_recording_is_not_sent_through_the_pipe(tmp_path: Path, spool: Path, serve) -> None:
    """A child that never reads its input, given the largest recording: the request must end at the
    deadline, not hang on a write into a full pipe with the lock held."""
    door = serve(fake_model(tmp_path, "import time; time.sleep(60)", reply_timeout=1.0))
    began = time.monotonic()
    status, _ = post(door, b"x" * MAX_AUDIO_BYTES)
    assert status == 503 and time.monotonic() - began < 30
    assert list(spool.iterdir()) == []
    assert not door.model.loaded


def test_a_model_that_cannot_start_is_a_503_and_leaves_nothing(tmp_path: Path, spool: Path, serve) -> None:
    door = serve(fake_model(tmp_path, "import sys; sys.exit(3)"))
    assert post(door, b"abc")[0] == 503
    assert post(door, b"abc")[0] == 503  # Asked again, not stuck.
    assert list(spool.iterdir()) == []


def test_a_recording_too_long_by_the_file_is_a_413(tmp_path: Path, spool: Path, serve) -> None:
    door = serve(fake_model(tmp_path, 'import sys\nfor line in sys.stdin:\n    print(\'{"error": "RecordingTooLong"}\', flush=True)\n'))
    assert post(door, b"abc")[0] == 413
    assert list(spool.iterdir()) == []


def _opus(path: Path, seconds: int) -> None:
    av = pytest.importorskip("av")
    numpy = pytest.importorskip("numpy")
    with av.open(str(path), "w", format="ogg") as container:
        stream = container.add_stream("libopus", rate=48000, layout="mono")
        silence = numpy.zeros((1, 960), dtype=numpy.float32)
        for index in range(seconds * 50):
            frame = av.AudioFrame.from_ndarray(silence, format="flt", layout="mono")
            frame.sample_rate, frame.pts = 48000, index * 960
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def test_the_length_is_measured_from_the_file_itself(tmp_path: Path) -> None:
    clip = tmp_path / "clip.ogg"
    _opus(clip, 3)
    assert voice_server._decode(str(clip)).size == pytest.approx(3 * voice_server.SAMPLE_RATE, abs=voice_server.SAMPLE_RATE // 10)
    with pytest.raises(voice_server.RecordingTooLong):
        voice_server._decode(str(clip), max_seconds=2)


def test_weights_that_are_not_there_are_a_503_not_a_crash(tmp_path: Path, spool: Path, serve, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real child with no weights: it never reaches for the network, and the door stays up and answers."""
    monkeypatch.setenv("VOICE_MODEL_DIR", str(tmp_path / "absent"))
    model = ModelProcess([sys.executable, "-u", str(Path(voice_server.__file__)), "--model-process"], name="voice")
    door = serve(model)
    assert post(door, b"abc")[0] == 503
    connection = http.client.HTTPConnection("127.0.0.1", door.server_address[1], timeout=10)
    connection.request("GET", "/")
    assert connection.getresponse().status == 200
    connection.close()
    assert list(spool.iterdir()) == []


@pytest.mark.parametrize("reply", ['{"error": "RuntimeError"}', "not json at all", '"text only"', '{"label": "x"}'])
def test_a_bad_answer_is_a_500_and_leaves_nothing(tmp_path: Path, spool: Path, serve, reply: str) -> None:
    door = serve(fake_model(tmp_path, f"import sys\nfor line in sys.stdin:\n    print({reply!r}, flush=True)\n"))
    assert post(door, b"abc")[0] == 500
    assert list(spool.iterdir()) == []


def test_a_recording_too_large_or_empty_never_reaches_the_model(tmp_path: Path, spool: Path, serve) -> None:
    door = serve(fake_model(tmp_path, HEARS))
    connection = http.client.HTTPConnection("127.0.0.1", door.server_address[1], timeout=10)
    connection.putrequest("POST", "/transcribe")
    connection.putheader("Content-Length", str(MAX_AUDIO_BYTES + 1))
    connection.endheaders()  # The body is never sent: the door must answer from the header alone.
    assert connection.getresponse().status == 413
    connection.close()
    assert post(door, b"")[0] == 422
    assert post(door, b"abc", path="/elsewhere")[0] == 404
    assert not door.model.loaded and list(spool.iterdir()) == []


def test_a_stalled_upload_does_not_hold_the_door_shut(tmp_path: Path, spool: Path, serve, monkeypatch: pytest.MonkeyPatch) -> None:
    assert 0 < Handler.timeout <= 60, "a client that stalls must be let go"
    monkeypatch.setattr(Handler, "timeout", 1.0)
    door = serve(fake_model(tmp_path, HEARS))
    stalled = socket.create_connection(("127.0.0.1", door.server_address[1]))
    stalled.sendall(b"POST /transcribe HTTP/1.1\r\nHost: x\r\nContent-Length: 1000\r\n\r\n" + b"x" * 10)
    # Another client is served while the first one stalls...
    assert post(door, b"abc")[0] == 200
    # ...and the stalled one is let go, not waited on for ever.
    stalled.settimeout(10)
    began = time.monotonic()
    try:
        dropped = stalled.recv(4096)
    except ConnectionResetError:
        dropped = b""
    stalled.close()
    assert dropped == b"" and time.monotonic() - began < 8
    assert list(spool.iterdir()) == []


def test_health_answers_while_a_recording_is_being_heard(tmp_path: Path, spool: Path, serve) -> None:
    slow = HEARS.replace("size = len", "import time; time.sleep(2); size = len")
    door = serve(fake_model(tmp_path, slow))
    result: list[int] = []
    worker = threading.Thread(target=lambda: result.append(post(door, b"abc")[0]))
    worker.start()
    time.sleep(0.5)
    began = time.monotonic()
    connection = http.client.HTTPConnection("127.0.0.1", door.server_address[1], timeout=10)
    connection.request("GET", "/")
    assert connection.getresponse().status == 200
    connection.close()
    assert time.monotonic() - began < 1.0
    worker.join(timeout=30)
    assert result == [200]


# ── what is not speech never reaches the model, and what the model invents is dropped ──
RATE = voice_server.SAMPLE_RATE


def _seconds(count: float):
    numpy = pytest.importorskip("numpy")
    return numpy.arange(int(count * RATE)) / RATE


def _beep(seconds: float = 2.0, hertz: float = 220.0):
    numpy = pytest.importorskip("numpy")
    return (0.3 * numpy.sin(2 * numpy.pi * hertz * _seconds(seconds))).astype(numpy.float32)


def _talking(seconds: float = 4.0):
    """Made-up speech: a gliding voice whose harmonics follow two formants, loud and soft at a syllable's pace, with pauses and a little room noise."""
    numpy = pytest.importorskip("numpy")
    rng = numpy.random.default_rng(7)
    t = _seconds(seconds)
    pitch = 120 + 40 * numpy.sin(2 * numpy.pi * 0.7 * t)
    phase = 2 * numpy.pi * numpy.cumsum(pitch) / RATE
    voice = sum(numpy.sin(k * phase) / (1 + ((k * pitch - 700) / 400) ** 2 + 0.3) for k in range(1, 30))
    syllables = numpy.clip(numpy.sin(2 * numpy.pi * 3.5 * t), 0, None) ** 1.5 * (numpy.sin(2 * numpy.pi * 0.4 * t) > -0.6)
    out = 0.12 * voice * syllables / numpy.abs(voice).max() * 3 + 0.002 * rng.standard_normal(t.size)
    return out.astype(numpy.float32)


def test_a_beep_a_hum_noise_and_silence_have_no_speech_in_them() -> None:
    numpy = pytest.importorskip("numpy")
    rng = numpy.random.default_rng(1)
    hum = sum(0.1 * numpy.sin(2 * numpy.pi * 50 * k * _seconds(3)) for k in (1, 2, 3, 5)).astype(numpy.float32)
    two_tones = (_beep(3, 697) + _beep(3, 1209)).astype(numpy.float32)
    noise = (0.2 * rng.standard_normal(3 * RATE)).astype(numpy.float32)
    for sound in (_beep(), _beep(2, 1000), hum, two_tones, noise, numpy.zeros(3 * RATE, numpy.float32), 0.0005 * noise):
        assert voice_server._speech_seconds(sound) == 0.0


def test_something_like_talking_is_let_through() -> None:
    assert voice_server._speech_seconds(_talking()) > 1.0
    numpy = pytest.importorskip("numpy")
    assert voice_server._speech_seconds(_talking() * numpy.float32(0.3)) > 1.0, "10 dB quieter is still heard"
    assert voice_server._speech_seconds(_talking() * numpy.float32(0.05)) == 0.0, "the floor: a voice 26 dB down (peaks at -48 dBFS) is taken for nothing"


def test_a_click_is_too_short_to_be_speech() -> None:
    numpy = pytest.importorskip("numpy")
    click = numpy.zeros(2 * RATE, numpy.float32)
    click[RATE : RATE + 300] = 0.5 * numpy.random.default_rng(2).standard_normal(300)
    assert voice_server._speech_seconds(click) == 0.0


class _Parrot:
    """Stands for the speech model: writes whatever it is told to, and counts being asked."""

    def __init__(self, text: str) -> None:
        self.text, self.asked = text, 0

    def __call__(self, *_args, **_kwargs) -> dict:
        self.asked += 1
        return {"text": f"  {self.text} "}


def _hear(monkeypatch: pytest.MonkeyPatch, sound, text: str) -> tuple[dict, _Parrot]:
    parrot = _Parrot(text)
    monkeypatch.setattr(voice_server, "_decode", lambda _path: sound)
    return voice_server._transcribe({"hear": parrot}, "unused"), parrot


def test_a_beep_gets_empty_text_and_the_model_is_not_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    reply, parrot = _hear(monkeypatch, _beep(), "Xin chào các bạn, hôm nay mình sẽ nói về chủ đề mới")
    assert reply == {"text": ""} and parrot.asked == 0


def test_talking_is_written_down(monkeypatch: pytest.MonkeyPatch) -> None:
    reply, parrot = _hear(monkeypatch, _talking(), "Mai mình họp lúc chín giờ nhé")
    assert reply == {"text": "Mai mình họp lúc chín giờ nhé"} and parrot.asked == 1


@pytest.mark.parametrize(
    "invented",
    [
        "không không không không không không không không",
        "Hãy subscribe cho kênh Ghiền Mì Gõ Để không bỏ lỡ những video hấp dẫn",
        "Cảm ơn các bạn đã theo dõi, hẹn gặp lại các bạn trong những video tiếp theo!",
        "a" * 400,
    ],
)
def test_what_the_model_invents_over_a_short_sound_is_dropped(monkeypatch: pytest.MonkeyPatch, invented: str) -> None:
    short = _talking()[: int(0.7 * RATE)]
    assert 0.3 <= voice_server._speech_seconds(short) < voice_server.STOCK_PHRASE_SECONDS
    reply, parrot = _hear(monkeypatch, short, invented)
    assert reply == {"text": ""} and parrot.asked == 1


def test_a_stock_line_said_in_a_long_recording_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    """A person may really say it; the stock-line rule only applies to a sound too short to hold more."""
    reply, _ = _hear(monkeypatch, _talking(12), "Cảm ơn các bạn đã theo dõi buổi họp hôm nay")
    assert reply["text"] != ""
