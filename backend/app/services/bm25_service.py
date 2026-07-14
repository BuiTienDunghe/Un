from __future__ import annotations

from rank_bm25 import BM25Okapi

from app.stores.sqlite_store import SQLiteStore
from app.utils.vi_tokenizer import tokenize_vietnamese


class Bm25Service:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def search(self, question: str, top_k: int, document_id: str | None = None) -> list[dict[str, object]]:
        chunks = self.store.get_document_chunks(document_id)
        if not chunks:
            return []
        corpus = [tokenize_vietnamese(str(chunk["content"])) for chunk in chunks]
        scores = BM25Okapi(corpus).get_scores(tokenize_vietnamese(question))
        ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)[:top_k]
        return [{"score": float(score), **chunks[index]} for index, score in ranked if score > 0]
