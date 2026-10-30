def test_vision_says_when_nothing_serves_and_needs_an_image(client, monkeypatch):
    response = client.post("/vision/chat", json={"message": "Describe this image"})
    assert response.status_code == 422
    assert response.json()["error_code"] == "IMAGE_REQUIRED"

    monkeypatch.delitem(client.app.state.model_router.models, "vision")
    response = client.post("/vision/chat", json={"message": "Describe this image"})
    assert response.status_code == 501
    assert response.json()["error_code"] == "VISION_NOT_IMPLEMENTED"
