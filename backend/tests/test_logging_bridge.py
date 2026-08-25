"""D4-lite #1: a third-party warning must survive as a durable record.

The failure this guards: the cross-encoder printed
``Token indices sequence length is longer than ... (778 > 512)`` on every call
for four days while 65% of the corpus was reranked on a truncated prefix, and
zero matching lines exist in the 30 days of log files. The warning was real,
loud, and thrown away — nothing configured the standard library's logging.
"""
from __future__ import annotations

import json
import logging
import warnings
from pathlib import Path

import pytest
from loguru import logger

from app.services.logging_service import LoggingService


class _NullStore:
    def log_request(self, *args, **kwargs) -> None:
        return None


@pytest.fixture
def bridged(tmp_path, monkeypatch):
    """A LoggingService writing to a scratch dir, with the bridge freshly armed.

    The bridge is process-global and installed once, so the class flag has to be
    reset or a test that runs second sees whatever the first one left behind.
    Handlers are restored afterwards, since replacing the root logger's handlers
    for the whole pytest process would eat other tests' output.
    """
    monkeypatch.setattr(LoggingService, "_stdlib_bridged", False)
    monkeypatch.setattr(LoggingService, "_configured_log_files", set())
    root_handlers, root_level = logging.root.handlers[:], logging.root.level
    before = set(logger._core.handlers)          # noqa: SLF001 - no public sink registry

    service = LoggingService(_NullStore(), tmp_path)
    yield service, tmp_path

    # Every sink this test opened has to go, or the next test's records land in
    # this test's tmp_path as well and the assertions start passing by accident.
    for sink_id in set(logger._core.handlers) - before:   # noqa: SLF001
        logger.remove(sink_id)
    logging.root.handlers, logging.root.level = root_handlers, root_level
    logging.captureWarnings(False)


def _records(log_dir: Path) -> list[dict]:
    return [
        json.loads(line)["record"]
        for path in sorted(log_dir.glob("app_*.log"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_a_third_party_logger_reaches_the_log_file(bridged):
    """A library that logs through the stdlib root must land in the file."""
    _, log_dir = bridged

    logging.getLogger("some_vendor_library").warning("chunk truncated at 512 tokens")

    messages = [record["message"] for record in _records(log_dir)]
    assert any("truncated at 512" in message for message in messages), messages


def test_the_source_library_is_named_on_the_record(bridged):
    """"Something warned" is not actionable; "transformers warned" is."""
    _, log_dir = bridged

    logging.getLogger("transformers.tokenization_utils_base").warning("Token indices sequence length is longer")

    named = [r for r in _records(log_dir) if r["extra"].get("logger_name") == "transformers.tokenization_utils_base"]
    assert named, [r["extra"] for r in _records(log_dir)]
    assert named[0]["extra"]["event"] == "stdlib"


def test_warnings_dot_warn_is_captured_too(bridged):
    """DeprecationWarning and friends do not go through logging on their own."""
    _, log_dir = bridged

    warnings.warn("this API moves in the next release", DeprecationWarning)

    messages = [record["message"] for record in _records(log_dir)]
    assert any("moves in the next release" in message for message in messages), messages


def test_info_from_libraries_is_not_captured(bridged):
    """WARNING and above only.

    Capturing INFO would pull in every httpx request line and bury the one
    warning this file exists to make findable — in the same file.
    """
    _, log_dir = bridged

    logging.getLogger("httpx").info("HTTP Request: POST http://localhost:11434/api/chat")

    messages = [record["message"] for record in _records(log_dir)]
    assert not any("HTTP Request" in message for message in messages), messages


def test_a_library_that_refuses_to_propagate_is_still_captured(bridged):
    """The measured reason the per-library loop exists at all.

    transformers sets propagate=False and installs its own handler, so
    logging.basicConfig alone yields ZERO lines for the exact warning that cost
    four days. Verified by running it that way: 0 records. This asserts the
    behaviour that fixes it, on the same shape of logger.
    """
    _, log_dir = bridged
    library = logging.getLogger("transformers")
    assert library.propagate is False, "the bridge must not rely on propagation"

    logging.getLogger("transformers.modeling_utils").warning("weights not initialized")

    messages = [record["message"] for record in _records(log_dir)]
    assert any("weights not initialized" in message for message in messages), messages
