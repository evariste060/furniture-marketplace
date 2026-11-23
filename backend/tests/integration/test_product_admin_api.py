"""Module 6 — products and variants (PR-03, PR-10; TC-04 variants, TC-16 staff roles).

Staff management needs 'catalog:manage' (administrator, sales). Public product responses show a
stock band (stock_status), never the exact available quantity.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import InventoryBalance, Product, ProductVariant
from app.models.common import MAX_MONEY_RWF
from app.models.operations import AuditRecord
from app.repositories.audit_repository import AuditRepository
from app.services import inventory as inv
from tests.support.catalog import force_status
from tests.support.commerce import new_order, soon
from tests.support.sellers import default_seller, post_product

# SC-06: the staff routes for orders, payments, stock and catalogue editing used here are held by
# no role in V1; these tests grant them to the administrator (tests/conftest.py).
pytestmark = pytest.mark.usefixtures("store_operations_granted")

STAFF = "/api/v1/staff"
PUBLIC = "/api/v1/catalog"


def error_code(res) -> str:
    return res.json()["error"]["code"]


def audits(db: Session, action: str, entity_id) -> list[AuditRecord]:
    db.expire_all()
    return list(
        db.scalars(
            select(AuditRecord).where(
                AuditRecord.action == action, AuditRecord.entity_id == str(entity_id)
            )
        )
    )


@pytest.fixture
def catalogue(client: TestClient, admin_auth: dict) -> dict:
    h = admin_auth["headers"]
    category = client.post(f"{STAFF}/categories", json={"name": "Phones"}, headers=h).json()
    # A brand belongs to at least one main category (ADR-012 decision 9).
    brand = client.post(
        f"{STAFF}/brands", json={"name": "Acme", "category_ids": [category["id"]]}, headers=h
    ).json()
    return {"headers": h, "category_id": category["id"], "brand_id": brand["id"]}


def create_product(client, catalogue, name="Galaxy S24", **fields):
    body = {"name": name, "category_id": catalogue["category_id"], **fields}
    res = post_product(client, json=body, headers=catalogue["headers"])
    assert res.status_code == 201, res.text
    return res.json()


def create_variant(client, catalogue, product_id, sku=None, **fields):
    body = {"sku": sku or f"SKU-{uuid.uuid4().hex[:8]}", "name": "Black 128GB", "price": 1000}
    res = client.post(
        f"{STAFF}/products/{product_id}/variants",
        json={**body, **fields},
        headers=catalogue["headers"],
    )
    assert res.status_code == 201, res.text
    return res.json()


def set_stock(db: Session, variant_id, on_hand: int) -> None:
    db.add(InventoryBalance(variant_id=uuid.UUID(str(variant_id)), on_hand=on_hand))
    db.commit()


def publish(client, catalogue, product_id) -> None:
    # Activation through the API needs an image (publication guard, tested in
    # test_publication_guard_api.py); these tests are about visibility and stock.
    force_status(product_id)


def public_slugs(client) -> list[str]:
    return [p["slug"] for p in client.get(f"{PUBLIC}/products").json()["items"]]


def quantity_keys(value, path="") -> list[str]:
    """Every key, at any depth, that could carry an exact stock quantity."""
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if "quantity" in key or "available" in key or "on_hand" in key:
                found.append(f"{path}.{key}")
            found += quantity_keys(item, f"{path}.{key}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            found += quantity_keys(item, f"{path}[{i}]")
    return found


# ---- products: create, slugs, references -------------------------------------------------
def test_product_is_created_as_draft_with_a_generated_slug(client, catalogue, db):
    product = create_product(
        client,
        catalogue,
        brand_id=catalogue["brand_id"],
        model="SM-S921",
        description="Flagship phone",
        specifications={"screen": "6.2 in", "ram_gb": 8},
        warranty_text="One year",
    )
    assert product["slug"] == "galaxy-s24" and product["status"] == "draft"
    assert product["brand_id"] == catalogue["brand_id"] and product["variants"] == []
    assert product["specifications"] == {"screen": "6.2 in", "ram_gb": 8}
    (record,) = audits(db, "catalog.product_create", product["id"])
    seller = default_seller(client, catalogue["headers"])  # sellers create (ADR-014 phase 2)
    assert str(record.actor_user_id) == seller["user"]["id"]
    assert record.change_summary["slug"] == "galaxy-s24"
    assert record.change_summary["store_id"] == seller["store_id"]
    assert "galaxy-s24" not in public_slugs(client)  # drafts are not public


def test_product_slugs_get_numeric_suffixes_and_explicit_slugs_must_be_free(client, catalogue):
    assert create_product(client, catalogue, "Galaxy S24")["slug"] == "galaxy-s24"
    assert create_product(client, catalogue, "galaxy  s24!")["slug"] == "galaxy-s24-2"
    assert create_product(client, catalogue, "Écran Pro")["slug"] == "ecran-pro"
    assert create_product(client, catalogue, "Custom", slug="my-phone")["slug"] == "my-phone"
    taken = post_product(
        client,
        json={"name": "X", "slug": "galaxy-s24", "category_id": catalogue["category_id"]},
        headers=catalogue["headers"],
    )
    assert taken.status_code == 409 and error_code(taken) == "slug_taken"
    nameless = post_product(
        client,
        json={"name": "!!!", "category_id": catalogue["category_id"]},
        headers=catalogue["headers"],
    )
    assert nameless.status_code == 422
    assert nameless.json()["error"]["details"][0]["loc"] == ["body", "name"]


def test_rename_keeps_the_slug_and_slugs_can_be_edited(client, catalogue):
    h = catalogue["headers"]
    product = create_product(client, catalogue, "Pixel 9")
    other = create_product(client, catalogue, "Pixel 9 Pro")
    renamed = client.patch(
        f"{STAFF}/products/{product['id']}", json={"name": "Pixel 9a"}, headers=h
    )
    assert renamed.json()["slug"] == "pixel-9" and renamed.json()["name"] == "Pixel 9a"
    edited = client.patch(f"{STAFF}/products/{product['id']}", json={"slug": "pixel-9a"}, headers=h)
    assert edited.status_code == 200 and edited.json()["slug"] == "pixel-9a"
    clash = client.patch(f"{STAFF}/products/{other['id']}", json={"slug": "pixel-9a"}, headers=h)
    assert clash.status_code == 409 and error_code(clash) == "slug_taken"


def test_category_and_brand_must_exist_and_brand_can_be_cleared(client, catalogue):
    h = catalogue["headers"]
    missing_category = post_product(
        client, json={"name": "X", "category_id": str(uuid.uuid4())}, headers=h
    )
    assert missing_category.status_code == 422
    assert missing_category.json()["error"]["details"][0]["loc"] == ["body", "category_id"]
    product = create_product(client, catalogue, brand_id=catalogue["brand_id"])
    missing_brand = client.patch(
        f"{STAFF}/products/{product['id']}", json={"brand_id": str(uuid.uuid4())}, headers=h
    )
    assert missing_brand.status_code == 422
    assert missing_brand.json()["error"]["details"][0]["loc"] == ["body", "brand_id"]
    cleared = client.patch(f"{STAFF}/products/{product['id']}", json={"brand_id": None}, headers=h)
    assert cleared.status_code == 200 and cleared.json()["brand_id"] is None
    unknown = client.patch(f"{STAFF}/products/{uuid.uuid4()}", json={"name": "X"}, headers=h)
    assert unknown.status_code == 404 and error_code(unknown) == "product_not_found"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": None},
        {"status": None},
        {"status": "deleted"},
        {"category_id": None},
        {"specifications": None},
        {"specifications": ["not", "an", "object"]},
        {"slug": "Bad Slug"},
        {"name": "x" * 241},
        {"id": str(uuid.uuid4())},
    ],
)
def test_invalid_product_updates_are_rejected(client, catalogue, body):
    product = create_product(client, catalogue)
    res = client.patch(f"{STAFF}/products/{product['id']}", json=body, headers=catalogue["headers"])
    assert res.status_code == 422 and error_code(res) == "validation_error"


def test_product_updates_are_audited_and_no_ops_are_not(client, catalogue, db):
    h = catalogue["headers"]
    product = create_product(client, catalogue)
    client.patch(f"{STAFF}/products/{product['id']}", json={"status": "draft"}, headers=h)
    assert audits(db, "catalog.product_update", product["id"]) == []
    client.patch(
        f"{STAFF}/products/{product['id']}",
        json={"status": "hidden", "description": "A long marketing text"},
        headers=h,
    )
    (record,) = audits(db, "catalog.product_update", product["id"])
    assert record.change_summary["changes"] == {
        "status": {"from": "draft", "to": "hidden"},
        "description": {"changed": True},  # long text is not copied into the audit trail
    }


# ---- public visibility -------------------------------------------------------------------
@pytest.mark.parametrize("hidden_status", ["draft", "hidden", "archived"])
def test_only_active_products_are_public(client, catalogue, hidden_status):
    product = create_product(client, catalogue, brand_id=catalogue["brand_id"])
    create_variant(client, catalogue, product["id"])
    publish(client, catalogue, product["id"])
    assert public_slugs(client) == ["galaxy-s24"]
    assert client.get(f"{PUBLIC}/products/galaxy-s24").status_code == 200

    client.patch(
        f"{STAFF}/products/{product['id']}",
        json={"status": hidden_status},
        headers=catalogue["headers"],
    )
    assert public_slugs(client) == []
    assert client.get(f"{PUBLIC}/products/galaxy-s24").status_code == 404


@pytest.mark.parametrize("deactivate", ["category", "brand"])
def test_inactive_category_or_brand_hides_active_products(client, catalogue, deactivate):
    h = catalogue["headers"]
    product = create_product(client, catalogue, brand_id=catalogue["brand_id"])
    publish(client, catalogue, product["id"])
    target = (
        f"{STAFF}/categories/{catalogue['category_id']}"
        if deactivate == "category"
        else f"{STAFF}/brands/{catalogue['brand_id']}"
    )
    assert client.patch(target, json={"is_active": False}, headers=h).status_code == 200
    assert public_slugs(client) == []
    assert client.get(f"{PUBLIC}/products/galaxy-s24").status_code == 404
    client.patch(target, json={"is_active": True}, headers=h)
    assert public_slugs(client) == ["galaxy-s24"]


def test_active_product_without_a_brand_is_public(client, catalogue):
    product = create_product(client, catalogue, "Unbranded Cable")
    publish(client, catalogue, product["id"])
    assert public_slugs(client) == ["unbranded-cable"]


# ---- variants ------------------------------------------------------------------------------
def test_variant_create_update_and_unique_sku(client, catalogue, db):
    h = catalogue["headers"]
    product = create_product(client, catalogue)
    variant = create_variant(
        client,
        catalogue,
        product["id"],
        sku="GS24-BLK-128",
        attributes={"colour": "black", "storage_gb": 128},
        compare_at_price=1500,
        low_stock_threshold=3,
    )
    assert variant["product_id"] == product["id"] and variant["currency_code"] == "RWF"
    assert (variant["price"], variant["compare_at_price"], variant["is_active"]) == (
        1000,
        1500,
        True,
    )
    (created,) = audits(db, "catalog.variant_create", variant["id"])
    assert created.change_summary["sku"] == "GS24-BLK-128"

    other = create_product(client, catalogue, "Other")
    dup = client.post(
        f"{STAFF}/products/{other['id']}/variants",
        json={"sku": "GS24-BLK-128", "name": "X", "price": 1},
        headers=h,
    )
    assert dup.status_code == 409 and error_code(dup) == "sku_taken"

    path = f"{STAFF}/products/{product['id']}/variants/{variant['id']}"
    updated = client.patch(path, json={"name": "Black 256GB", "compare_at_price": None}, headers=h)
    assert updated.status_code == 200
    assert updated.json()["name"] == "Black 256GB" and updated.json()["compare_at_price"] is None
    listed = client.patch(f"{STAFF}/products/{product['id']}", json={"model": "SM"}, headers=h)
    assert [v["sku"] for v in listed.json()["variants"]] == ["GS24-BLK-128"]


def test_price_changes_are_audited_with_old_and_new_values(client, catalogue, db, admin_auth):
    product = create_product(client, catalogue)
    variant = create_variant(client, catalogue, product["id"], price=1000, compare_at_price=1200)
    res = client.patch(
        f"{STAFF}/products/{product['id']}/variants/{variant['id']}",
        json={"price": 950, "compare_at_price": 1300},
        headers=admin_auth["headers"],
    )
    assert res.status_code == 200 and res.json()["price"] == 950
    (record,) = audits(db, "catalog.variant_update", variant["id"])
    assert record.actor_user_id == admin_auth["user"].id
    assert record.change_summary["changes"] == {
        "price": {"from": 1000, "to": 950},
        "compare_at_price": {"from": 1200, "to": 1300},
    }
    assert record.change_summary["product_id"] == product["id"]


def test_variant_delete_deactivates_and_never_removes_the_row(client, catalogue, db):
    h = catalogue["headers"]
    product = create_product(client, catalogue)
    keep = create_variant(client, catalogue, product["id"], sku="KEEP-1", name="A")
    gone = create_variant(client, catalogue, product["id"], sku="GONE-1", name="B")
    # A placed order references the variant through its stock reservation.
    set_stock(db, gone["id"], 2)
    publish(client, catalogue, product["id"])
    with Session(db.get_bind()) as s:
        inv.create_order_with_reservations(
            s, new_order({uuid.UUID(gone["id"]): 1}), expires_at=soon()
        )

    path = f"{STAFF}/products/{product['id']}/variants/{gone['id']}"
    res = client.delete(path, headers=h)
    assert res.status_code == 204 and res.content == b""
    db.expire_all()
    stored = db.get(ProductVariant, uuid.UUID(gone["id"]))
    assert stored is not None and stored.is_active is False
    detail = client.get(f"{PUBLIC}/products/galaxy-s24").json()
    assert [v["sku"] for v in detail["variants"]] == ["KEEP-1"]
    (record,) = audits(db, "catalog.variant_deactivate", gone["id"])
    assert record.change_summary["sku"] == "GONE-1"

    assert client.delete(path, headers=h).status_code == 204  # repeat: no-op
    assert len(audits(db, "catalog.variant_deactivate", gone["id"])) == 1
    reactivated = client.patch(path, json={"is_active": True}, headers=h)
    assert reactivated.status_code == 200 and reactivated.json()["is_active"] is True
    assert keep["is_active"] is True


def test_variant_must_belong_to_the_product_in_the_path(client, catalogue):
    h = catalogue["headers"]
    product = create_product(client, catalogue)
    other = create_product(client, catalogue, "Other")
    variant = create_variant(client, catalogue, product["id"])
    wrong = client.delete(f"{STAFF}/products/{other['id']}/variants/{variant['id']}", headers=h)
    assert wrong.status_code == 404 and error_code(wrong) == "variant_not_found"
    missing = client.post(
        f"{STAFF}/products/{uuid.uuid4()}/variants",
        json={"sku": "X1", "name": "X", "price": 1},
        headers=h,
    )
    assert missing.status_code == 404 and error_code(missing) == "product_not_found"


@pytest.mark.parametrize(
    "body",
    [
        {"price": -1},
        {"price": MAX_MONEY_RWF + 1},
        {"price": 10.5},
        {"compare_at_price": -5},
        {"low_stock_threshold": -1},
        {"sku": "HAS SPACE"},
        {"sku": "has/slash"},
        {"sku": ""},
        {"currency_code": "USD"},
        {"available_quantity": 10},
    ],
)
def test_invalid_variants_are_rejected(client, catalogue, body):
    product = create_product(client, catalogue)
    base = {"sku": "OK-1", "name": "Black", "price": 1000}
    res = client.post(
        f"{STAFF}/products/{product['id']}/variants",
        json={**base, **body},
        headers=catalogue["headers"],
    )
    assert res.status_code == 422 and error_code(res) == "validation_error"


def test_audit_failure_rolls_back_a_price_change(client, catalogue, db, monkeypatch):
    product = create_product(client, catalogue)
    variant = create_variant(client, catalogue, product["id"], price=1000)

    def fail(*args, **kwargs):
        raise RuntimeError("simulated audit persistence failure")

    monkeypatch.setattr(AuditRepository, "create", staticmethod(fail))
    with pytest.raises(RuntimeError):
        client.patch(
            f"{STAFF}/products/{product['id']}/variants/{variant['id']}",
            json={"price": 1},
            headers=catalogue["headers"],
        )
    db.expire_all()
    stored = db.get(ProductVariant, uuid.UUID(variant["id"]))
    assert stored is not None and stored.price == 1000


# ---- public stock status -------------------------------------------------------------------
@pytest.mark.parametrize(
    ("threshold", "on_hand", "status"),
    [
        (0, 1, "in_stock"),  # threshold 0 never reports low stock
        (0, 0, "out_of_stock"),
        (3, 4, "in_stock"),
        (3, 3, "low_stock"),  # equal to the threshold
        (3, 1, "low_stock"),
        (3, 0, "out_of_stock"),
        (5, None, "out_of_stock"),  # no inventory record
    ],
)
def test_stock_status_boundaries(client, catalogue, db, threshold, on_hand, status):
    product = create_product(client, catalogue)
    variant = create_variant(client, catalogue, product["id"], low_stock_threshold=threshold)
    if on_hand is not None:
        set_stock(db, variant["id"], on_hand)
    publish(client, catalogue, product["id"])
    detail = client.get(f"{PUBLIC}/products/galaxy-s24").json()
    listed = client.get(f"{PUBLIC}/products").json()["items"][0]
    for public in (detail, listed):
        (shown,) = public["variants"]
        assert shown["stock_status"] == status
        assert shown["in_stock"] is (status != "out_of_stock")


def test_reservations_count_against_the_stock_band(client, catalogue, db):
    product = create_product(client, catalogue)
    variant = create_variant(client, catalogue, product["id"], low_stock_threshold=3)
    set_stock(db, variant["id"], 4)
    publish(client, catalogue, product["id"])
    assert client.get(f"{PUBLIC}/products/galaxy-s24").json()["variants"][0]["stock_status"] == (
        "in_stock"
    )
    with Session(db.get_bind()) as s:
        inv.create_order_with_reservations(
            s, new_order({uuid.UUID(variant["id"]): 1}), expires_at=soon()
        )
    assert client.get(f"{PUBLIC}/products/galaxy-s24").json()["variants"][0]["stock_status"] == (
        "low_stock"
    )


def test_public_responses_never_contain_exact_quantities(client, catalogue, db):
    product = create_product(client, catalogue, brand_id=catalogue["brand_id"])
    variant = create_variant(client, catalogue, product["id"], low_stock_threshold=2)
    set_stock(db, variant["id"], 7)
    publish(client, catalogue, product["id"])
    listing = client.get(f"{PUBLIC}/products").json()
    detail = client.get(f"{PUBLIC}/products/galaxy-s24").json()
    assert listing["total"] == 1
    assert quantity_keys(listing) == [] and quantity_keys(detail) == []
    assert set(detail["variants"][0]) == {
        "id",
        "sku",
        "name",
        "attributes",
        "price",
        "compare_at_price",
        "currency_code",
        "stock_status",
        "in_stock",
        "images",
    }


# ---- authorization -------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["customer_auth"])
def test_other_roles_are_forbidden_and_nothing_changes(client, catalogue, db, who, request):
    product = create_product(client, catalogue)
    variant = create_variant(client, catalogue, product["id"], price=1000)
    h = request.getfixturevalue(who)["headers"]
    base = f"{STAFF}/products/{product['id']}"
    attempts = [
        client.post(
            f"{STAFF}/products",
            json={"name": "N", "category_id": catalogue["category_id"]},
            headers=h,
        ),
        client.patch(base, json={"status": "active"}, headers=h),
        client.post(f"{base}/variants", json={"sku": "N-1", "name": "N", "price": 1}, headers=h),
        client.patch(f"{base}/variants/{variant['id']}", json={"price": 1}, headers=h),
        client.delete(f"{base}/variants/{variant['id']}", headers=h),
    ]
    assert [r.status_code for r in attempts] == [403] * 5
    assert {error_code(r) for r in attempts} == {"permission_denied"}
    db.expire_all()
    assert db.scalar(select(func.count(Product.id))) == 1
    stored = db.get(ProductVariant, uuid.UUID(variant["id"]))
    assert stored is not None and (stored.price, stored.is_active) == (1000, True)
    assert db.get(Product, uuid.UUID(product["id"])).status == "draft"


def test_administrators_cannot_create_products(client, catalogue, db):
    # SC-05: moderation only. A valid body is refused with an explanation; nothing is stored or
    # audited, and the administrator can still edit the seller's products (tests above).
    res = client.post(
        f"{STAFF}/products",
        json={"name": "Staff Sofa", "category_id": catalogue["category_id"]},
        headers=catalogue["headers"],
    )
    assert res.status_code == 409 and error_code(res) == "staff_product_creation_disabled"
    assert "sellers add their own products" in res.json()["error"]["message"]
    assert db.scalar(select(func.count(Product.id))) == 0
    assert not db.scalars(
        select(AuditRecord).where(AuditRecord.action == "catalog.product_create")
    ).all()


def test_anonymous_requests_are_unauthorized(client):
    res = client.post(f"{STAFF}/products", json={"name": "Anon"})
    assert res.status_code == 401 and error_code(res) == "token_missing"
    product_id, variant_id = uuid.uuid4(), uuid.uuid4()
    assert client.delete(f"{STAFF}/products/{product_id}/variants/{variant_id}").status_code == 401
