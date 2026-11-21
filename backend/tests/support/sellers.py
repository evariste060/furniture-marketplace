"""Seller test helpers (ADR-014): applications and approved sellers through the real API."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from app.models.identity import User
from app.models.marketplace import Store
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


def new_store(name: str | None = None, *, status: str = "approved") -> Store:
    """A transient store (with its owner) for tests that build catalogue rows directly in the
    database (ADR-014 phase 2: every product belongs to a store). Added to the session through
    the product that references it."""
    tag = uuid4().hex[:12]
    now = datetime.now(UTC)
    decided = status != "pending"
    return Store(
        owner=User(  # sellers apply with a verified email (ADR-014 phase 1)
            email=f"store.owner.{tag}@example.com",
            full_name="Store Owner",
            email_verified_at=datetime.now(UTC),
        ),
        name=name or f"Test Store {tag}",
        slug=f"test-store-{tag}",
        contact_email=f"store.{tag}@example.com",
        contact_phone="+250788000999",
        district="Gasabo",
        status=status,
        status_reason="Test reason." if status in ("rejected", "suspended") else None,
        submitted_at=now,
        reviewed_at=now if decided else None,
        approved_at=now if status in ("approved", "suspended") else None,
    )


SELLER_PRODUCTS = "/api/v1/seller/products"
DEFAULT_SELLER = ("default.seller@example.com", "+250788999001", "Default Test Store")


def default_seller(client: TestClient, admin_headers: dict) -> dict:
    """One approved seller per test client (ADR-014 phase 2), approved with admin_headers."""
    cached = client.__dict__.get("_default_seller")
    if cached is None:
        email, phone, name = DEFAULT_SELLER
        cached = approved_seller(client, {"headers": admin_headers}, email, phone, name)
        client.__dict__["_default_seller"] = cached
    return cached


def post_product(client: TestClient, *, json: dict, headers: dict) -> Any:
    """Create a product as production does since SC-05: the default seller adds it to their
    store (POST /seller/products). `headers` are an administrator's, used to approve that
    seller and to apply is_featured, which only staff may set (merchandising)."""
    seller = default_seller(client, headers)
    body = dict(json)
    featured = body.pop("is_featured", None)
    res = client.post(SELLER_PRODUCTS, json=body, headers=seller["headers"])
    if featured is None or res.status_code != 201:
        return res
    patched = client.patch(
        f"/api/v1/staff/products/{res.json()['id']}",
        json={"is_featured": featured},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text
    # The test client's own response class (Starlette may use httpx or httpx2).
    return type(res)(201, json=patched.json(), request=res.request)


# ---- raw-SQL migration tests ---------------------------------------------------------------
def sql_store(conn: Connection) -> str | None:
    """For migration tests that insert products with SQL: a new approved store (and its owner)
    to own them when products.store_id exists at the current revision (ADR-014 phase 2),
    otherwise None (an older schema has no store column)."""
    has_column = conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() "
            "AND table_name = 'products' AND column_name = 'store_id'"
        )
    ).first()
    if has_column is None:
        return None
    owner, store = str(uuid4()), str(uuid4())
    conn.execute(
        text(
            "INSERT INTO users (id, email, full_name, email_verified_at) "
            "VALUES (:id, :email, 'Store owner', now())"
        ),
        {"id": owner, "email": f"owner-{owner}@example.com"},
    )
    conn.execute(
        text(
            "INSERT INTO stores (id, owner_user_id, name, slug, contact_email, contact_phone, "
            "district, status, submitted_at, reviewed_at, approved_at) VALUES (:id, :owner, "
            ":name, :slug, 'shop@example.com', '+250788000001', 'Gasabo', 'approved', now(), "
            "now(), now())"
        ),
        {"id": store, "owner": owner, "name": f"Store {store}", "slug": f"store-{store}"},
    )
    return store


def forget_stores(engine: Engine) -> None:
    """Delete every store of the disposable per-test schema, so a downgrade below phase 1 (which
    refuses while stores exist, and never drops them silently) can run. Call it after
    downgrading below b2d4f6a8c0e1, once products no longer reference stores. Test schemas
    only: never point this at a real database."""
    with engine.begin() as conn:
        schema: str = conn.execute(text("SELECT current_schema()")).scalar_one()
        assert schema.startswith("test_"), schema
        owners: list[Any] = list(
            conn.execute(text("SELECT owner_user_id FROM stores")).scalars().all()
        )
        conn.execute(text("DELETE FROM store_status_history"))
        conn.execute(text("DELETE FROM stores"))
        if owners:  # the owner accounts the store helpers created
            conn.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": list(owners)})
