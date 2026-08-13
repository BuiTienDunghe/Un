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


def test_new_conversation_gets_server_side_title(client, mock_ollama):
    chat = client.post("/chat", json={"message": "  Tiêu đề   tự sinh từ tin đầu  "})
    conversation_id = chat.json()["conversation_id"]

    detail = client.get(f"/conversations/{conversation_id}")

    assert detail.status_code == 200
    assert detail.json()["title"] == "Tiêu đề tự sinh từ tin đầu"
    client.delete(f"/conversations/{conversation_id}")


def test_conversation_rename_and_missing_rename(client, mock_ollama):
    chat = client.post("/chat", json={"message": "Hello"})
    conversation_id = chat.json()["conversation_id"]

    renamed = client.patch(f"/conversations/{conversation_id}", json={"title": "Tên mới"})
    detail = client.get(f"/conversations/{conversation_id}")
    missing = client.patch("/conversations/does-not-exist", json={"title": "x"})

    assert renamed.status_code == 204
    assert detail.json()["title"] == "Tên mới"
    assert missing.status_code == 404
    client.delete(f"/conversations/{conversation_id}")
