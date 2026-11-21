"""Standard error body {"error": {"code", "message", "details"}} (implementation plan step A3)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.errors import (
    AppError,
    Conflict,
    Forbidden,
    NotFound,
    ServiceUnavailable,
    TooManyRequests,
    Unauthorized,
    ValidationFailed,
    field_error,
)
from app.main import app

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def temporary_route() -> Iterator:
    """Register a throwaway route on the real app (so the real handlers run), then remove it."""
    added = []

    def add(path: str, endpoint) -> None:
        app.add_api_route(path, endpoint, methods=["GET"], include_in_schema=False)
        added.append(app.router.routes[-1])

    yield add
    for route in added:
        app.router.routes.remove(route)
    app.openapi_schema = None


def test_error_classes_carry_status_code_and_default_message():
    expected = {
        Unauthorized: (401, "unauthorized"),
        Forbidden: (403, "forbidden"),
        NotFound: (404, "not_found"),
        Conflict: (409, "conflict"),
        ValidationFailed: (422, "validation_error"),
        TooManyRequests: (429, "rate_limited"),
        ServiceUnavailable: (503, "service_unavailable"),
    }
    for cls, (status, code) in expected.items():
        err = cls()
        assert (err.status_code, err.code) == (status, code)
        assert issubclass(cls, AppError) and err.message


def test_field_error_matches_the_schema_validation_shape():
    err = field_error(("query", "q"), "q must not be blank")
    assert err.status_code == 422 and err.code == "validation_error"
    assert err.details == [
        {"type": "value_error", "loc": ["query", "q"], "msg": "q must not be blank"}
    ]


def test_app_error_is_rendered_with_code_details_and_headers(temporary_route):
    def boom():
        raise TooManyRequests(
            "Slow down.", code="rate_limited", details={"scope": "ip"}, headers={"Retry-After": "7"}
        )

    temporary_route("/api/v1/__test/app-error", boom)
    res = client.get("/api/v1/__test/app-error")
    assert res.status_code == 429
    assert res.headers["retry-after"] == "7"
    assert res.json() == {
        "error": {"code": "rate_limited", "message": "Slow down.", "details": {"scope": "ip"}}
    }


def test_unknown_routes_and_methods_use_the_standard_shape():
    missing = client.get("/api/v1/does-not-exist")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"

    wrong_method = client.delete("/api/v1/health")
    assert wrong_method.status_code == 405
    assert wrong_method.json()["error"]["code"] == "method_not_allowed"


def test_validation_errors_list_location_without_submitted_values():
    secret = "Never-Echo-This-1"
    res = client.post("/api/v1/auth/login", json={"identifier": "", "password": secret})
    assert res.status_code == 422
    error = res.json()["error"]
    assert error["code"] == "validation_error"
    assert error["message"] == "Request validation failed."
    assert error["details"] and all(set(e) == {"type", "loc", "msg"} for e in error["details"])
    assert secret not in res.text


def test_unexpected_errors_return_500_without_leaking(temporary_route, caplog):
    def crash():
        raise RuntimeError("db password is hunter2")

    temporary_route("/api/v1/__test/crash", crash)
    res = client.get("/api/v1/__test/crash?phone=0788123456")
    assert res.status_code == 500
    assert res.json() == {
        "error": {
            "code": "internal_error",
            "message": "An unexpected error occurred.",
            "details": None,
        }
    }
    assert "hunter2" not in res.text
    app_logs = [r.getMessage() for r in caplog.records if r.name == "app.errors"]
    assert app_logs == ["Unhandled error on GET /api/v1/__test/crash"]  # no query string


def test_openapi_documents_every_error_with_the_standard_schema():
    spec = app.openapi()
    schemas = spec["components"]["schemas"]
    assert "HTTPValidationError" not in schemas and "ValidationError" not in schemas
    assert set(schemas["ErrorResponse"]["properties"]) == {"error"}
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            for status, response in operation["responses"].items():
                if status.startswith(("4", "5")):
                    schema = response["content"]["application/json"]["schema"]
                    assert schema == {"$ref": "#/components/schemas/ErrorResponse"}, (
                        method,
                        path,
                        status,
                    )
