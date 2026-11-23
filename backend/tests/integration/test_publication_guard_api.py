"""The publication guard, bulk activate, SKU rules and unique image positions (approved
2026-10-26, checkpoint 1b topics 5 and 6).

Every path that activates a product or removes a product image calls
app.services.product_admin.ensure_publishable: product create and update, the catalogue import,
image delete, moving an image to a variant, bulk image replace and bulk activate.
"""

import io
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditRecord, Product
from app.services import product_admin
from tests.support.media import image_row
from tests.support.sellers import new_store, post_product

# SC-06: the staff routes for orders, payments, stock and catalogue editing used here are held by
# no role in V1; these tests grant them to the administrator (tests/conftest.py).
pytestmark = pytest.mark.usefixtures("store_operations_granted")

STAFF = "/api/v1/staff"


@pytest.fixture
def category(client: TestClient, admin_auth: dict) -> dict:
    res = client.post(f"{STAFF}/categories", json={"name": "Phones"}, headers=admin_auth["headers"])
    return res.json()


def draft(client, headers, category_id: str, name: str, sku: str | None = None) -> dict:
    res = post_product(client, json={"name": name, "category_id": category_id}, headers=headers)
    assert res.status_code == 201, res.text
    product = res.json()
    if sku:
        variant = client.post(
            f"{STAFF}/products/{product['id']}/variants",
            json={"sku": sku, "name": "Std", "price": 1000},
            headers=headers,
        )
        assert variant.status_code == 201, variant.text
        product["variant_id"] = variant.json()["id"]
    return product


def add_image(db: Session, product_id: str, sort_order: int = 0, variant_id=None):
    image = image_row(
        uuid.UUID(product_id),
        sort_order,
        variant_id=uuid.UUID(variant_id) if variant_id else None,
    )
    db.add(image)
    db.commit()
    return image


def status_of(db: Session, product_id: str) -> str:
    db.expire_all()
    product = db.get(Product, uuid.UUID(product_id))
    assert product is not None
    return product.status


