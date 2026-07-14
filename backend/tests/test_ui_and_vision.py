def test_vision_is_explicitly_not_implemented(client):
    response = client.post("/vision/chat", json={"message": "Describe this image"})

    assert response.status_code == 501
    assert response.json()["error_code"] == "VISION_NOT_IMPLEMENTED"
