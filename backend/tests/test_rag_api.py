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


def test_reopened_rag_conversation_still_carries_its_sources(client, mock_ollama, monkeypatch):
    monkeypatch.setattr(
        "app.services.postgres_retrieval_service.PostgresRetrievalService.retrieve",
        lambda self, query, top_k, document_id=None: [
            {"document_id": "doc_a", "filename": "sổ tay.pdf", "chunk_id": "chunk_a", "chunk_index": 0, "page_start": 7, "page_end": 8, "heading_path": "Chương 2", "score": 0.91, "content": "Nội dung được trích dẫn A."},
            {"document_id": "doc_b", "filename": "ghi chú.txt", "chunk_id": "chunk_b", "chunk_index": 3, "page": 2, "score": 0.42, "content": "Nội dung được trích dẫn B."},
        ],
    )

    answered = client.post("/rag/chat", json={"message": "Quy trình in ấn thế nào?"})
    conversation_id = answered.json()["conversation_id"]
    reopened = client.get(f"/conversations/{conversation_id}")

    assert answered.status_code == 200 and reopened.status_code == 200
    question, answer = reopened.json()["messages"]
    assert question["sources"] == []
    # Reopening shows the same citations, in the same order, as the live answer.
    assert [source["chunk_id"] for source in answer["sources"]] == ["chunk_a", "chunk_b"]
    assert [source["filename"] for source in answer["sources"]] == ["sổ tay.pdf", "ghi chú.txt"]
    assert (answer["sources"][0]["page_start"], answer["sources"][0]["page_end"]) == (7, 8)
    assert answer["sources"][0]["heading_path"] == "Chương 2"
    # A chunk carrying only `page` still renders a page number after reload.
    assert answer["sources"][1]["page_start"] == 2
    assert answer["sources"][1]["excerpt"] == "Nội dung được trích dẫn B."
    client.delete(f"/conversations/{conversation_id}")


def test_rag_chat_persists_turn_into_conversation(client, mock_ollama, monkeypatch):
    monkeypatch.setattr(
        "app.services.postgres_retrieval_service.PostgresRetrievalService.retrieve",
        lambda self, query, top_k, document_id=None: [{"document_id": "doc_demo", "filename": "demo.txt", "chunk_id": "chunk_1", "chunk_index": 0, "page": None, "score": 0.99, "content": "RAG context."}],
    )

    first = client.post("/rag/chat", json={"message": "Câu hỏi RAG đầu tiên"})
    conversation_id = first.json()["conversation_id"]
    second = client.post("/rag/chat", json={"message": "Câu tiếp theo", "conversation_id": conversation_id})
    detail = client.get(f"/conversations/{conversation_id}")
    missing = client.post("/rag/chat", json={"message": "x", "conversation_id": "unknown-conv"})

    assert first.status_code == 200 and conversation_id
    assert second.status_code == 200
    assert second.json()["conversation_id"] == conversation_id
    assert detail.status_code == 200
    assert [m["role"] for m in detail.json()["messages"]] == ["user", "assistant", "user", "assistant"]
    assert detail.json()["title"] == "Câu hỏi RAG đầu tiên"
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "CONVERSATION_NOT_FOUND"
    client.delete(f"/conversations/{conversation_id}")


def test_rag_search_returns_sources_without_the_answer_model(client, monkeypatch):
    monkeypatch.setattr(
        "app.services.postgres_retrieval_service.PostgresRetrievalService.retrieve",
        lambda self, query, top_k, document_id=None: [{"document_id": "doc_demo", "filename": "demo.txt", "chunk_id": "chunk_1", "chunk_index": 0, "page": None, "score": 0.99, "content": "RAG retrieves context before answering."}],
    )

    def forbidden_chat(*args, **kwargs):
        raise AssertionError("/rag/search must not call the answer model")

    monkeypatch.setattr("app.services.model_router.ModelRouter.chat", forbidden_chat)

    response = client.post("/rag/search", json={"message": "RAG làm gì?"})

    assert response.status_code == 200
    body = response.json()
    assert "answer" not in body
    assert body["sources"][0]["document_id"] == "doc_demo"
    assert body["sources"][0]["content"] == "RAG retrieves context before answering."


def test_rag_search_with_no_matching_context_returns_an_empty_list(client, monkeypatch):
    monkeypatch.setattr(
        "app.services.postgres_retrieval_service.PostgresRetrievalService.retrieve",
        lambda self, query, top_k, document_id=None: [],
    )

    response = client.post("/rag/search", json={"message": "Câu hỏi ngoài tài liệu", "document_id": "doc_missing"})

    # Search reports absence as an empty result; only /rag/chat treats missing
    # context as an error, because it would otherwise answer ungrounded.
    assert response.status_code == 200
    assert response.json()["sources"] == []


def test_rag_search_clips_to_the_cited_context_budget(client, monkeypatch):
    monkeypatch.setattr(
        "app.services.postgres_retrieval_service.PostgresRetrievalService.retrieve",
        lambda self, query, top_k, document_id=None: [
            {"document_id": "doc_demo", "filename": "demo.txt", "chunk_id": f"chunk_{index}", "chunk_index": index, "page": None, "score": 1.0 - index * 0.1, "content": f"chunk {index}"}
            for index in range(8)
        ],
    )

    response = client.post("/rag/search", json={"message": "RAG làm gì?"})

    # Same max_context_chunks clipping as /rag/chat, so eval-measured sources
    # are exactly the citations the chat path would produce.
    assert [source["chunk_id"] for source in response.json()["sources"]] == ["chunk_0", "chunk_1", "chunk_2", "chunk_3", "chunk_4"]
