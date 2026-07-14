def test_chat_returns_response_and_model_used(client, mock_ollama):
    response = client.post("/chat", json={"message": "Explain RAG"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Mock response from qwen3.5:9b"
    assert body["model_used"] == "qwen3.5:9b"
    assert body["conversation_id"]
    assert isinstance(body["latency_ms"], int)


def test_chat_rejects_unknown_conversation(client, mock_ollama):
    response = client.post("/chat", json={"message": "Hello", "conversation_id": "unknown"})

    assert response.status_code == 404
    assert response.json()["error_code"] == "CONVERSATION_NOT_FOUND"


def test_chat_uses_relevant_memory_when_requested(client, mock_ollama, monkeypatch):
    monkeypatch.setattr(
        "app.services.memory_service.MemoryService.search",
        lambda self, query, top_k: [{"content": "The user prefers Vietnamese.", "score": 0.9}],
    )
    captured_messages = []

    def capture_chat(self, model, messages, options, keep_alive, think=None):
        captured_messages.extend(messages)
        return "Mock response from qwen3.5:9b"

    monkeypatch.setattr("app.llm_clients.ollama_client.OllamaClient.chat", capture_chat)
    response = client.post("/chat", json={"message": "Hello", "use_memory": True})

    assert response.status_code == 200
    assert any("The user prefers Vietnamese." in item["content"] for item in captured_messages)


def test_chat_streams_tokens_and_persists_completed_message(client, monkeypatch):
    monkeypatch.setattr("app.llm_clients.ollama_client.OllamaClient.stream_chat", lambda *args, **kwargs: iter(["Hello", " world"]))

    response = client.post("/chat", json={"message": "Stream this", "stream": True})

    assert response.status_code == 200
    assert "event: token" in response.text
    assert "Hello" in response.text
    assert "event: done" in response.text
