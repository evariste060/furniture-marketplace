from fastapi.testclient import TestClient


def test_health_reaches_the_real_database(client: TestClient):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
        "checks": {"database": "ok", "storage": "ok", "catalogue": "ok"},
    }
