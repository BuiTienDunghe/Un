from __future__ import annotations

from pathlib import Path

from loguru import logger

from app.stores.sqlite_store import SQLiteStore


class LoggingService:
    _configured_log_files: set[Path] = set()

    def __init__(self, store: SQLiteStore, log_dir: Path) -> None:
        self.store = store
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = log_dir / "app_{time:YYYY-MM-DD}.log"
        if self.log_file not in self._configured_log_files:
            logger.add(
                str(self.log_file),
                rotation="1 day",
                retention="30 days",
                format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {module}:{function}:{line} | {message}",
                level="INFO",
            )
            self._configured_log_files.add(self.log_file)

    def log_request(
        self, endpoint: str, model_used: str | None, latency_ms: int, status: str, error_code: str | None = None
    ) -> None:
        self.store.log_request(endpoint, model_used, latency_ms, status, error_code)
        logger.bind(endpoint=endpoint, model_used=model_used, latency_ms=latency_ms, status=status, error_code=error_code).info(
            "request completed"
        )