# ---- the guard on every path ---------------------------------------------------------------
def test_a_new_product_cannot_be_created_active(client, admin_auth, category):
    res = post_product(
        client,
        json={"name": "Spark", "category_id": category["id"], "status": "active"},
        headers=admin_auth["headers"],
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "product_has_no_images"


def test_activation_needs_a_product_image_and_variant_images_do_not_count(
    client, db, admin_auth, category
):
    h = admin_auth["headers"]
    product = draft(client, h, category["id"], "Spark", sku="SP-1")
    path = f"{STAFF}/products/{product['id']}"
    for current in ("draft", "hidden", "archived"):
        client.patch(path, json={"status": current}, headers=h)
        refused = client.patch(path, json={"status": "active"}, headers=h)
        assert refused.status_code == 409, current
        assert refused.json()["error"]["code"] == "product_has_no_images"
    add_image(db, product["id"], 0, variant_id=product["variant_id"])  # a variant image
    assert client.patch(path, json={"status": "active"}, headers=h).status_code == 409
    add_image(db, product["id"], 1)
    activated = client.patch(path, json={"status": "active"}, headers=h)
    assert activated.status_code == 200 and activated.json()["status"] == "active"


def test_the_last_product_image_of_an_active_product_cannot_be_removed(
    client, db, admin_auth, category
):
    h = admin_auth["headers"]
    product = draft(client, h, category["id"], "Spark", sku="SP-2")
    first = add_image(db, product["id"], 0)
    second = add_image(db, product["id"], 1)
    client.patch(f"{STAFF}/products/{product['id']}", json={"status": "active"}, headers=h)

    assert client.delete(f"{STAFF}/images/{first.id}", headers=h).status_code == 204
    last = client.delete(f"{STAFF}/images/{second.id}", headers=h)
    assert last.status_code == 409 and last.json()["error"]["code"] == "last_product_image"
    assert last.json()["error"]["message"] == (
        "Upload a replacement or deactivate the product first."
    )
    moved = client.patch(
        f"{STAFF}/images/{second.id}", json={"variant_id": product["variant_id"]}, headers=h
    )
    assert moved.status_code == 409 and moved.json()["error"]["code"] == "last_product_image"

    client.patch(f"{STAFF}/products/{product['id']}", json={"status": "draft"}, headers=h)
    assert client.delete(f"{STAFF}/images/{second.id}", headers=h).status_code == 204


def test_products_already_active_without_images_are_not_deactivated(
    client, db, admin_auth, category
):
    legacy = Product(
        store=new_store(), name="Legacy", slug="legacy", category_id=uuid.UUID(category["id"])
    )
    legacy.status = "active"
    db.add(legacy)
    db.commit()
    h = admin_auth["headers"]
    res = client.patch(f"{STAFF}/products/{legacy.id}", json={"model": "L1"}, headers=h)
    assert res.status_code == 200 and res.json()["status"] == "active"
    listed = client.get(
        f"{STAFF}/products", params={"status": "active", "has_images": "false"}, headers=h
    ).json()
    assert [p["slug"] for p in listed["items"]] == ["legacy"]


def test_every_activation_and_image_removal_path_uses_the_single_guard(
    client, db, admin_auth, category, monkeypatch
):
    calls: list[tuple] = []
    real = product_admin.ensure_publishable

    def spy(db, product_id, **kwargs):
        calls.append((product_id, kwargs.get("excluding_image_id")))
        return real(db, product_id, **kwargs)

    for module in (
        "app.services.product_admin",
        "app.services.image_admin",
        "app.services.bulk_images",
    ):
        monkeypatch.setattr(f"{module}.ensure_publishable", spy)
    h = admin_auth["headers"]
    post_product(
        client,
        json={"name": "New", "category_id": category["id"], "status": "active"},
        headers=h,
    )
    product = draft(client, h, category["id"], "Spark", sku="SP-3")
    image = add_image(db, product["id"], 0)
    client.patch(f"{STAFF}/products/{product['id']}", json={"status": "active"}, headers=h)
    client.delete(f"{STAFF}/images/{image.id}", headers=h)
    client.patch(
        f"{STAFF}/images/{image.id}", json={"variant_id": product["variant_id"]}, headers=h
    )
    pid = uuid.UUID(product["id"])
    assert calls == [(None, None), (pid, None), (pid, image.id), (pid, image.id)]


# ---- bulk activate -------------------------------------------------------------------------
def test_bulk_activate_reports_each_product(client, db, admin_auth, category):
    h = admin_auth["headers"]
    ready = draft(client, h, category["id"], "Ready")
    bare = draft(client, h, category["id"], "Bare")
    live = draft(client, h, category["id"], "Live")
    add_image(db, ready["id"])
    add_image(db, live["id"])
    client.patch(f"{STAFF}/products/{live['id']}", json={"status": "active"}, headers=h)
    missing = str(uuid.uuid4())

    listed = client.get(
        f"{STAFF}/products", params={"status": "draft", "has_images": "true"}, headers=h
    ).json()
    assert [p["slug"] for p in listed["items"]] == ["ready"]

    res = client.post(
        f"{STAFF}/products/bulk-activate",
        json={"product_ids": [ready["id"], bare["id"], live["id"], missing]},
        headers=h,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert [r["outcome"] for r in body["results"]] == [
        "activated",
        "skipped_no_images",
        "already_active",
        "not_found",
    ]
    assert (body["activated"], body["skipped_no_images"]) == (1, 1)
    assert (body["already_active"], body["not_found"]) == (1, 1)
    assert status_of(db, ready["id"]) == "active" and status_of(db, bare["id"]) == "draft"
    db.expire_all()
    audits = db.scalars(
        select(AuditRecord).where(
            AuditRecord.action == "catalog.product_update",
            AuditRecord.entity_id == ready["id"],
        )
    ).all()
    assert [a.change_summary["changes"]["status"] for a in audits] == [
        {"from": "draft", "to": "active"}
    ]


@pytest.mark.parametrize(
    "ids",
    [[], [str(uuid.uuid4())] * 2, [str(uuid.uuid4()) for _ in range(201)]],
    ids=["empty", "repeated", "201"],
)
def test_bulk_activate_validates_its_input(client, admin_auth, ids):
    res = client.post(
        f"{STAFF}/products/bulk-activate", json={"product_ids": ids}, headers=admin_auth["headers"]
    )
    assert res.status_code == 422


@pytest.mark.parametrize("who", ["customer_auth"])
def test_bulk_activate_needs_catalog_manage(client, request, who):
    headers = request.getfixturevalue(who)["headers"]
    res = client.post(
        f"{STAFF}/products/bulk-activate",
        json={"product_ids": [str(uuid.uuid4())]},
        headers=headers,
    )
    assert res.status_code == 403


# ---- the import ----------------------------------------------------------------------------
def test_an_import_row_asking_for_active_without_images_saves_a_draft_with_a_warning(
    client, db, admin_auth, category
):
    h = admin_auth["headers"]
    # SC-05: imports update existing products only; a seller added this one as a draft.
    made = post_product(
        client,
        json={"name": "Imported Phone", "slug": "imported-phone", "category_id": category["id"]},
        headers=h,
    )
    assert made.status_code == 201, made.text
    rows = (
        "sku,product_slug,product_name,category_slug,variant_name,price,product_status\n"
        "IMP-1,imported-phone,Imported Phone,phones,Std,1000,active\n"
    )
    res = client.post(
        f"{STAFF}/imports",
        files={"file": ("rows.csv", io.BytesIO(rows.encode()), "text/csv")},
        headers=h,
    )
    assert res.status_code in (200, 201), res.text
    job = res.json()
    assert job["status"] == "completed" and job["imported_rows"] == 1
    assert job["warnings"] == [
        {
            "row": 2,
            "field": "product_status",
            # The existing-product wording (SC-05: imports no longer create products).
            "message": "The product has no images, so it was saved as draft instead of "
            "active. Upload images (bulk upload), then activate it.",
        }
    ]
    product = db.scalar(select(Product).where(Product.slug == "imported-phone"))
    assert product is not None and product.status == "draft"


# ---- SKUs ----------------------------------------------------------------------------------
def test_skus_are_unique_ignoring_case_and_may_not_contain_a_double_underscore(
    client, admin_auth, category
):
    h = admin_auth["headers"]
    product = draft(client, h, category["id"], "Spark", sku="SPARK-128")
    path = f"{STAFF}/products/{product['id']}/variants"
    taken = client.post(path, json={"sku": "spark-128", "name": "B", "price": 1}, headers=h)
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "sku_taken"
    double = client.post(path, json={"sku": "SPARK__2", "name": "C", "price": 1}, headers=h)
    assert double.status_code == 422
    assert "'__'" in double.json()["error"]["details"][0]["msg"]
    stock = client.get("/api/v1/inventory/spark-128", headers=h)  # any case finds the SKU
    assert stock.status_code == 200 and stock.json()["sku"] == "SPARK-128"


# ---- positions -----------------------------------------------------------------------------
def test_two_product_images_cannot_share_a_position(client, db, admin_auth, category):
    h = admin_auth["headers"]
    product = draft(client, h, category["id"], "Spark", sku="SP-4")
    add_image(db, product["id"], 0)
    second = add_image(db, product["id"], 1)
    variant_image = add_image(db, product["id"], 0, variant_id=product["variant_id"])
    taken = client.patch(f"{STAFF}/images/{second.id}", json={"sort_order": 0}, headers=h)
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "sort_order_taken"
    back = client.patch(f"{STAFF}/images/{variant_image.id}", json={"variant_id": None}, headers=h)
    assert back.status_code == 409  # would become a second product image at position 1


def test_the_staff_views_show_the_bulk_upload_file_names(client, db, admin_auth, category):
    h = admin_auth["headers"]
    product = draft(client, h, category["id"], "Samsung Galaxy A55")
    listed = client.get(f"{STAFF}/products", headers=h).json()["items"][0]
    assert listed["next_photo_file_name"] == "samsung-galaxy-a55.jpg"
    first = add_image(db, product["id"], 0)
    second = add_image(db, product["id"], 1)
    detail = client.get(f"{STAFF}/products/{product['id']}", headers=h).json()
    assert detail["photo_file_names"] == [
        {"image_id": str(first.id), "position": 1, "file_name": "samsung-galaxy-a55.jpg"},
        {"image_id": str(second.id), "position": 2, "file_name": "samsung-galaxy-a55__2.jpg"},
    ]
    assert detail["next_photo_file_name"] == "samsung-galaxy-a55__3.jpg"
