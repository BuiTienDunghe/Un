from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path


class SQLiteStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    model_used TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id)
                );
                CREATE TABLE IF NOT EXISTS request_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    endpoint TEXT NOT NULL,
                    model_used TEXT,
                    latency_ms INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    error_code TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    original_filename TEXT NOT NULL,
                    stored_filename TEXT NOT NULL,
                    content_type TEXT,
                    status TEXT NOT NULL,
                    chunks_count INTEGER NOT NULL DEFAULT 0,
                    ocr_pages_count INTEGER NOT NULL DEFAULT 0,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS document_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    page INTEGER,
                    extraction_method TEXT NOT NULL DEFAULT 'native',
                    FOREIGN KEY(document_id) REFERENCES documents(id),
                    UNIQUE(document_id, chunk_index)
                );
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    importance REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ocr_runs (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    status TEXT NOT NULL,
                    model TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    result_json TEXT NOT NULL
                );
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(document_chunks)").fetchall()}
            if "extraction_method" not in columns:
                connection.execute("ALTER TABLE document_chunks ADD COLUMN extraction_method TEXT NOT NULL DEFAULT 'native'")
            document_columns = {row["name"] for row in connection.execute("PRAGMA table_info(documents)").fetchall()}
            if "ocr_pages_count" not in document_columns:
                connection.execute("ALTER TABLE documents ADD COLUMN ocr_pages_count INTEGER NOT NULL DEFAULT 0")

    def healthcheck(self) -> bool:
        try:
            with self._connect() as connection:
                connection.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False

    def conversation_exists(self, conversation_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
        return row is not None

    def create_conversation(self, conversation_id: str) -> None:
        now = self._timestamp()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO conversations (id, created_at, updated_at) VALUES (?, ?, ?)",
                (conversation_id, now, now),
            )

    def add_message(
        self, conversation_id: str, role: str, content: str, model_used: str | None = None
    ) -> None:
        now = self._timestamp()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO messages (conversation_id, role, content, model_used, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (conversation_id, role, content, model_used, now),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id)
            )

    def get_messages(self, conversation_id: str, limit: int) -> list[dict[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT role, content FROM messages WHERE conversation_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (conversation_id, limit),
            ).fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

    def list_conversations(self) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT c.id, c.created_at, c.updated_at, COUNT(m.id) AS message_count "
                "FROM conversations c LEFT JOIN messages m ON m.conversation_id = c.id "
                "GROUP BY c.id ORDER BY c.updated_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_conversation(self, conversation_id: str) -> dict[str, object] | None:
        with self._connect() as connection:
            conversation = connection.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
            messages = connection.execute(
                "SELECT role, content, model_used, created_at FROM messages WHERE conversation_id = ? ORDER BY id",
                (conversation_id,),
            ).fetchall()
        if conversation is None:
            return None
        return {**dict(conversation), "messages": [dict(message) for message in messages]}

    def delete_conversation(self, conversation_id: str) -> bool:
        with self._connect() as connection:
            connection.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
            result = connection.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        return result.rowcount > 0

    def log_request(
        self,
        endpoint: str,
        model_used: str | None,
        latency_ms: int,
        status: str,
        error_code: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO request_logs (endpoint, model_used, latency_ms, status, error_code, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (endpoint, model_used, latency_ms, status, error_code, self._timestamp()),
            )

    def create_document(self, document_id: str, original_filename: str, stored_filename: str, content_type: str | None) -> None:
        now = self._timestamp()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO documents (id, original_filename, stored_filename, content_type, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'uploaded', ?, ?)",
                (document_id, original_filename, stored_filename, content_type, now, now),
            )

    def get_document(self, document_id: str) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        return dict(row) if row else None

    def list_documents_for_storage_migration(self) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT id, stored_filename FROM documents").fetchall()
        return [dict(row) for row in rows]

    def update_document_status(self, document_id: str, status: str, chunks_count: int | None = None, ocr_pages_count: int | None = None, error_message: str | None = None) -> None:
        assignments = ["status = ?", "updated_at = ?", "error_message = ?"]
        values: list[object] = [status, self._timestamp(), error_message]
        if chunks_count is not None:
            assignments.append("chunks_count = ?")
            values.append(chunks_count)
        if ocr_pages_count is not None:
            assignments.append("ocr_pages_count = ?")
            values.append(ocr_pages_count)
        values.append(document_id)
        with self._connect() as connection:
            connection.execute(f"UPDATE documents SET {', '.join(assignments)} WHERE id = ?", values)

    def replace_document_chunks(self, document_id: str, chunks: list[tuple[str, int | None, str]]) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
            connection.executemany(
                "INSERT INTO document_chunks (document_id, chunk_index, content, page, extraction_method) VALUES (?, ?, ?, ?, ?)",
                [(document_id, index, content, page, extraction_method) for index, (content, page, extraction_method) in enumerate(chunks)],
            )

    def get_document_chunks(self, document_id: str | None = None) -> list[dict[str, object]]:
        statement = (
            "SELECT c.document_id, d.original_filename AS filename, c.chunk_index, c.page, c.extraction_method, c.content "
            "FROM document_chunks c JOIN documents d ON d.id = c.document_id WHERE d.status = 'indexed'"
        )
        values: tuple[object, ...] = ()
        if document_id:
            statement += " AND c.document_id = ?"
            values = (document_id,)
        with self._connect() as connection:
            rows = connection.execute(statement, values).fetchall()
        return [dict(row) for row in rows]

    def create_memory(self, memory_id: str, content: str, memory_type: str, importance: float) -> None:
        now = self._timestamp()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO memories (id, content, memory_type, importance, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (memory_id, content, memory_type, importance, now, now),
            )

    def get_memory(self, memory_id: str) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return dict(row) if row else None

    def update_memory(self, memory_id: str, content: str, memory_type: str, importance: float) -> bool:
        with self._connect() as connection:
            result = connection.execute(
                "UPDATE memories SET content = ?, memory_type = ?, importance = ?, updated_at = ? WHERE id = ?",
                (content, memory_type, importance, self._timestamp(), memory_id),
            )
        return result.rowcount > 0

    def delete_memory(self, memory_id: str) -> bool:
        with self._connect() as connection:
            result = connection.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        return result.rowcount > 0

    def save_ocr_run(self, run_id: str, filename: str, status: str, model: str, result_json: str) -> None:
        now = self._timestamp()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO ocr_runs (id, filename, status, model, created_at, updated_at, result_json) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at, result_json=excluded.result_json",
                (run_id, filename, status, model, now, now, result_json),
            )

    def list_ocr_runs(self) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT id, filename, status, model, created_at, updated_at, result_json FROM ocr_runs ORDER BY updated_at DESC").fetchall()
        return [dict(row) for row in rows]

    def delete_ocr_run(self, run_id: str) -> bool:
        with self._connect() as connection:
            result = connection.execute("DELETE FROM ocr_runs WHERE id = ?", (run_id,))
        return result.rowcount > 0

    # --- Batch chunk lookup (for Qdrant → SQLite content resolution) ---

    def get_chunks_by_keys(self, keys: list[tuple[str, int]]) -> dict[tuple[str, int], dict[str, object]]:
        """Batch-fetch chunk content by (document_id, chunk_index) pairs."""
        if not keys:
            return {}
        with self._connect() as connection:
            placeholders = ",".join(["(?, ?)"] * len(keys))
            flat_values = [value for pair in keys for value in pair]
            rows = connection.execute(
                f"SELECT c.document_id, c.chunk_index, c.content, c.page, c.extraction_method, d.original_filename AS filename "
                f"FROM document_chunks c JOIN documents d ON d.id = c.document_id "
                f"WHERE (c.document_id, c.chunk_index) IN (VALUES {placeholders})",
                flat_values,
            ).fetchall()
        return {(row["document_id"], row["chunk_index"]): dict(row) for row in rows}

    # --- Cleanup methods (TTL) ---

    def get_expired_documents(self, cutoff_iso: str) -> list[dict[str, object]]:
        """Get indexed documents older than cutoff."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, stored_filename FROM documents WHERE status = 'indexed' AND updated_at < ?",
                (cutoff_iso,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_expired_logs(self, cutoff_iso: str) -> int:
        """Delete request_logs older than cutoff. Returns count deleted."""
        with self._connect() as connection:
            result = connection.execute("DELETE FROM request_logs WHERE created_at < ?", (cutoff_iso,))
        return result.rowcount

    def get_expired_ocr_runs(self, cutoff_iso: str) -> list[dict[str, object]]:
        """Get OCR runs older than cutoff."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, result_json FROM ocr_runs WHERE updated_at < ?",
                (cutoff_iso,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(UTC).isoformat()
