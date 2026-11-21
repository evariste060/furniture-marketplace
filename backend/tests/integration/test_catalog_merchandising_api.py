"""Storefront merchandising (approved 2026-10-25): category descriptions and images, brand logos
(B1), featured products (B2), the bestselling sort (B3) and created_at on catalogue products (B4).

Images use the ADR-009 pipeline shared with product images; files go to a temporary MEDIA_ROOT.
"""

import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.media import KEY_PATTERN, LocalMediaStorage, get_media_storage
from app.main import app
from app.models import Category, MediaObject, OrderStatusHistory, ProductVariant
from app.models.operations import AuditRecord
from app.repositories.audit_repository import AuditRepository
from app.services import media_cleanup
from tests.support.catalog import force_status
from tests.support.commerce import new_order

STAFF = "/api/v1/staff"
PUBLIC = "/api/v1/catalog"


def png(size=(300, 200), colour=(10, 120, 240, 255)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", size, colour).save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture
def storage(tmp_path, monkeypatch):
    media = LocalMediaStorage(tmp_path / "media", get_settings().image_public_base_url)
    app.dependency_overrides[get_media_storage] = lambda: media
    monkeypatch.setattr("app.services.catalog.get_media_storage", lambda: media)
    yield media
    app.dependency_overrides.pop(get_media_storage, None)


def run_cleanup(db: Session, storage) -> None:
    """What the worker does: delete every retired file, then its registry row."""
    media_cleanup.delete_due(db, storage, datetime.now(UTC))


def media_states(db: Session) -> list[str]:
    db.expire_all()
    return sorted(db.scalars(select(MediaObject.state)))


def stored_files(storage: LocalMediaStorage) -> list[str]:
    if not storage.root.exists():
        return []
    return sorted(
        p.relative_to(storage.root).as_posix() for p in storage.root.rglob("*") if p.is_file()
    )


def audits(db: Session, action: str) -> list[AuditRecord]:
    db.expire_all()
    return list(db.scalars(select(AuditRecord).where(AuditRecord.action == action)))


def put_file(client, path: str, headers: dict, data: bytes | None = None):
    return client.post(
        path,
        files={"file": ("x.png", png() if data is None else data, "image/png")},
        headers=headers,
    )


@pytest.fixture
def category(client: TestClient, admin_auth: dict) -> dict:
    res = client.post(
        f"{STAFF}/categories",
        json={"name": "Phones", "description": "  Smartphones & accessories  "},
        headers=admin_auth["headers"],
    )
    assert res.status_code == 201, res.text
    return res.json()


@pytest.fixture
def brand(client: TestClient, admin_auth: dict) -> dict:
    # A brand needs a main category (ADR-012 decision 9): its own, so tests can add "Phones".
    h = admin_auth["headers"]
    home = client.post(f"{STAFF}/categories", json={"name": "Brand home"}, headers=h)
    assert home.status_code == 201, home.text
    body = {"name": "Samsung", "category_ids": [home.json()["id"]]}
    res = client.post(f"{STAFF}/brands", json=body, headers=h)
    assert res.status_code == 201, res.text
    return res.json()


# ---- B1: category description --------------------------------------------------------------
def test_category_description_is_saved_trimmed_public_and_can_be_cleared(
    client, admin_auth, category, storage
):
    h = admin_auth["headers"]
    assert category["description"] == "Smartphones & accessories" and category["image"] is None
    (public,) = client.get(f"{PUBLIC}/categories").json()
    assert public["description"] == "Smartphones & accessories" and public["image"] is None

    too_long = client.patch(
        f"{STAFF}/categories/{category['id']}", json={"description": "x" * 501}, headers=h
    )
    assert too_long.status_code == 422
    cleared = client.patch(
        f"{STAFF}/categories/{category['id']}", json={"description": None}, headers=h
    )
    assert cleared.status_code == 200 and cleared.json()["description"] is None


# ---- B1: category image ----------------------------------------------------------------------
def test_category_image_upload_stores_both_files_and_appears_publicly(
    client, admin_auth, category, storage, db
):
    path = f"{STAFF}/categories/{category['id']}/image"
    raw = png(size=(640, 480))
    res = put_file(client, path, admin_auth["headers"], raw)
    assert res.status_code == 200, res.text
    image = res.json()["image"]
    key = image["url"].removeprefix(get_settings().image_public_base_url + "/")
    assert KEY_PATTERN.fullmatch(key) and key.startswith(f"categories/{category['id']}/")
    assert image == {
        "url": f"{get_settings().image_public_base_url}/{key}",
        "width": 640,
        "height": 480,
        "alt": "Phones",
        "position": 0,
    }
    assert stored_files(storage) == [f"private/{key}", f"public/{key}"]
    assert (storage.private_root / key).read_bytes() == raw
    public_file = Image.open(storage.public_root / key)
    assert public_file.format == "PNG" and public_file.mode == "RGBA"  # transparency kept

    (public,) = client.get(f"{PUBLIC}/categories").json()
    assert public["image"] == image
    (record,) = audits(db, "catalog.category_image_upload")
    assert record.change_summary["image_ref"] == key
    assert record.change_summary["replaced_image_ref"] is None


def test_replacing_a_category_image_creates_a_new_key_and_retires_the_old_files(
    client, admin_auth, category, storage, db
):
    path = f"{STAFF}/categories/{category['id']}/image"
    first = put_file(client, path, admin_auth["headers"]).json()["image"]["url"]
    second = put_file(client, path, admin_auth["headers"]).json()["image"]["url"]
    assert first != second
    # The old files stay reachable until the worker runs after the replacement's commit.
    assert len(stored_files(storage)) == 4
    assert media_states(db) == ["active", "active", "deleting", "deleting"]
    run_cleanup(db, storage)
    key = second.rsplit("/media/", 1)[1]
    assert stored_files(storage) == [f"private/{key}", f"public/{key}"]
    assert media_states(db) == ["active", "active"]


def test_removing_a_category_image_clears_it_and_deletes_the_files(
    client, admin_auth, category, storage, db
):
    path = f"{STAFF}/categories/{category['id']}/image"
    put_file(client, path, admin_auth["headers"])
    res = client.delete(path, headers=admin_auth["headers"])
    assert res.status_code == 200 and res.json()["image"] is None
    assert media_states(db) == ["deleting", "deleting"]
    run_cleanup(db, storage)
    assert stored_files(storage) == [] and media_states(db) == []
    assert len(audits(db, "catalog.category_image_delete")) == 1
    again = client.delete(path, headers=admin_auth["headers"])  # nothing to remove
    assert again.status_code == 200 and len(audits(db, "catalog.category_image_delete")) == 1


def test_deleting_a_category_retires_its_image_files(client, admin_auth, category, storage, db):
    put_file(client, f"{STAFF}/categories/{category['id']}/image", admin_auth["headers"])
    assert len(stored_files(storage)) == 2
    res = client.delete(f"{STAFF}/categories/{category['id']}", headers=admin_auth["headers"])
    assert res.status_code == 204 and media_states(db) == ["deleting", "deleting"]
    run_cleanup(db, storage)
    assert stored_files(storage) == [] and media_states(db) == []


@pytest.mark.parametrize("data", [b"not an image", png()[:60]], ids=["text", "corrupt-png"])
def test_invalid_category_images_are_rejected_and_nothing_changes(
    client, admin_auth, category, storage, db, data
):
    res = put_file(
        client, f"{STAFF}/categories/{category['id']}/image", admin_auth["headers"], data
    )
    assert res.status_code == 422
    assert res.json()["error"]["details"][0]["loc"] == ["body", "file"]
    assert stored_files(storage) == []
    db.expire_all()
    assert db.get(Category, uuid.UUID(category["id"])).image_media_id is None
    assert media_states(db) == []


def test_a_failed_audit_removes_the_new_files_and_keeps_the_old_image(
    client, admin_auth, category, storage, db, monkeypatch
):
    path = f"{STAFF}/categories/{category['id']}/image"
    old = put_file(client, path, admin_auth["headers"]).json()["image"]["url"]
    before = stored_files(storage)

    def fail(*args, **kwargs):
        raise RuntimeError("simulated audit persistence failure")

    monkeypatch.setattr(AuditRepository, "create", staticmethod(fail))
    with pytest.raises(RuntimeError):
        put_file(client, path, admin_auth["headers"])
    assert stored_files(storage) == before  # new files removed, old ones untouched
    assert media_states(db) == ["active", "active"]  # the new pending rows were discarded
    monkeypatch.undo()
    (public,) = client.get(f"{PUBLIC}/categories").json()
    assert public["image"]["url"] == old


def test_unknown_categories_and_oversized_files(client, admin_auth, storage):
    missing = put_file(client, f"{STAFF}/categories/{uuid.uuid4()}/image", admin_auth["headers"])
    assert missing.status_code == 404
    big = put_file(
        client,
        f"{STAFF}/categories/{uuid.uuid4()}/image",
        admin_auth["headers"],
        b"\x00" * (5 * 1024 * 1024 + 200_000),
    )
    assert big.status_code == 413 and big.json()["error"]["code"] == "file_too_large"
    assert stored_files(storage) == []


# ---- B1: brand logo ------------------------------------------------------------------------
def test_brand_logo_upload_replace_and_remove(client, admin_auth, brand, storage, db):
    h = admin_auth["headers"]
    path = f"{STAFF}/brands/{brand['id']}/logo"
    assert brand["logo"] is None
    first = put_file(client, path, h)
    assert first.status_code == 200, first.text
    logo = first.json()["logo"]
    assert logo["alt"] == "Samsung" and (logo["width"], logo["height"]) == (300, 200)
    assert f"/brands/{brand['id']}/" in logo["url"]
    (public,) = client.get(f"{PUBLIC}/brands").json()
    assert public["logo"] == logo

    second = put_file(client, path, h).json()["logo"]
    assert second["url"] != logo["url"]
    run_cleanup(db, storage)
    assert len(stored_files(storage)) == 2
    removed = client.delete(path, headers=h)
    assert removed.status_code == 200 and removed.json()["logo"] is None
    run_cleanup(db, storage)
    assert stored_files(storage) == [] and media_states(db) == []
    assert len(audits(db, "catalog.brand_logo_upload")) == 2
    assert len(audits(db, "catalog.brand_logo_delete")) == 1


def test_deleting_a_brand_retires_its_logo_files(client, admin_auth, brand, storage, db):
    put_file(client, f"{STAFF}/brands/{brand['id']}/logo", admin_auth["headers"])
    assert (
        client.delete(f"{STAFF}/brands/{brand['id']}", headers=admin_auth["headers"]).status_code
        == 204
    )
    run_cleanup(db, storage)
    assert stored_files(storage) == [] and media_states(db) == []


@pytest.mark.parametrize(
    "who", ["operations_auth", "management_auth", "finance_auth", "customer_auth"]
)
def test_only_catalogue_managers_change_category_images_and_brand_logos(
    client, request, admin_auth, category, brand, storage, who
):
    h = request.getfixturevalue(who)["headers"]
    attempts = [
        put_file(client, f"{STAFF}/categories/{category['id']}/image", h),
        client.delete(f"{STAFF}/categories/{category['id']}/image", headers=h),
        put_file(client, f"{STAFF}/brands/{brand['id']}/logo", h),
        client.delete(f"{STAFF}/brands/{brand['id']}/logo", headers=h),
    ]
    assert [r.status_code for r in attempts] == [403] * 4
    assert stored_files(storage) == []


def test_sales_staff_manage_category_images(client, sales_auth, category, storage):
    res = put_file(client, f"{STAFF}/categories/{category['id']}/image", sales_auth["headers"])
    assert res.status_code == 200


def test_anonymous_image_changes_are_unauthorized(client, category, storage):
    assert put_file(client, f"{STAFF}/categories/{category['id']}/image", {}).status_code == 401
    assert client.delete(f"{STAFF}/brands/{uuid.uuid4()}/logo").status_code == 401


# ---- B2 and B4: featured products, created_at -----------------------------------------------
def make_product(client, headers, category_id: str, name: str, **extra) -> dict:
    res = client.post(
        f"{STAFF}/products",
        json={"name": name, "category_id": category_id, **extra},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    product = res.json()
    force_status(product["id"])  # active without images (the guard has its own tests)
    product["status"] = "active"
    variant = client.post(
        f"{STAFF}/products/{product['id']}/variants",
        json={"sku": f"SKU-{uuid.uuid4().hex[:8]}", "name": "Std", "price": 1000},
        headers=headers,
    )
    assert variant.status_code == 201, variant.text
    return {**product, "variant_id": variant.json()["id"]}


def test_featured_flag_is_staff_editable_audited_and_filters_the_catalogue(
    client, admin_auth, category, db
):
    h = admin_auth["headers"]
    pinned = make_product(client, h, category["id"], "Galaxy A55", is_featured=True)
    plain = make_product(client, h, category["id"], "Spark 20")
    assert pinned["is_featured"] is True and plain["is_featured"] is False

    def names(**params) -> list[str]:
        res = client.get(f"{PUBLIC}/products", params=params)
        assert res.status_code == 200, res.text
        return [p["name"] for p in res.json()["items"]]

    assert names(featured="true") == ["Galaxy A55"]
    assert names(featured="false") == ["Spark 20"]
    assert names() == ["Galaxy A55", "Spark 20"]

    res = client.patch(f"{STAFF}/products/{plain['id']}", json={"is_featured": True}, headers=h)
    assert res.status_code == 200 and res.json()["is_featured"] is True
    assert names(featured="true") == ["Galaxy A55", "Spark 20"]
    changes = [
        r.change_summary["changes"]
        for r in audits(db, "catalog.product_update")
        if "is_featured" in r.change_summary["changes"]
    ]
    assert changes == [{"is_featured": {"from": False, "to": True}}]
    null = client.patch(f"{STAFF}/products/{plain['id']}", json={"is_featured": None}, headers=h)
    assert null.status_code == 422


def add_variant(client, headers, product_id: str, **fields) -> str:
    res = client.post(
        f"{STAFF}/products/{product_id}/variants",
        json={"sku": f"SKU-{uuid.uuid4().hex[:8]}", "name": "Alt", "price": 1000, **fields},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def set_variant(client, headers, product: dict, variant_id: str, **fields) -> None:
    res = client.patch(
        f"{STAFF}/products/{product['id']}/variants/{variant_id}", json=fields, headers=headers
    )
    assert res.status_code == 200, res.text


def test_on_sale_lists_products_with_an_active_variant_below_its_compare_at_price(
    client, admin_auth, category
):
    """Deals (owner decision 2026-10-27): on_sale=true keeps a product when any active variant
    has compare_at_price > price; on_sale=false keeps the others."""
    h = admin_auth["headers"]
    deal = make_product(client, h, category["id"], "A deal")
    set_variant(client, h, deal, deal["variant_id"], compare_at_price=1500)
    second = make_product(client, h, category["id"], "B second variant on sale")
    add_variant(client, h, second["id"], price=800, compare_at_price=900)
    equal = make_product(client, h, category["id"], "C compare equals price")
    set_variant(client, h, equal, equal["variant_id"], compare_at_price=1000)
    lower = make_product(client, h, category["id"], "D compare below price")
    set_variant(client, h, lower, lower["variant_id"], compare_at_price=900)
    inactive = make_product(client, h, category["id"], "E inactive variant on sale")
    add_variant(client, h, inactive["id"], price=500, compare_at_price=2000, is_active=False)
    make_product(client, h, category["id"], "F no compare price")

    def names(**params) -> list[str]:
        res = client.get(f"{PUBLIC}/products", params=params)
        assert res.status_code == 200, res.text
        assert res.json()["total"] == len(res.json()["items"])
        return [p["name"] for p in res.json()["items"]]

    assert names(on_sale="true") == ["A deal", "B second variant on sale"]
    assert names(on_sale="false") == [
        "C compare equals price",
        "D compare below price",
        "E inactive variant on sale",
        "F no compare price",
    ]
    assert len(names()) == 6
    assert names(on_sale="true", category=category["slug"], q="deal") == ["A deal"]

    # Clearing the compare-at price ends the deal at once.
    set_variant(client, h, deal, deal["variant_id"], compare_at_price=None)
    assert names(on_sale="true") == ["B second variant on sale"]
    assert client.get(f"{PUBLIC}/products", params={"on_sale": "maybe"}).status_code == 422


def test_catalogue_products_carry_is_featured_and_created_at(client, admin_auth, category):
    make_product(client, admin_auth["headers"], category["id"], "Pixel 8", is_featured=True)
    listed = client.get(f"{PUBLIC}/products").json()["items"][0]
    detail = client.get(f"{PUBLIC}/products/pixel-8").json()
    for body in (listed, detail):
        assert body["is_featured"] is True
        assert datetime.fromisoformat(body["created_at"]).tzinfo is not None
    assert listed["created_at"] == detail["created_at"]


# ---- B3: bestselling (delivered orders, last 90 days; rule approved 2026-10-26) -------------
def sell(
    db: Session, product: dict, quantity: int, status: str = "delivered", days_ago: int = 1
) -> None:
    variant = db.get(ProductVariant, uuid.UUID(product["variant_id"]))
    assert variant is not None
    order = new_order({variant.id: quantity})
    order.status = status
    order.items[0].product_id = variant.product_id
    db.add(order)
    db.flush()
    when = datetime.now(UTC) - timedelta(days=days_ago)
    db.add(OrderStatusHistory(order_id=order.id, status="received", created_at=when))
    if status == "delivered":
        db.add(OrderStatusHistory(order_id=order.id, status="delivered", created_at=when))
    db.commit()


def test_bestselling_counts_only_orders_delivered_in_the_last_90_days(
    client, admin_auth, category, db
):
    h = admin_auth["headers"]
    alpha = make_product(client, h, category["id"], "Alpha")
    bravo = make_product(client, h, category["id"], "Bravo")
    charlie = make_product(client, h, category["id"], "Charlie")
    delta = make_product(client, h, category["id"], "Delta")
    make_product(client, h, category["id"], "Echo", is_featured=True)  # never sold
    make_product(client, h, category["id"], "Foxtrot")  # never sold, newest
    sell(db, alpha, 2)
    sell(db, bravo, 3)
    for status in ("received", "confirmed", "processing", "dispatched", "cancelled"):
        sell(db, bravo, 40, status=status)  # not delivered: not a sale
        sell(db, charlie, 40, status=status)
    sell(db, delta, 100, days_ago=91)  # delivered, but outside the window
    sell(db, delta, 1, days_ago=89)
    sell(db, alpha, 2, days_ago=89)

    def names(**params) -> list[str]:
        res = client.get(f"{PUBLIC}/products", params={"sort_by": "bestselling", **params})
        assert res.status_code == 200, res.text
        return [p["name"] for p in res.json()["items"]]

    # Units 4 (2 + 2), 3, 1, then the unsold: featured first, then newest first.
    assert names() == ["Alpha", "Bravo", "Delta", "Echo", "Foxtrot", "Charlie"]
    # sort_direction flips only the units; the tie-break order stays.
    assert names(sort_direction="asc") == ["Echo", "Foxtrot", "Charlie", "Delta", "Bravo", "Alpha"]
    assert names(size=2, page=2) == ["Delta", "Echo"]


def test_bestselling_ties_are_featured_then_newest(client, admin_auth, category):
    h = admin_auth["headers"]
    for name, featured in (("Old", False), ("Pinned", True), ("New", False)):
        make_product(client, h, category["id"], name, is_featured=featured)
    res = client.get(f"{PUBLIC}/products", params={"sort_by": "bestselling"})
    assert [p["name"] for p in res.json()["items"]] == ["Pinned", "New", "Old"]


def test_unknown_sort_values_are_rejected(client):
    res = client.get(f"{PUBLIC}/products", params={"sort_by": "popularity"})
    assert res.status_code == 422


# ---- Category spotlight product (approved 2026-11-11) ---------------------------------------
def spotlight_of(client, slug: str) -> str | None:
    def walk(nodes):
        for node in nodes:
            if node["slug"] == slug:
                return node
            found = walk(node["children"])
            if found:
                return found
        return None

    node = walk(client.get(f"{PUBLIC}/categories").json())
    assert node is not None
    return node["spotlight_product_slug"]


def test_spotlight_product_is_picked_audited_public_and_cleared(client, admin_auth, category, db):
    h = admin_auth["headers"]
    url = f"{STAFF}/categories/{category['id']}"
    sub = client.post(
        f"{STAFF}/categories", json={"name": "Android", "parent_id": category["id"]}, headers=h
    ).json()
    product = make_product(client, h, sub["id"], "Galaxy A55")
    assert category["spotlight_product_id"] is None and spotlight_of(client, "phones") is None

    # A product of a subcategory counts.
    res = client.patch(url, json={"spotlight_product_id": product["id"]}, headers=h)
    assert res.status_code == 200, res.text
    assert res.json()["spotlight_product_id"] == product["id"]
    assert spotlight_of(client, "phones") == "galaxy-a55"
    (audit,) = audits(db, "catalog.category_update")
    assert audit.change_summary["changes"]["spotlight_product_id"]["to"] == product["id"]

    listed = client.get(f"{STAFF}/categories", headers=h).json()["items"]
    assert {c["slug"]: c["spotlight_product_id"] for c in listed}["phones"] == product["id"]

    # Hidden while the product is not public.
    force_status(product["id"], "draft")
    assert spotlight_of(client, "phones") is None
    force_status(product["id"])

    cleared = client.patch(url, json={"spotlight_product_id": None}, headers=h)
    assert cleared.status_code == 200 and cleared.json()["spotlight_product_id"] is None
    assert spotlight_of(client, "phones") is None


def test_spotlight_product_must_be_in_the_category(client, admin_auth, category):
    h = admin_auth["headers"]
    other = client.post(f"{STAFF}/categories", json={"name": "Laptops"}, headers=h).json()
    laptop = make_product(client, h, other["id"], "ThinkPad")
    url = f"{STAFF}/categories/{category['id']}"
    for product_id in (laptop["id"], str(uuid.uuid4())):
        res = client.patch(url, json={"spotlight_product_id": product_id}, headers=h)
        assert res.status_code == 422, res.text
        assert res.json()["error"]["details"][0]["loc"] == ["body", "spotlight_product_id"]


def test_moving_the_spotlight_product_away_hides_it(client, admin_auth, category, db):
    h = admin_auth["headers"]
    other = client.post(f"{STAFF}/categories", json={"name": "Laptops"}, headers=h).json()
    product = make_product(client, h, category["id"], "Galaxy A55")
    client.patch(
        f"{STAFF}/categories/{category['id']}",
        json={"spotlight_product_id": product["id"]},
        headers=h,
    )
    moved = client.patch(
        f"{STAFF}/products/{product['id']}", json={"category_id": other["id"]}, headers=h
    )
    assert moved.status_code == 200, moved.text
    assert spotlight_of(client, "phones") is None
    db.expire_all()
    stored = db.get(Category, uuid.UUID(category["id"]))
    assert stored is not None and str(stored.spotlight_product_id) == product["id"]
