def test_health_returns_ok(client, mock_ollama):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["postgres"] == "ok"
    assert "sqlite" not in response.json()
    assert response.json()["ollama"] == "ok"


def test_health_returns_degraded_when_ollama_is_down(client, monkeypatch):
    monkeypatch.setattr("app.llm_clients.ollama_client.OllamaClient.healthcheck", lambda self: False)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["ollama"] == "unavailable"
