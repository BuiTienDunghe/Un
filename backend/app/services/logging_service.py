from __future__ import annotations

import logging
import warnings
from pathlib import Path

from loguru import logger

from app.stores.auxiliary_store import AuxiliaryStore


class _InterceptHandler(logging.Handler):
    """Route the standard library's logging into loguru's sinks.

    D4-lite #1. Before this, ``logging_service`` configured loguru and nothing
    else, so every warning raised by a third-party library — transformers,
    httpx, sentence-transformers — went to a console window and died with it.
    That is not hypothetical: the cross-encoder printed
    ``Token indices sequence length is longer than ... (778 > 512)`` on every
    single call for four days while 65% of the corpus was reranked on a
    truncated prefix, and a search of all 30 days of log files finds zero
    matching lines. The bug was eventually found by hand-measuring stages.

    Ten lines is what that record cost.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        # Walk out of the logging machinery so the recorded source location is
        # the library that actually warned, not this handler.
        frame, depth = logging.currentframe(), 2
        while frame is not None and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.bind(event="stdlib", logger_name=record.name).opt(
            depth=depth, exception=record.exc_info
        ).log(level, record.getMessage())


class LoggingService:
    _configured_log_files: set[Path] = set()
    _stdlib_bridged = False

    def __init__(self, store: AuxiliaryStore, log_dir: Path, stdlib_level: int = logging.WARNING) -> None:
        self.store = store
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = log_dir / "app_{time:YYYY-MM-DD}.log"
        if self.log_file not in self._configured_log_files:
            logger.add(
                str(self.log_file),
                rotation="1 day",
                retention="30 days",
                serialize=True,
                level="INFO",
            )
            self._configured_log_files.add(self.log_file)
        self._bridge_stdlib(stdlib_level)

    @classmethod
    def _bridge_stdlib(cls, level: int) -> None:
        """Make third-party warnings durable, at WARNING and above.

        WARNING rather than INFO on purpose. The whole value here is the line
        nobody was going to read anyway — a truncation notice, a deprecation, a
        retry — and those are all WARNING or worse. Capturing INFO too would
        pull in every httpx request line and drown the signal in the same file
        that is supposed to make it findable.

        The per-library loop is NOT belt-and-braces, it is the whole mechanism.
        Measured: with ``basicConfig`` + ``captureWarnings`` alone — the recipe
        every guide gives — the tokenizer warning this exists to catch produces
        ZERO lines in the file. transformers sets ``propagate=False`` on its own
        logger and installs its own StreamHandler, so the root handler never
        sees it. Naming the libraries explicitly is what makes it durable.

        Accepted cost: transformers installs that handler at import, which is
        after this runs, so its warnings print twice on the console — once
        through loguru, once through its own handler. The FILE gets exactly one
        line, which is the record that matters. Silencing the console copy would
        mean importing transformers at startup to call its logging API, and that
        drags in ~2.5 GB of torch on a machine that may not have the extra
        installed at all.
        """
        if cls._stdlib_bridged:
            return
        handler = _InterceptHandler()
        logging.basicConfig(handlers=[handler], level=level, force=True)
        # captureWarnings routes warnings.warn() — DeprecationWarning and
        # friends — through logging, and from there into the file.
        logging.captureWarnings(True)
        warnings.simplefilter("default")
        for name in ("transformers", "sentence_transformers", "huggingface_hub", "torch", "urllib3", "httpx"):
            library = logging.getLogger(name)
            library.handlers = [handler]
            library.propagate = False
            if library.level == logging.NOTSET or library.level > level:
                library.setLevel(level)
        cls._stdlib_bridged = True

    def log_request(
        self, endpoint: str, model_used: str | None, latency_ms: int, status: str, error_code: str | None = None,
        message_id: int | None = None, tokens_in: int | None = None, tokens_out: int | None = None, prompt_hash: str | None = None,
    ) -> None:
        self.store.log_request(endpoint, model_used, latency_ms, status, error_code, message_id=message_id, tokens_in=tokens_in, tokens_out=tokens_out, prompt_hash=prompt_hash)
        logger.bind(endpoint=endpoint, model_used=model_used, latency_ms=latency_ms, status=status, error_code=error_code, message_id=message_id, tokens_in=tokens_in, tokens_out=tokens_out).info(
            "request completed"
        )
