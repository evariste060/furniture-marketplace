"""GET / identifies the service; every other unknown path is still a structured 404."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_answers_200_with_the_service_information():
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "FurniHub API"
    assert body["status"] == "ok"
    assert body["message"] == "Welcome to the FurniHub API."


def test_root_links_to_the_health_and_documentation_endpoints():
    assert client.get("/").json()["links"] == {
        "health": "/api/v1/health",
        "docs": "/docs",
        "redoc": "/redoc",
        "openapi": "/api/v1/openapi.json",
    }


def test_root_health_link_is_a_real_route():
    health = client.get("/").json()["links"]["health"]
    assert "get" in app.openapi()["paths"][health]


@pytest.mark.parametrize("link", ["docs", "redoc", "openapi"])
def test_root_documentation_links_resolve(link: str):
    target = client.get("/").json()["links"][link]
    assert client.get(target).status_code == 200


@pytest.mark.parametrize("path", ["/no-such-route", "/api/v1/no-such-route", "/root"])
def test_unknown_routes_keep_the_structured_404(path: str):
    response = client.get(path)
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Not Found", "details": None}
    }
