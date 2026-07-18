def test_upload_document_success(client):
    response = client.post("/documents/upload", files={"file": ("notes.txt", b"Local AI Core stores documents.", "text/plain")})

    assert response.status_code == 201
    body = response.json()
    assert body["document_id"].startswith("doc_")
    assert body["status"] == "uploaded"


def test_upload_uses_a_per_document_folder(client):
    response = client.post("/documents/upload", files={"file": ("notes.txt", b"saved once", "text/plain")})

    document_id = response.json()["document_id"]
    stored_file = client.app.state.settings.documents_path / document_id / "original.txt"
    assert stored_file.read_bytes() == b"saved once"


def test_upload_deduplicates_identical_content(client):
    first = client.post("/documents/upload", files={"file": ("a.txt", b"same bytes", "text/plain")}).json()
    second = client.post("/documents/upload", files={"file": ("b.txt", b"same bytes", "text/plain")}).json()

    assert second["duplicate"] is True
    assert second["document_id"] == first["document_id"]
    assert len(first["content_hash"]) == 64


def test_replace_source_creates_a_new_ingestion_version(client, mock_ollama, monkeypatch):
    monkeypatch.setattr("app.stores.qdrant_store.QdrantStore.upsert_chunks", lambda *args, **kwargs: None)
    upload = client.post("/documents/upload", files={"file": ("a.txt", b"first source", "text/plain")}).json()
    response = client.post(f"/documents/{upload['document_id']}/replace", files={"file": ("a.txt", b"second source", "text/plain")})

    assert response.status_code == 202
    assert response.json()["duplicate"] is False
    assert response.json()["index_version"] == 1


def test_upload_invalid_file_type(client):
    response = client.post("/documents/upload", files={"file": ("malware.exe", b"no", "application/octet-stream")})

    assert response.status_code == 415
    assert response.json()["error_code"] == "UNSUPPORTED_FILE_TYPE"


def test_upload_rejects_mismatched_mime_type(client):
    response = client.post(
        "/documents/upload",
        files={"file": ("notes.txt", b"not really plain text", "application/pdf")},
    )

    assert response.status_code == 415
    assert response.json()["error_code"] == "UNSUPPORTED_FILE_TYPE"


def test_document_status_returns_stored_metadata(client):
    upload = client.post(
        "/documents/upload",
        files={"file": ("notes.txt", b"Document status metadata.", "text/plain")},
    )

    response = client.get(f"/documents/{upload.json()['document_id']}/status")

    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == upload.json()["document_id"]
    assert body["status"] == "uploaded"
    # PostgreSQL creates version 1 in staging at upload time; it is not active
    # until ingestion activation succeeds.
    assert body["active_index_version"] == 1
    assert body["source_available"] is True
    assert body["retention_policy"] == "permanent"


def test_remove_source_keeps_indexed_knowledge_but_blocks_reindex(client):
    upload = client.post("/documents/upload", files={"file": ("notes.txt", b"Keep extracted knowledge.", "text/plain")}).json()

    assert client.delete(f"/documents/{upload['document_id']}/source").status_code == 204
    status = client.get(f"/documents/{upload['document_id']}/status").json()
    assert status["source_available"] is False
    response = client.post("/documents/index", json={"document_id": upload["document_id"]})
    assert response.status_code == 409
    assert response.json()["error_code"] == "SOURCE_UNAVAILABLE"


def test_retention_can_pin_a_document(client):
    upload = client.post("/documents/upload", files={"file": ("notes.txt", b"Pin this document.", "text/plain")}).json()

    response = client.patch(f"/documents/{upload['document_id']}/retention", json={"pinned": True, "retention_policy": "temporary"})

    assert response.status_code == 200
    assert response.json()["pinned"] is True
    assert response.json()["retention_policy"] == "temporary"


def test_permanent_delete_cascades_postgres_records(client, monkeypatch):
    monkeypatch.setattr("app.stores.qdrant_store.QdrantStore.delete_document", lambda *args, **kwargs: None)
    upload = client.post("/documents/upload", files={"file": ("notes.txt", b"Delete all document data.", "text/plain")}).json()

    assert client.delete(f"/documents/{upload['document_id']}").status_code == 204
    assert client.get(f"/documents/{upload['document_id']}/status").status_code == 404


def test_index_creates_chunks(client, mock_ollama, monkeypatch):
    monkeypatch.setattr("app.stores.qdrant_store.QdrantStore.upsert_chunks", lambda *args, **kwargs: None)
    upload = client.post(
        "/documents/upload",
        files={"file": ("notes.txt", b"RAG retrieves relevant context. It then answers from that context.", "text/plain")},
    )

    response = client.post("/documents/index", json={"document_id": upload.json()["document_id"]})

    assert response.status_code == 202
    run = client.get(f"/documents/ingestions/{response.json()['ingestion_run_id']}").json()
    for _ in range(30):
        if run["status"] in {"completed", "failed"}:
            break
        import time; time.sleep(0.03)
        run = client.get(f"/documents/ingestions/{response.json()['ingestion_run_id']}").json()
    assert run["status"] == "completed"
    assert run["chunks_count"] >= 1
