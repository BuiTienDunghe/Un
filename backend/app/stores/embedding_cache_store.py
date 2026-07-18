"""PostgreSQL-only embedding cache contract for document indexing workers.

The cache is deliberately independent from the auxiliary-domain store.  It is
an optional acceleration: invalid rows and cache infrastructure failures are
handled by callers as misses, never as a reason to use an unverified vector.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Protocol

from loguru import logger
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker

from app.postgres.models import EmbeddingCache


@dataclass(frozen=True)
class EmbeddingCacheIdentity:
    """All inputs which can change an embedding vector's meaning."""

    content_hash: str
    model_name: str
    model_revision: str
    dimensions: int
    config_fingerprint: str
    normalization_fingerprint: str

    @property
    def cache_key(self) -> str:
        # The table's unique tuple is authoritative.  This key is useful for
        # logs/tests and remains deterministic without exposing document text.
        payload = json.dumps(
            {
                "content_hash": self.content_hash,
                "model_name": self.model_name,
                "model_revision": self.model_revision,
                "dimensions": self.dimensions,
                "config_fingerprint": self.config_fingerprint,
                "normalization_fingerprint": self.normalization_fingerprint,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class EmbeddingCacheStore(Protocol):
    def get(self, identity: EmbeddingCacheIdentity) -> list[float] | None: ...

    def save(self, identity: EmbeddingCacheIdentity, vector: list[float]) -> None: ...


def fingerprint(value: Any) -> str:
    """Canonical, deterministic fingerprint for declared embedding settings."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class PostgresEmbeddingCacheStore:
    """Short-session PostgreSQL cache implementation.

    It intentionally does not hold a session while Ollama is called.  Invalid
    vector JSON is a cache miss and is never returned to indexing.
    """

    def __init__(self, session_factory: sessionmaker) -> None:
        self.sessions = session_factory

    @staticmethod
    def _valid_vector(vector: object, dimensions: int) -> list[float] | None:
        if not isinstance(vector, list) or len(vector) != dimensions:
            return None
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in vector):
            return None
        return [float(value) for value in vector]

    def get(self, identity: EmbeddingCacheIdentity) -> list[float] | None:
        with self.sessions() as session:
            row = session.scalar(
                select(EmbeddingCache).where(
                    EmbeddingCache.content_hash == identity.content_hash,
                    EmbeddingCache.model_name == identity.model_name,
                    EmbeddingCache.model_revision == identity.model_revision,
                    EmbeddingCache.dimensions == identity.dimensions,
                    EmbeddingCache.config_fingerprint == identity.config_fingerprint,
                    EmbeddingCache.normalization_fingerprint == identity.normalization_fingerprint,
                )
            )
            if row is None:
                return None
            vector = self._valid_vector(row.vector, identity.dimensions)
            if vector is None:
                logger.warning("embedding_cache_invalid_vector cache_key={}", identity.cache_key)
            return vector

    def save(self, identity: EmbeddingCacheIdentity, vector: list[float]) -> None:
        normalized = self._valid_vector(vector, identity.dimensions)
        if normalized is None:
            raise ValueError("embedding vector dimensions or payload are invalid")
        statement = insert(EmbeddingCache).values(
            content_hash=identity.content_hash,
            model_name=identity.model_name,
            model_revision=identity.model_revision,
            dimensions=identity.dimensions,
            config_fingerprint=identity.config_fingerprint,
            normalization_fingerprint=identity.normalization_fingerprint,
            vector=normalized,
        ).on_conflict_do_update(
            constraint="uq_embedding_cache_key",
            set_={"vector": normalized},
        )
        with self.sessions.begin() as session:
            session.execute(statement)
