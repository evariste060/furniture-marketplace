from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db.session import get_db
from app.main import app

client = TestClient(app)


class FakeSession:
    """Stands in for the database session so the health probe runs without PostgreSQL."""

    def __init__(self, reachable: bool) -> None:
        self.reachable = reachable
        self.statements: list[str] = []

    def execute(self, statement):
        self.statements.append(str(statement))
        if not self.reachable:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    def rollback(self) -> None:
        pass


@pytest.fixture
def session(request) -> Iterator[FakeSession]:
    fake = FakeSession(reachable=request.param)
    app.dependency_overrides[get_db] = lambda: fake
    try:
        yield fake
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.parametrize("session", [True], indirect=True)
def test_health_checks_the_database(session: FakeSession):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
        "checks": {"database": "ok", "storage": "ok", "catalogue": "ok"},
    }
    assert session.statements == ["SET LOCAL statement_timeout = '2s'", "SELECT 1"]


@pytest.mark.parametrize("session", [False], indirect=True)
def test_health_reports_an_unreachable_database_as_503(
    session: FakeSession, caplog: pytest.LogCaptureFixture
):
    response = client.get("/api/v1/health")
    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "database_unavailable",
            "message": "The database is unreachable.",
            "details": None,
        }
    }
    assert "connection refused" not in caplog.text  # only the exception type is logged


def test_cors_allowed_origin():
    response = client.options(
        "/api/v1/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_rejects_unknown_origin():
    response = client.options(
        "/api/v1/health",
        headers={"Origin": "https://untrusted.example", "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize(
    ("path", "method", "header"),
    [
        ("/api/v1/cart", "GET", "x-cart-token"),  # guest carts (module 11)
        ("/api/v1/cart/items", "POST", "content-type, x-cart-token"),
        ("/api/v1/inventory/SKU-1/adjustments", "POST", "authorization, idempotency-key"),
    ],
)
def test_cors_preflight_allows_the_api_custom_headers(path, method, header):
    response = client.options(
        path,
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": header,
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    allowed = response.headers["access-control-allow-headers"].lower()
    for name in header.split(", "):
        assert name in allowed


def test_cors_preflight_with_custom_headers_rejects_an_unknown_origin():
    response = client.options(
        "/api/v1/cart",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-cart-token",
        },
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_cors_preflight_still_refuses_unlisted_headers():
    response = client.options(
        "/api/v1/cart",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-something-else",
        },
    )
    assert response.status_code == 400


class BrokenStorage:
    def free_bytes(self):
        raise OSError("disk gone")


@pytest.mark.parametrize("session", [True], indirect=True)
def test_unusable_storage_is_reported_as_degraded_not_down(
    session: FakeSession, caplog: pytest.LogCaptureFixture
):
    from app.integrations.media import get_media_storage

    app.dependency_overrides[get_media_storage] = BrokenStorage
    try:
        response = client.get("/api/v1/health")
    finally:
        app.dependency_overrides.pop(get_media_storage, None)
    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "database": "ok",
        "checks": {"database": "ok", "storage": "degraded", "catalogue": "ok"},
    }
    assert "disk gone" not in caplog.text  # only the exception type is logged
