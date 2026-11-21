"""Seller test helpers (ADR-014): applications and approved sellers through the real API."""

from fastapi.testclient import TestClient

from tests.conftest import _register

APPLY = "/api/v1/seller/application"
SELLER_STORE = "/api/v1/seller/store"
STAFF_SELLERS = "/api/v1/staff/sellers"
APPLICATION = {
    "name": "Kigali Oak Works",
    "description": "Hand-made solid wood tables.\n\nDelivered in Kigali.",
    "contact_email": " Sales@OakWorks.Example.RW ",
    "contact_phone": "0788 765 432",
    "district": "Gasabo",
    "sector": "Kimironko",
    "street_address": "KG 11 Ave",
}


def application(**changes) -> dict:
    return {**APPLICATION, **changes}


def apply(client: TestClient, auth: dict, **changes):
    return client.post(APPLY, json=application(**changes), headers=auth["headers"])


def decide(client: TestClient, admin: dict, store_id: str, status: str, reason: str | None = None):
    body: dict = {"status": status}
    if reason is not None:
        body["reason"] = reason
    return client.patch(f"{STAFF_SELLERS}/{store_id}/status", json=body, headers=admin["headers"])


def approved_seller(
    client: TestClient, admin: dict, email: str, phone: str, store_name: str
) -> dict:
    """A verified customer whose store `store_name` an administrator approved. Returns the
    customer's auth dict with the store's id and slug added."""
    auth = _register(client, email, phone, f"Owner of {store_name}")
    res = apply(client, auth, name=store_name, contact_email=email)
    assert res.status_code == 201, res.text
    store = res.json()
    approved = decide(client, admin, store["id"], "approved")
    assert approved.status_code == 200, approved.text
    return {**auth, "store_id": store["id"], "store_slug": store["slug"]}
