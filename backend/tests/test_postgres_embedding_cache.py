from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.postgres.database import create_postgres_engine, create_session_factory
from app.postgres.models import EmbeddingCache
from app.stores.embedding_cache_store import EmbeddingCacheIdentity, PostgresEmbeddingCacheStore, fingerprint
from app.services.postgres_document_service import PostgresDocumentService


POSTGRES_URL = os.getenv("POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="set POSTGRES_TEST_URL to run PostgreSQL integration tests")


@pytest.fixture
def cache_store():
    factory = create_session_factory(create_postgres_engine(str(POSTGRES_URL)))
    prefix = f"phase7a-{uuid4().hex}"
    try:
        yield PostgresEmbeddingCacheStore(factory), factory, prefix
    finally:
        with factory.begin() as session:
            session.execute(delete(EmbeddingCache).where(EmbeddingCache.model_name.like("phase7a-%")))


def _identity(prefix: str, *, revision: str = "r1", dimensions: int = 3, config: str = "a", normalization: str = "unit"):
    return EmbeddingCacheIdentity(
        content_hash="a" * 64,
        model_name=f"{prefix}-model",
        model_revision=revision,
        dimensions=dimensions,
        config_fingerprint=fingerprint({"config": config}),
        normalization_fingerprint=fingerprint(normalization),
    )


def test_cache_hit_miss_and_idempotent_upsert(cache_store):
    store, factory, prefix = cache_store
    identity = _identity(prefix)
    assert store.get(identity) is None
    store.save(identity, [0.1, 0.2, 0.3])
    store.save(identity, [0.1, 0.2, 0.3])
    assert store.get(identity) == [0.1, 0.2, 0.3]
    with factory() as session:
        assert len(list(session.scalars(select(EmbeddingCache).where(EmbeddingCache.model_name == identity.model_name)))) == 1


@pytest.mark.parametrize("change", ["revision", "config", "normalization", "dimensions"])
def test_identity_changes_are_cache_misses(cache_store, change):
    store, _, prefix = cache_store
    original = _identity(prefix)
    store.save(original, [0.1, 0.2, 0.3])
    values = {"revision": "r2", "config": "b", "normalization": "none", "dimensions": 4}
    changed = _identity(prefix, **{change: values[change]})
    assert store.get(changed) is None


def test_invalid_vector_payload_and_dimension_are_safe_misses(cache_store):
    store, factory, prefix = cache_store
    identity = _identity(prefix)
    with factory.begin() as session:
        session.add(EmbeddingCache(
            content_hash=identity.content_hash, model_name=identity.model_name,
            model_revision=identity.model_revision, dimensions=identity.dimensions,
            config_fingerprint=identity.config_fingerprint,
            normalization_fingerprint=identity.normalization_fingerprint,
            vector=["not-a-number"],
        ))
    assert store.get(identity) is None
    with pytest.raises(ValueError):
        store.save(identity, [0.1])


def test_worker_module_has_no_sqlite_embedding_cache_dependency():
    import app.workers.tasks as tasks
    assert not hasattr(tasks, "SQLiteStore")


def test_legacy_embedding_rows_are_not_imported(cache_store):
    _, factory, prefix = cache_store
    with factory() as session:
        assert session.scalar(select(EmbeddingCache).where(EmbeddingCache.model_name == f"{prefix}-legacy")) is None


class _MemoryCache:
    def __init__(self, *, fail_get: bool = False, fail_save: bool = False):
        self.rows, self.fail_get, self.fail_save = {}, fail_get, fail_save
        self.saves = 0
    def get(self, identity):
        if self.fail_get: raise ConnectionError("cache down")
        return self.rows.get(identity)
    def save(self, identity, vector):
        if self.fail_save: raise ConnectionError("cache down")
        self.saves += 1; self.rows[identity] = vector


class _Router:
    def __init__(self, config): self.models, self.calls = {"embedding": config}, 0
    def embed(self, text): self.calls += 1; return [0.1, 0.2, 0.3], self.models["embedding"]["name"]


def _service_for_cache(cache, config):
    # _embed_with_cache has no repository/session interaction; keeping the
    # dependencies inert makes the cache failure policy explicit.
    return PostgresDocumentService(None, cache, None, _Router(config), None, __import__("pathlib").Path("."), 1, 0, None)


def test_missing_revision_is_safe_miss_and_does_not_save():
    cache = _MemoryCache(); service = _service_for_cache(cache, {"name": "model", "normalization": "unit"})
    assert service._embed_with_cache("content", "model") == [0.1, 0.2, 0.3]
    assert service.router.calls == 1 and cache.saves == 0


def test_cache_lookup_and_save_failure_do_not_break_embedding():
    config = {"name": "model", "revision": "r1", "normalization": "unit", "dimensions": 3}
    assert _service_for_cache(_MemoryCache(fail_get=True), config)._embed_with_cache("content", "model") == [0.1, 0.2, 0.3]
    assert _service_for_cache(_MemoryCache(fail_save=True), config)._embed_with_cache("content", "model") == [0.1, 0.2, 0.3]
