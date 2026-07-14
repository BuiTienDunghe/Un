def test_conversation_list_detail_and_delete(client, mock_ollama):
    chat = client.post("/chat", json={"message": "Hello"})
    conversation_id = chat.json()["conversation_id"]

    listing = client.get("/conversations")
    detail = client.get(f"/conversations/{conversation_id}")
    deleted = client.delete(f"/conversations/{conversation_id}")

    assert listing.status_code == 200
    assert any(item["id"] == conversation_id for item in listing.json())
    assert detail.status_code == 200
    assert len(detail.json()["messages"]) == 2
    assert deleted.status_code == 204
    assert client.get(f"/conversations/{conversation_id}").status_code == 404
