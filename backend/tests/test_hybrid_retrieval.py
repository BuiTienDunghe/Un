from app.services.retrieval_service import RetrievalService


def test_rrf_combines_dense_and_bm25_results_without_duplicate_chunks():
    service = RetrievalService.__new__(RetrievalService)
    service.rrf_k = 60
    dense = [{"document_id": "doc_1", "chunk_index": 0, "content": "Dense result", "score": 0.9}]
    sparse = [
        {"document_id": "doc_1", "chunk_index": 0, "content": "Dense result", "score": 2.0},
        {"document_id": "doc_1", "chunk_index": 1, "content": "Sparse result", "score": 1.0},
    ]

    results = service.rrf(dense, sparse, top_k=5)

    assert [result["chunk_index"] for result in results] == [0, 1]
    assert results[0]["score"] > results[1]["score"]
