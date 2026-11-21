"""Every seller route is guarded (ADR-014). Seller routes are enumerated from the application, so
a route added later without require_approved_seller fails here: only the three application
routes, which any signed-in customer uses, are exempt. No seller route takes a store id: the
store is always the caller's own."""

import pytest
from fastapi.testclient import TestClient

from tests.integration.test_staff_authorization_api import _api_routes, _concrete
from tests.support.sellers import approved_seller, decide

APPLICATION_ROUTES = {
    ("GET", "/api/v1/seller/application"),
    ("POST", "/api/v1/seller/application"),
    ("PUT", "/api/v1/seller/application"),
}


def _seller_scoped(dependant) -> bool:
    for sub in dependant.dependencies:
        if getattr(sub.call, "seller_scoped", False) or _seller_scoped(sub):
            return True
    return False


def _seller_routes() -> list[tuple[str, str, bool]]:
    from app.main import app

    routes = []
    for path, methods, dependant in _api_routes(app.routes):
        if not path.startswith("/api/v1/seller"):
            continue
        for method in sorted(methods - {"HEAD", "OPTIONS"}):
            routes.append((method, path, _seller_scoped(dependant)))
    return routes


SELLER_ROUTES = _seller_routes()
SCOPED = [(m, p) for m, p, scoped in SELLER_ROUTES if scoped]


def test_every_seller_route_is_scoped_to_an_approved_store():
    assert len(SELLER_ROUTES) >= 5
    unguarded = {(m, p) for m, p, scoped in SELLER_ROUTES if not scoped}
    assert unguarded == APPLICATION_ROUTES
    assert ("PATCH", "/api/v1/seller/store") in SCOPED


def test_no_seller_route_names_a_store():
    for _, path, _ in SELLER_ROUTES:
        assert "{store" not in path, path


@pytest.mark.parametrize(("method", "path"), SCOPED, ids=[f"{m} {p}" for m, p in SCOPED])
def test_a_suspended_seller_is_refused_on_every_seller_route(
    client: TestClient, admin_auth: dict, method: str, path: str
):
    seller = approved_seller(client, admin_auth, "susp@example.com", "+250788100050", "Halted")
    decided = decide(client, admin_auth, seller["store_id"], "suspended", "Suspended for a test.")
    assert decided.status_code == 200
    res = client.request(method, _concrete(path), json={}, headers=seller["headers"])
    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "seller_not_approved"


@pytest.mark.parametrize(("method", "path"), SCOPED, ids=[f"{m} {p}" for m, p in SCOPED])
def test_a_customer_without_a_store_is_refused_on_every_seller_route(
    client: TestClient, customer_auth: dict, method: str, path: str
):
    res = client.request(method, _concrete(path), json={}, headers=customer_auth["headers"])
    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "seller_not_approved"
