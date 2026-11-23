"""ADR-014 phase 2: the seller's own catalogue, cross-store isolation, staff moderation, and the
approved-store rule of the public catalogue.

Seller A and seller B each own an approved store. Every seller route is tried by each against
the other's product, variant, image and SKU: the answer is always 404, exactly like a resource
that does not exist, and nothing changes.
"""

import uuid

import pytest
from sqlalchemy import func, select

from app.models import InventoryBalance, Product, ProductImage, ProductVariant
from app.models.marketplace import Store
from app.models.operations import AuditRecord
from tests.integration.test_image_admin_api import image_bytes, storage  # noqa: F401
from tests.support.catalog import force_status
from tests.support.sellers import approved_seller, decide

# SC-06: the staff routes for orders, payments, stock and catalogue editing used here are held by
# no role in V1; these tests grant them to the administrator (tests/conftest.py).
pytestmark = pytest.mark.usefixtures("store_operations_granted")

SELLER = "/api/v1/seller"
STAFF = "/api/v1/staff"
PUBLIC = "/api/v1/catalog"
STORES = "/api/v1/stores"


def code(res) -> str:
    return res.json()["error"]["code"]


@pytest.fixture
def market(client, admin_auth) -> dict:
    """Two approved stores, a category, and one product with a variant and stock in each."""
    h = admin_auth["headers"]
    category = client.post(f"{STAFF}/categories", json={"name": "Sofas"}, headers=h).json()
    a = approved_seller(client, admin_auth, "a@example.com", "+250788100001", "Oak Store")
    b = approved_seller(client, admin_auth, "b@example.com", "+250788100002", "Teak Store")
    out = {"admin": h, "category_id": category["id"], "a": a, "b": b}
    for key, sku in (("a", "OAK-1"), ("b", "TEAK-1")):
        seller = out[key]
        product = client.post(
            f"{SELLER}/products",
            json={"name": f"{key.upper()} Sofa", "category_id": category["id"]},
            headers=seller["headers"],
        )
        assert product.status_code == 201, product.text
        variant = client.post(
            f"{SELLER}/products/{product.json()['id']}/variants",
            json={"sku": sku, "name": "Standard", "price": 100_000},
            headers=seller["headers"],
        )
        assert variant.status_code == 201, variant.text
        stock = client.post(
            f"{SELLER}/inventory/{sku}/adjustments",
            json={"reason": "receipt", "quantity_delta": 5},
            headers={**seller["headers"], "Idempotency-Key": f"opening-{sku}"},
        )
        assert stock.status_code == 201, stock.text
        seller["product"] = product.json()
        seller["variant"] = variant.json()
        seller["sku"] = sku
    return out


def add_image(client, seller: dict) -> dict:
    res = client.post(
        f"{SELLER}/products/{seller['product']['id']}/images",
        files={"file": ("sofa.jpg", image_bytes(size=(800, 600)), "image/jpeg")},
        headers=seller["headers"],
    )
    assert res.status_code == 201, res.text
    return res.json()


# ---- the seller's own catalogue ----------------------------------------------------------------
def test_a_seller_creates_products_in_their_own_store(client, db, market):
    a = market["a"]
    product = db.get(Product, uuid.UUID(a["product"]["id"]))
    assert product is not None and str(product.store_id) == a["store_id"]
    assert a["product"]["store_id"] == a["store_id"] and a["product"]["status"] == "draft"
    [audit] = db.scalars(
        select(AuditRecord).where(
            AuditRecord.action == "catalog.product_create",
            AuditRecord.entity_id == str(product.id),
        )
    ).all()
    assert str(audit.actor_user_id) == str(a["user"]["id"])
    assert str(audit.change_summary["store_id"]) == a["store_id"]


