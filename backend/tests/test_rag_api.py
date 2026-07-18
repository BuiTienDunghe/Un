def test_rag_chat_returns_sources(client, mock_ollama, monkeypatch):
    monkeypatch.setattr(
        "app.services.postgres_retrieval_service.PostgresRetrievalService.retrieve",
        lambda self, query, top_k, document_id=None: [{"document_id": "doc_demo", "filename": "demo.txt", "chunk_index": 0, "page": None, "score": 0.99, "content": "RAG retrieves context before answering."}],
    )

    response = client.post("/rag/chat", json={"message": "What does RAG do?"})

    assert response.status_code == 200
    body = response.json()
    assert body["model_used"] == "qwen3.5:9b"
    assert body["sources"][0]["document_id"] == "doc_demo"


def test_rag_chat_rejects_missing_context(client, mock_ollama, monkeypatch):
    monkeypatch.setattr(
        "app.services.postgres_retrieval_service.PostgresRetrievalService.retrieve",
        lambda self, query, top_k, document_id=None: [],
    )

    response = client.post("/rag/chat", json={"message": "What does RAG do?", "document_id": "doc_missing"})

    assert response.status_code == 422
    assert response.json()["error_code"] == "INSUFFICIENT_CONTEXT"


def test_rag_chat_streams_tokens_and_sources(client, monkeypatch):
    monkeypatch.setattr(
        "app.services.postgres_retrieval_service.PostgresRetrievalService.retrieve",
        lambda self, query, top_k, document_id=None: [{"document_id": "doc_demo", "filename": "demo.txt", "chunk_index": 0, "page": None, "score": 0.99, "content": "RAG retrieves context before answering."}],
    )
    monkeypatch.setattr("app.llm_clients.ollama_client.OllamaClient.embed", lambda self, model, text: [0.1, 0.2, 0.3])
    monkeypatch.setattr("app.llm_clients.ollama_client.OllamaClient.stream_chat", lambda *args, **kwargs: iter(["RAG", " answer"]))

    response = client.post("/rag/chat", json={"message": "What does RAG do?", "stream": True})

    assert response.status_code == 200
    assert "sources" in response.text
    assert '"content": "RAG"' in response.text
    assert '"content": " answer"' in response.text
