from pathlib import Path

from app.stores.sqlite_store import SQLiteStore
from app.stores.qdrant_store import QdrantStore
from app.services.retrieval_service import RetrievalService


def test_chunk_lookup_returns_requested_content(tmp_path: Path):
    store = SQLiteStore(tmp_path / "storage.db")
    store.initialize()
    store.create_document("doc_one", "one.txt", "doc_one.txt", "text/plain")
    store.create_document("doc_two", "two.txt", "doc_two.txt", "text/plain")
    store.replace_document_chunks("doc_one", [("first content", 1, "native"), ("second content", 2, "ocr")])
    store.replace_document_chunks("doc_two", [("other content", 1, "native")])

    result = store.get_chunks_by_keys([("doc_one", 1), ("doc_two", 0), ("missing", 0)])

    assert result[("doc_one", 1)]["content"] == "second content"
    assert result[("doc_one", 1)]["extraction_method"] == "ocr"
    assert result[("doc_two", 0)]["content"] == "other content"
    assert ("missing", 0) not in result


def test_qdrant_document_payload_excludes_chunk_content():
    class Client:
        def delete(self, **_: object) -> None:
            return None

        def upsert(self, **kwargs: object) -> None:
            self.points = kwargs["points"]

    store = QdrantStore.__new__(QdrantStore)
    store.client = Client()
    store.collection_name = "documents"
    store._ensure_collection = lambda _: None
    store._retry = lambda operation: operation()

    store.upsert_chunks("doc_one", "one.txt", [("private chunk text", 1, "native")], [[0.1, 0.2]])

    assert "content" not in store.client.points[0].payload


def test_dense_retrieval_resolves_qdrant_result_content_from_sqlite(tmp_path: Path):
    store = SQLiteStore(tmp_path / "storage.db")
    store.initialize()
    store.create_document("doc_one", "one.txt", "doc_one.txt", "text/plain")
    store.replace_document_chunks("doc_one", [("SQLite is the source of truth", 1, "native")])

    class Qdrant:
        def search(self, *_: object) -> list[dict[str, object]]:
            return [{"document_id": "doc_one", "chunk_index": 0, "score": 0.9}]

    class Router:
        def embed(self, _: str) -> tuple[list[float], str]:
            return [0.1], "embedding"

    class Bm25:
        def search(self, *_: object) -> list[dict[str, object]]:
            return []

    class Reranker:
        enabled = False
        candidate_limit = 5

        def rerank(self, _: str, candidates: list[dict[str, object]], __: int) -> list[dict[str, object]]:
            return candidates

    result = RetrievalService(Qdrant(), Router(), Bm25(), Reranker(), store, "dense", 60).retrieve("truth", 1, None)

    assert result[0]["content"] == "SQLite is the source of truth"