def test_store_and_merchandising_fields_are_refused_from_seller_bodies(client, db, market):
    a, b = market["a"], market["b"]
    for body in (
        {"name": "Chair", "category_id": market["category_id"], "store_id": b["store_id"]},
        {"name": "Chair", "category_id": market["category_id"], "is_featured": True},
    ):
        res = client.post(f"{SELLER}/products", json=body, headers=a["headers"])
        assert res.status_code == 422, res.text
    path = f"{SELLER}/products/{a['product']['id']}"
    for body in ({"store_id": b["store_id"]}, {"is_featured": True}):
        assert client.patch(path, json=body, headers=a["headers"]).status_code == 422
    product = db.get(Product, uuid.UUID(a["product"]["id"]))
    assert str(product.store_id) == a["store_id"] and product.is_featured is False
    assert db.scalar(select(func.count(Product.id))) == 2


def test_a_seller_lists_and_reads_only_their_own_products(client, market):
    a, b = market["a"], market["b"]
    page = client.get(f"{SELLER}/products", headers=a["headers"]).json()
    assert [item["id"] for item in page["items"]] == [a["product"]["id"]] and page["total"] == 1
    assert page["items"][0]["store"] == {
        "id": a["store_id"],
        "name": "Oak Store",
        "slug": a["store_slug"],
    }
    stock = client.get(f"{SELLER}/inventory", headers=a["headers"]).json()
    assert [row["sku"] for row in stock["items"]] == ["OAK-1"] and stock["total"] == 1
    assert stock["items"][0]["on_hand"] == 5
    own = client.get(f"{SELLER}/products/{a['product']['id']}", headers=a["headers"])
    assert own.status_code == 200 and own.json()["variants"][0]["sku"] == "OAK-1"
    assert client.get(f"{SELLER}/products", headers=b["headers"]).json()["total"] == 1


@pytest.mark.parametrize(("caller", "owner"), [("a", "b"), ("b", "a")])
def test_another_stores_products_variants_images_and_stock_are_404(
    client,
    db,
    market,
    storage,  # noqa: F811
    caller,
    owner,
):
    me, other = market[caller], market[owner]
    image = add_image(client, other)
    product_id, variant_id = other["product"]["id"], other["variant"]["id"]
    h = me["headers"]
    base = f"{SELLER}/products/{product_id}"
    attempts = {
        "read": client.get(base, headers=h),
        "update": client.patch(base, json={"name": "Taken over"}, headers=h),
        "archive": client.patch(base, json={"status": "archived"}, headers=h),
        "add variant": client.post(
            f"{base}/variants", json={"sku": "X-1", "name": "X", "price": 1}, headers=h
        ),
        "update variant": client.patch(
            f"{base}/variants/{variant_id}", json={"price": 1}, headers=h
        ),
        "deactivate variant": client.delete(f"{base}/variants/{variant_id}", headers=h),
        "upload image": client.post(
            f"{base}/images",
            files={"file": ("x.jpg", image_bytes(size=(400, 300)), "image/jpeg")},
            headers=h,
        ),
        "reorder images": client.put(
            f"{base}/images/order", json={"image_ids": [image["id"]]}, headers=h
        ),
        "update image": client.patch(
            f"{SELLER}/images/{image['id']}", json={"alt_text": "Mine now"}, headers=h
        ),
        "delete image": client.delete(f"{SELLER}/images/{image['id']}", headers=h),
        "read stock": client.get(f"{SELLER}/inventory/{other['sku']}", headers=h),
        "adjust stock": client.post(
            f"{SELLER}/inventory/{other['sku']}/adjustments",
            json={"reason": "adjustment", "quantity_delta": -5},
            headers={**h, "Idempotency-Key": "cross-store-1"},
        ),
    }
    assert {name: r.status_code for name, r in attempts.items()} == dict.fromkeys(attempts, 404)
    # The same answer as a resource that does not exist: nothing about the other store leaks.
    unknown = client.get(f"{SELLER}/products/{uuid.uuid4()}", headers=h).json()
    assert attempts["read"].json() == unknown
    assert code(attempts["read stock"]) == "sku_not_found"
    assert code(attempts["update image"]) == "image_not_found"
    db.expire_all()
    product = db.get(Product, uuid.UUID(product_id))
    assert (product.name, product.status) == (f"{owner.upper()} Sofa", "draft")
    variant = db.get(ProductVariant, uuid.UUID(variant_id))
    assert (variant.price, variant.is_active) == (100_000, True)
    images = db.scalars(select(ProductImage).where(ProductImage.product_id == product.id)).all()
    assert [(str(i.id), i.alt_text) for i in images] == [(image["id"], None)]
    balance = db.scalar(
        select(InventoryBalance).where(InventoryBalance.variant_id == uuid.UUID(variant_id))
    )
    assert balance is not None and balance.on_hand == 5


