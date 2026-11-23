"""SC-06 (ADR-014 phase 7): store operations are the sellers', not the administrator's.

The staff routes for orders, payments, stock, catalogue editing, the catalogue import and bulk
photos stay declared, but their permissions are held by no role in V1, so the Marketplace
Administrator is refused on the backend (403 permission_denied), whatever the admin UI shows. The
administrator still moderates a product: its visibility and featured flag, nothing else.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.roles import ROLE_PERMISSIONS, UNASSIGNED_PERMISSIONS
from tests.support.sellers import post_product

STAFF = "/api/v1/staff"
SOME = uuid.uuid4()

REFUSED = [
    ("get", f"{STAFF}/orders", None),
    ("get", f"{STAFF}/orders/{SOME}", None),
    ("patch", f"{STAFF}/orders/{SOME}/status", {"status": "cancelled", "reason": "Customer asked"}),
    ("get", f"{STAFF}/payments", None),
    ("post", f"{STAFF}/payments/{SOME}/confirm-cod", {}),
    ("get", "/api/v1/inventory", None),
    ("post", "/api/v1/inventory/SKU-1/adjustments", {"delta": 1, "reason": "count"}),
    ("get", f"{STAFF}/reports/stock", None),
    ("get", f"{STAFF}/reports/stock/export", None),
    ("post", f"{STAFF}/products/bulk-activate", {"product_ids": [str(SOME)]}),
    ("post", f"{STAFF}/products/{SOME}/variants", {"sku": "SKU-X", "name": "Oak", "price": 1000}),
    ("patch", f"{STAFF}/products/{SOME}/variants/{SOME}", {"price": 1000}),
    ("delete", f"{STAFF}/products/{SOME}/variants/{SOME}", None),
    ("put", f"{STAFF}/products/{SOME}/images/order", {"image_ids": []}),
    ("patch", f"{STAFF}/images/{SOME}", {"alt_text": "x"}),
    ("delete", f"{STAFF}/images/{SOME}", None),
    ("get", f"{STAFF}/imports/template", None),
    ("get", f"{STAFF}/jobs/{SOME}", None),
]


def test_no_role_holds_a_store_operation_permission():
    for role, permissions in ROLE_PERMISSIONS.items():
        assert not permissions & UNASSIGNED_PERMISSIONS, role


@pytest.mark.parametrize(("method", "path", "body"), REFUSED)
def test_the_administrator_is_refused_every_store_operation(
    client: TestClient, admin_auth: dict, method: str, path: str, body
):
    kwargs = {"headers": admin_auth["headers"]}
    if body is not None:
        kwargs["json"] = body
    res = getattr(client, method)(path, **kwargs)
    assert res.status_code == 403, (path, res.text)
    assert res.json()["error"]["code"] == "permission_denied"


@pytest.fixture
def product(client: TestClient, admin_auth: dict) -> dict:
    h = admin_auth["headers"]
    category = client.post(f"{STAFF}/categories", json={"name": "Sofas"}, headers=h).json()
    res = post_product(client, json={"name": "Oak sofa", "category_id": category["id"]}, headers=h)
    assert res.status_code == 201, res.text
    return res.json()


def test_the_administrator_moderates_visibility_and_featured_only(
    client: TestClient, admin_auth: dict, product: dict
):
    h = admin_auth["headers"]
    url = f"{STAFF}/products/{product['id']}"
    hidden = client.patch(url, json={"status": "hidden", "is_featured": True}, headers=h)
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["status"] == "hidden" and hidden.json()["is_featured"] is True
    for body in ({"name": "Renamed"}, {"description": "New"}, {"status": "archived", "name": "X"}):
        res = client.patch(url, json=body, headers=h)
        assert res.status_code == 403, (body, res.text)
        assert res.json()["error"]["code"] == "permission_denied"
    assert client.get(url, headers=h).json()["name"] == "Oak sofa"
