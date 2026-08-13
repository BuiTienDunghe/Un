def test_dashboard_stats_shape_and_web_counts(client, mock_ollama):
    chat = client.post("/chat", json={"message": "Dashboard stats seed"})
    conversation_id = chat.json()["conversation_id"]

    response = client.get("/api/dashboard/stats")
    body = response.json()

    assert response.status_code == 200
    assert body["web"]["conversation_count"] >= 1
    assert body["web"]["message_count"] >= 2
    assert body["web"]["last_activity_at"]
    assert isinstance(body["discord"]["turn_counts"], dict)
    assert isinstance(body["discord"]["recent_sessions"], list)
    assert body["discord"]["session_count"] >= body["discord"]["active_session_count"]
    client.delete(f"/conversations/{conversation_id}")
