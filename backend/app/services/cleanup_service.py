from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from loguru import logger

from app.stores.sqlite_store import SQLiteStore


class CleanupService:
    """TTL-based cleanup for documents, OCR runs, and request logs."""

    def __init__(self, store: SQLiteStore, documents_path: Path, ocr_runs_path: Path) -> None:
        self.store = store
        self.documents_path = documents_path
        self.ocr_runs_path = ocr_runs_path

    def run_all(self, documents_ttl_days: int, ocr_runs_ttl_days: int, logs_ttl_days: int) -> None:
        """Run all cleanup tasks. Safe to call on every server startup."""
        if documents_ttl_days > 0:
            count = self.cleanup_expired_documents(documents_ttl_days)
            if count:
                logger.info(f"Cleanup: removed {count} expired document(s) (TTL={documents_ttl_days}d)")
        if ocr_runs_ttl_days > 0:
            count = self.cleanup_expired_ocr_runs(ocr_runs_ttl_days)
            if count:
                logger.info(f"Cleanup: removed {count} expired OCR run(s) (TTL={ocr_runs_ttl_days}d)")
        if logs_ttl_days > 0:
            count = self.cleanup_expired_logs(logs_ttl_days)
            if count:
                logger.info(f"Cleanup: removed {count} expired log(s) (TTL={logs_ttl_days}d)")

    def cleanup_expired_documents(self, ttl_days: int) -> int:
        """Remove indexed documents older than ttl_days. Keeps uploaded/failed docs."""
        cutoff = self._cutoff(ttl_days)
        expired = self.store.get_expired_documents(cutoff)
        for doc in expired:
            doc_id = str(doc["id"])
            # Remove per-document folder (new layout)
            doc_dir = self.documents_path / doc_id
            if doc_dir.is_dir():
                shutil.rmtree(doc_dir, ignore_errors=True)
            # Remove flat file (old layout)
            flat_file = self.documents_path.parent / "uploads" / str(doc["stored_filename"])
            flat_file.unlink(missing_ok=True)
        return len(expired)

    def cleanup_expired_ocr_runs(self, ttl_days: int) -> int:
        """Remove OCR run folders and DB records older than ttl_days."""
        cutoff = self._cutoff(ttl_days)
        expired = self.store.get_expired_ocr_runs(cutoff)
        for run in expired:
            run_id = str(run["id"])
            run_dir = self.ocr_runs_path / run_id
            if run_dir.is_dir():
                shutil.rmtree(run_dir, ignore_errors=True)
            self.store.delete_ocr_run(run_id)
        return len(expired)

    def cleanup_expired_logs(self, ttl_days: int) -> int:
        """Remove request_logs older than ttl_days."""
        cutoff = self._cutoff(ttl_days)
        return self.store.delete_expired_logs(cutoff)

    @staticmethod
    def _cutoff(ttl_days: int) -> str:
        return (datetime.now(UTC) - timedelta(days=ttl_days)).isoformat()
