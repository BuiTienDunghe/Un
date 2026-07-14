from types import SimpleNamespace

import pytest
from qdrant_client.models import VectorParams

from app.stores.qdrant_store import QdrantDimensionMismatchError, QdrantStore


class FakeQdrantClient:
    def collection_exists(self, name):
        return True

    def get_collection(self, name):
        vectors = VectorParams(size=3, distance="Cosine")
        return SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(vectors=vectors)))


def test_existing_collection_requires_matching_embedding_dimension():
    store = QdrantStore.__new__(QdrantStore)
    store.client = FakeQdrantClient()

    with pytest.raises(QdrantDimensionMismatchError, match="dimension 3"):
        store._ensure_collection(4)
