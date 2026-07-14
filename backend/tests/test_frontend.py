def test_frontend_is_served(client):
    response = client.get("/ui/")

    assert response.status_code == 200
    assert "Trợ lý AI" in response.text
