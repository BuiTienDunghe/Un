def test_code_chat_uses_code_model(client, mock_ollama):
    response = client.post("/code/chat", json={"message": "Explain this error", "code_context": "TypeError"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Mock response from qwen2.5-coder:7b"
    assert body["model_used"] == "qwen2.5-coder:7b"


def test_code_chat_streams_tokens(client, monkeypatch):
    monkeypatch.setattr("app.llm_clients.ollama_client.OllamaClient.stream_chat", lambda *args, **kwargs: iter(["Fix", " it"]))

    response = client.post("/code/chat", json={"message": "Stream code", "stream": True})

    assert response.status_code == 200
    assert "Fix" in response.text
    assert "event: done" in response.text
