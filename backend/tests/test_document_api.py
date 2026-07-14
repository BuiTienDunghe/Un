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
    assert response.json() == {
        "document_id": upload.json()["document_id"],
        "filename": "notes.txt",
        "status": "uploaded",
        "chunks_count": 0,
        "ocr_pages_count": 0,
        "error_message": None,
    }


def test_index_creates_chunks(client, mock_ollama, monkeypatch):
    monkeypatch.setattr("app.stores.qdrant_store.QdrantStore.upsert_chunks", lambda *args, **kwargs: None)
    upload = client.post(
        "/documents/upload",
        files={"file": ("notes.txt", b"RAG retrieves relevant context. It then answers from that context.", "text/plain")},
    )

    response = client.post("/documents/index", json={"document_id": upload.json()["document_id"]})

    assert response.status_code == 200
    assert response.json()["status"] == "indexed"
    assert response.json()["chunks_created"] >= 1
