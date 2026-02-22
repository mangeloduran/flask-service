def test_example(client):
    resp = client.get("/api/v1/example")
    assert resp.status_code == 200
    assert resp.get_json() == {"message": "hello"}