def test_a_suspended_seller_loses_their_catalogue_at_once(client, market):
    a = market["a"]
    suspended = decide(
        client,
        {"headers": market["admin"]},
        a["store_id"],
        "suspended",
        "Paused for a stock review.",
    )
    assert suspended.status_code == 200, suspended.text
    for res in (
        client.get(f"{SELLER}/products", headers=a["headers"]),
        client.patch(
            f"{SELLER}/products/{a['product']['id']}", json={"name": "X"}, headers=a["headers"]
        ),
        client.get(f"{SELLER}/inventory", headers=a["headers"]),
    ):
        assert res.status_code == 403 and code(res) == "seller_not_approved"


# ---- staff moderation (SC-05) --------------------------------------------------------------
def test_administrators_moderate_every_stores_products_but_do_not_create(client, db, market):
    h = market["admin"]
    a, b = market["a"], market["b"]
    listed = client.get(f"{STAFF}/products", headers=h).json()
    assert {item["store"]["slug"] for item in listed["items"]} == {a["store_slug"], b["store_slug"]}
    only_b = client.get(f"{STAFF}/products", params={"store_id": b["store_id"]}, headers=h)
    assert [item["id"] for item in only_b.json()["items"]] == [b["product"]["id"]]
    detail = client.get(f"{STAFF}/products/{a['product']['id']}", headers=h).json()
    assert detail["store_id"] == a["store_id"]
    path = f"{STAFF}/products/{a['product']['id']}"
    for body in ({"name": "Moderated Sofa"}, {"status": "hidden"}, {"status": "archived"}):
        res = client.patch(path, json=body, headers=h)
        assert res.status_code == 200, res.text
    featured = client.patch(
        f"{STAFF}/products/{b['product']['id']}", json={"is_featured": True}, headers=h
    )
    assert featured.status_code == 200 and featured.json()["is_featured"] is True
    stock = client.get("/api/v1/inventory", headers=h).json()  # the staff stock list
    assert {row["sku"] for row in stock["items"]} == {"OAK-1", "TEAK-1"}

    refused = client.post(
        f"{STAFF}/products",
        json={"name": "Staff Chair", "category_id": market["category_id"]},
        headers=h,
    )
    assert refused.status_code == 409 and code(refused) == "staff_product_creation_disabled"
    assert db.scalar(select(func.count(Product.id))) == 2
    product = db.get(Product, uuid.UUID(a["product"]["id"]))
    assert (product.name, product.status, str(product.store_id)) == (
        "Moderated Sofa",
        "archived",
        a["store_id"],
    )


