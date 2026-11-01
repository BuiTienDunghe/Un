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
