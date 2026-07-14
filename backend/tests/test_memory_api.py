def test_memory_add_search_update_and_delete(client, mock_ollama, monkeypatch):
    memories: dict[str, dict[str, object]] = {}

    def upsert(self, memory_id, content, memory_type, importance, vector):
        memories[memory_id] = {"memory_id": memory_id, "content": content, "memory_type": memory_type, "importance": importance, "score": 0.9}

    monkeypatch.setattr("app.stores.qdrant_store.QdrantStore.upsert_memory", upsert)
    monkeypatch.setattr("app.stores.qdrant_store.QdrantStore.search_memories", lambda self, vector, top_k: list(memories.values())[:top_k])
    monkeypatch.setattr("app.stores.qdrant_store.QdrantStore.delete_memory", lambda self, memory_id: memories.pop(memory_id, None))

    created = client.post("/memory/add", json={"content": "Prefer concise Vietnamese responses.", "importance": 0.8})
    memory_id = created.json()["id"]
    searched = client.post("/memory/search", json={"query": "language preference"})
    updated = client.put(f"/memory/{memory_id}", json={"content": "Prefer concise answers.", "memory_type": "preference", "importance": 1.0})
    deleted = client.delete(f"/memory/{memory_id}")

    assert created.status_code == 201
    assert searched.status_code == 200
    assert searched.json()[0]["memory_id"] == memory_id
    assert updated.status_code == 200
    assert updated.json()["importance"] == 1.0
    assert deleted.status_code == 204
    assert client.put(f"/memory/{memory_id}", json={"content": "x"}).status_code == 404