# ---- the public catalogue: approved stores only ----------------------------------------------
def test_only_approved_stores_products_are_public_and_name_their_store(client, db, market):
    a, b = market["a"], market["b"]
    for seller in (a, b):
        force_status(seller["product"]["id"])  # active without images (the guard's own tests)
    listing = client.get(f"{PUBLIC}/products").json()
    assert {item["store"]["slug"] for item in listing["items"]} == {
        a["store_slug"],
        b["store_slug"],
    }
    detail = client.get(f"{PUBLIC}/products/{a['product']['slug']}").json()
    assert detail["store"] == {"id": a["store_id"], "name": "Oak Store", "slug": a["store_slug"]}
    only_a = client.get(f"{PUBLIC}/products", params={"store": a["store_slug"]}).json()
    assert [item["id"] for item in only_a["items"]] == [a["product"]["id"]]
    assert client.get(f"{PUBLIC}/products", params={"store": "nope"}).json()["total"] == 0

    stores = client.get(STORES).json()
    assert [(s["slug"], s["product_count"]) for s in stores["items"]] == [
        (a["store_slug"], 1),
        (b["store_slug"], 1),
    ]
    assert set(stores["items"][0]) == {
        "id",
        "name",
        "slug",
        "description",
        "district",
        "logo",
        "cover",
        "product_count",
        "approved_at",
    }  # no contact details, address, owner, history or commission

    # Suspending a store hides its products everywhere and makes them unsellable at once.
    decide(
        client,
        {"headers": market["admin"]},
        a["store_id"],
        "suspended",
        "Paused for a stock review.",
    )
    listing = client.get(f"{PUBLIC}/products").json()
    assert [item["id"] for item in listing["items"]] == [b["product"]["id"]]
    assert client.get(f"{PUBLIC}/products/{a['product']['slug']}").status_code == 404
    assert client.get(f"{STORES}/{a['store_slug']}").status_code == 404
    assert [s["slug"] for s in client.get(STORES).json()["items"]] == [b["store_slug"]]
    cart = client.post("/api/v1/cart/items", json={"variant_id": a["variant"]["id"], "quantity": 1})
    assert cart.status_code in (404, 409, 422), cart.text
    assert client.get(f"{STORES}/{b['store_slug']}").json()["product_count"] == 1


def test_pending_and_rejected_stores_are_never_public(client, db, admin_auth, customer_auth):
    res = client.post(
        f"{SELLER}/application",
        json={
            "name": "Pending Store",
            "contact_email": "pending@example.com",
            "contact_phone": "0788 100 009",
            "district": "Gasabo",
        },
        headers=customer_auth["headers"],
    )
    assert res.status_code == 201, res.text
    slug = res.json()["slug"]
    assert client.get(f"{STORES}/{slug}").status_code == 404
    assert client.get(STORES).json()["total"] == 0
    decide(client, admin_auth, res.json()["id"], "rejected", "Incomplete.")
    assert client.get(f"{STORES}/{slug}").status_code == 404
    assert db.scalar(select(func.count(Store.id))) == 1


# ---- the store's logo and cover --------------------------------------------------------------
def test_a_seller_uploads_and_removes_their_own_logo_and_cover(client, db, market, storage):  # noqa: F811
    a = market["a"]
    for field in ("logo", "cover"):
        res = client.post(
            f"{SELLER}/store/{field}",
            files={
                "file": (
                    f"{field}.png",
                    image_bytes(size=(600, 600), image_format="PNG"),
                    "image/png",
                )
            },
            headers=a["headers"],
        )
        assert res.status_code == 200, res.text
        assert res.json()[field]["url"]
    public = client.get(f"{STORES}/{a['store_slug']}").json()
    assert public["logo"] is not None and public["cover"] is not None
    other = client.get(f"{STORES}/{market['b']['store_slug']}").json()
    assert other["logo"] is None and other["cover"] is None
    removed = client.delete(f"{SELLER}/store/logo", headers=a["headers"])
    assert removed.status_code == 200 and removed.json()["logo"] is None
    again = client.delete(f"{SELLER}/store/logo", headers=a["headers"])
    assert again.status_code == 200
    image_actions = ("store.logo_upload", "store.cover_upload", "store.logo_delete")
    actions = list(
        db.scalars(
            select(AuditRecord.action)
            .where(
                AuditRecord.action.in_(image_actions),
                AuditRecord.entity_id == a["store_id"],
            )
            .order_by(AuditRecord.created_at)
        )
    )
    assert actions == ["store.logo_upload", "store.cover_upload", "store.logo_delete"]
