from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    app_name: str = "local-ai-core"
    database_url: str | None = None
    # Layer-1 access control. Empty means "no key configured": writes stay open,
    # which is what a single-user machine wants and what the one-click launcher
    # depends on. Set it to close write endpoints to anyone without the header.
    local_ai_api_key: str = ""
    # Only meaningful once a key is set; closes read endpoints too.
    local_ai_protect_reads: bool = False
    request_log_retention_days: int = 7
    ingestion_execution_backend: str = "thread"
    redis_url: str = "redis://127.0.0.1:6379/0"
    rq_queue_prefix: str = "local-ai:dev"
    job_max_attempts: int = 3
    job_stale_timeout_seconds: int = 900
    discord_memory_ingestion_enabled: bool = False
    discord_memory_extractor_enabled: bool = False
    discord_memory_extractor_model: str = "qwen3.5:2b"
    discord_memory_extractor_schema_version: str = "v1"
    discord_memory_extractor_num_ctx: int = 4096
    discord_memory_extractor_temperature: float = 0.0
    discord_memory_extractor_seed: int = 424242
    discord_memory_extractor_json_fallback: bool = False
    discord_memory_extractor_timeout_seconds: float = 60.0
    discord_memory_extractor_retry_count: int = 1
    discord_memory_queue_name: str = "memory_extract"
    # P2-2: Discord turns run through the agent loop (tool use + trace). Off
    # falls back to plain chat — same answer path as before the agent existed.
    discord_agent_tools_enabled: bool = True
    # P2-1: proposals at or above this extractor confidence are applied by the
    # agent itself (reviewed_by="agent") and can be reverted in one click from
    # the dashboard; below it they wait in the review queue. Set to "off" to
    # review everything by hand. Delete-proposals always wait for a human.
    discord_memory_auto_apply_threshold: float | None = 0.8
    superseded_version_grace_days: int = 7
    backup_dir: str = "data/backups"
    log_dir: str = "data/logs"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_chat_timeout_seconds: float = 120.0
    ollama_health_timeout_seconds: float = 5.0
    ollama_retry_count: int = 2
    # ── Cloud LLM providers ──
    gemini_api_key: str | None = None
    gemini_chat_timeout_seconds: float = 60.0
    gemini_retry_count: int = 2
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_chat_timeout_seconds: float = 90.0
    deepseek_retry_count: int = 2
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_timeout_seconds: float = 10.0
    # Memory vectors live in their own named collection. Tests point this at a
    # test-only collection so a mocked low-dimension embed can never create or
    # poison the runtime collection (a 3-dim collection makes every real
    # 1024-dim memory write fail with a dimension mismatch).
    qdrant_memories_collection: str = "memories"
    max_upload_size_bytes: int = 52_428_800
    max_message_length: int = 10_000
    conversation_history_limit: int = 12

    @field_validator("discord_memory_auto_apply_threshold", mode="before")
    @classmethod
    def _auto_apply_off_words(cls, value: object) -> object:
        # `.env` files have no null literal; the natural way an operator turns
        # autonomy off is an empty value or the word "off".
        if isinstance(value, str) and value.strip().lower() in {"", "off", "none", "disabled"}:
            return None
        return value

    @model_validator(mode="after")
    def validate_runtime_database(self) -> "Settings":
        if self.request_log_retention_days < 1:
            raise ValueError("REQUEST_LOG_RETENTION_DAYS must be positive")
        if not self.database_url:
            raise ValueError("DATABASE_URL is required for the PostgreSQL runtime")
        if not str(self.database_url).startswith("postgresql+"):
            raise ValueError("DATABASE_URL must use a PostgreSQL SQLAlchemy dialect, not SQLite")
        if not self.discord_memory_extractor_schema_version.strip():
            raise ValueError("DISCORD_MEMORY_EXTRACTOR_SCHEMA_VERSION must not be empty")
        if not self.discord_memory_extractor_model.strip():
            raise ValueError("DISCORD_MEMORY_EXTRACTOR_MODEL must not be empty")
        if self.discord_memory_extractor_num_ctx < 512:
            raise ValueError("DISCORD_MEMORY_EXTRACTOR_NUM_CTX must be at least 512")
        if self.discord_memory_extractor_temperature != 0.0:
            raise ValueError(
                "DISCORD_MEMORY_EXTRACTOR_TEMPERATURE must be 0.0 in strict mode"
            )
        if self.discord_memory_extractor_timeout_seconds <= 0:
            raise ValueError(
                "DISCORD_MEMORY_EXTRACTOR_TIMEOUT_SECONDS must be positive"
            )
        if self.discord_memory_extractor_retry_count < 0:
            raise ValueError(
                "DISCORD_MEMORY_EXTRACTOR_RETRY_COUNT must not be negative"
            )
        if not self.discord_memory_queue_name.strip():
            raise ValueError("DISCORD_MEMORY_QUEUE_NAME must not be empty")
        if self.discord_memory_auto_apply_threshold is not None and not (
            0.0 < self.discord_memory_auto_apply_threshold <= 1.0
        ):
            raise ValueError(
                "DISCORD_MEMORY_AUTO_APPLY_THRESHOLD must be in (0, 1] or 'off'"
            )
        return self

    @property
    def logs_path(self) -> Path:
        return PROJECT_ROOT / self.log_dir

    @property
    def models_path(self) -> Path:
        return Path(__file__).with_name("models.yaml")

    @property
    def documents_path(self) -> Path:
        return PROJECT_ROOT / "data" / "documents"

    @property
    def ocr_runs_path(self) -> Path:
        return PROJECT_ROOT / "data" / "ocr_runs"

    @property
    def backups_path(self) -> Path:
        return PROJECT_ROOT / self.backup_dir

    @property
    def postgres_backups_path(self) -> Path:
        # Keeps the layout the manual script has always written to, so old and
        # new backups sit in one directory.
        return self.backups_path / "postgres"

    def load_config(self) -> dict[str, Any]:
        with self.models_path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    def load_storage_config(self) -> dict[str, Any]:
        return self.load_config().get("storage", {})

    def load_models(self) -> dict[str, dict[str, Any]]:
        payload = self.load_config()
        models = payload.get("models")
        if not isinstance(models, dict):
            raise ValueError("models.yaml must contain a models mapping")
        return models


@lru_cache
def get_settings() -> Settings:
    return Settings()
