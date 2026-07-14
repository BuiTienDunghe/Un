from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    app_name: str = "local-ai-core"
    db_path: str = "data/sqlite/local_ai_core.db"
    log_dir: str = "data/logs"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_chat_timeout_seconds: float = 120.0
    ollama_health_timeout_seconds: float = 5.0
    ollama_retry_count: int = 2
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_timeout_seconds: float = 10.0
    max_upload_size_bytes: int = 52_428_800
    max_message_length: int = 10_000
    max_code_context_length: int = 50_000
    conversation_history_limit: int = 12

    @property
    def database_path(self) -> Path:
        return PROJECT_ROOT / self.db_path

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
