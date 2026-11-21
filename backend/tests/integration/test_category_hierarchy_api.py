"""Category hierarchy (approved 2026-11-16): main category, then subcategory.

- The staff API caps the tree at two levels and reorders the categories under one parent.
- A main category's listing and filter counts include its subcategories' products.
- Hiding a main category hides its subcategories' products everywhere the public sees them.
- A product cannot be newly assigned to a hidden category or brand; one already there keeps it.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Category, InventoryBalance
from app.models.operations import AuditRecord
from app.services import inventory
from tests.support.catalog import force_status

STAFF = "/api/v1/staff"
PUBLIC = "/api/v1/catalog"


def category(client, h, name, **fields) -> dict:
    res = client.post(f"{STAFF}/categories", json={"name": name, **fields}, headers=h)
    assert res.status_code == 201, res.text
    return res.json()


def brand(client, h, name, **fields) -> dict:
    """A brand needs a main category (ADR-012 decision 9); one is made when none is given."""
    if "category_ids" not in fields:
        fields["category_ids"] = [category(client, h, f"Main {uuid.uuid4().hex[:8]}")["id"]]
    res = client.post(f"{STAFF}/brands", json={"name": name, **fields}, headers=h)
    assert res.status_code == 201, res.text
    return res.json()


def product(client, h, name, category_id, brand_id=None, publish=True) -> dict:
    body = {"name": name, "category_id": category_id, "brand_id": brand_id}
    res = client.post(f"{STAFF}/products", json=body, headers=h)
    assert res.status_code == 201, res.text
    if publish:
        force_status(res.json()["id"])  # active without images (the guard has its own tests)
    return res.json()


def listing(client, **params) -> list[str]:
    res = client.get(f"{PUBLIC}/products", params=params)
    assert res.status_code == 200, res.text
    return sorted(p["slug"] for p in res.json()["items"])


def error(res) -> tuple[int, str]:
    return res.status_code, res.json()["error"]["code"]


def field_message(res, field: str) -> str:
    assert res.status_code == 422, res.text
    (detail,) = [d for d in res.json()["error"]["details"] if d["loc"][-1] == field]
    return detail["msg"]


@pytest.fixture
def tree(client: TestClient, admin_auth: dict) -> dict:
    """Phones (Smartphones, Tablets) and Laptops, one brand, one product per category."""
    h = admin_auth["headers"]
    phones = category(client, h, "Phones & Tablets", slug="phones", sort_order=1)
    laptops = category(client, h, "Laptops & Computers", slug="laptops", sort_order=2)
    smart = category(client, h, "Smartphones", parent_id=phones["id"], sort_order=1)
    tablets = category(client, h, "Tablets", parent_id=phones["id"], sort_order=2)
    samsung = brand(client, h, "Samsung", category_ids=[phones["id"]])
    return {
        "h": h,
        "phones": phones,
        "laptops": laptops,
        "smart": smart,
        "tablets": tablets,
        "samsung": samsung,
        "galaxy": product(client, h, "Galaxy S24", smart["id"], samsung["id"]),
        "tab": product(client, h, "Galaxy Tab S9", tablets["id"], samsung["id"]),
        "phone_case": product(client, h, "Universal Phone Stand", phones["id"]),
        "book": product(client, h, "Galaxy Book4", laptops["id"], samsung["id"]),
    }


# ---- two levels ----------------------------------------------------------------------------------
def test_a_subcategory_cannot_have_subcategories(client, tree):
    res = client.post(
        f"{STAFF}/categories",
        json={"name": "Android", "parent_id": tree["smart"]["id"]},
        headers=tree["h"],
    )
    assert "main category" in field_message(res, "parent_id")


def test_a_category_with_subcategories_cannot_be_moved_under_another(client, tree):
    res = client.patch(
        f"{STAFF}/categories/{tree['phones']['id']}",
        json={"parent_id": tree["laptops"]["id"]},
        headers=tree["h"],
    )
    assert "subcategories" in field_message(res, "parent_id")


def test_a_subcategory_moves_to_another_main_category_or_to_the_top(client, db, tree):
    path = f"{STAFF}/categories/{tree['tablets']['id']}"
    moved = client.patch(path, json={"parent_id": tree["laptops"]["id"]}, headers=tree["h"])
    assert moved.status_code == 200 and moved.json()["parent_id"] == tree["laptops"]["id"]
    # Laptops now has a subcategory, so it cannot become one itself.
    res = client.patch(
        f"{STAFF}/categories/{tree['laptops']['id']}",
        json={"parent_id": tree["phones"]["id"]},
        headers=tree["h"],
    )
    assert "subcategories" in field_message(res, "parent_id")
    # Once Tablets moves to the top, Laptops has none and may become a subcategory.
    top = client.patch(path, json={"parent_id": None}, headers=tree["h"])
    assert top.status_code == 200 and top.json()["parent_id"] is None
    under = client.patch(
        f"{STAFF}/categories/{tree['laptops']['id']}",
        json={"parent_id": tree["phones"]["id"]},
        headers=tree["h"],
    )
    assert under.status_code == 200


# ---- reorder -------------------------------------------------------------------------------------
def order(client, h, parent_id, ids):
    return client.put(
        f"{STAFF}/categories/order", json={"parent_id": parent_id, "category_ids": ids}, headers=h
    )


def reorder_audits(db: Session) -> list[AuditRecord]:
    db.expire_all()
    query = select(AuditRecord).where(AuditRecord.action == "catalog.category_reorder")
    return list(db.scalars(query))


def test_subcategories_and_main_categories_are_reordered_and_audited_once(client, db, tree):
    h = tree["h"]
    res = order(client, h, tree["phones"]["id"], [tree["tablets"]["id"], tree["smart"]["id"]])
    assert res.status_code == 204
    res = order(client, h, None, [tree["laptops"]["id"], tree["phones"]["id"]])
    assert res.status_code == 204

    public = client.get(f"{PUBLIC}/categories").json()
    assert [c["slug"] for c in public] == ["laptops", "phones"]
    assert [c["slug"] for c in public[1]["children"]] == ["tablets", "smartphones"]
    records = reorder_audits(db)
    assert [r.entity_id for r in records] == [tree["phones"]["id"], "top-level"]
    assert records[0].change_summary["changes"] == [
        {"id": tree["tablets"]["id"], "from": 2, "to": 1},
        {"id": tree["smart"]["id"], "from": 1, "to": 2},
    ]
    # The same order again changes nothing and is not audited.
    assert order(client, h, None, [tree["laptops"]["id"], tree["phones"]["id"]]).status_code == 204
    assert len(reorder_audits(db)) == 2


def test_an_incomplete_or_foreign_order_is_refused_and_changes_nothing(client, db, tree):
    h = tree["h"]
    phones = tree["phones"]["id"]
    for ids in (
        [tree["smart"]["id"]],  # Tablets missing
        [tree["smart"]["id"], tree["tablets"]["id"], tree["laptops"]["id"]],  # not under Phones
        [tree["smart"]["id"], str(uuid.uuid4())],
    ):
        assert error(order(client, h, phones, ids)) == (409, "category_order_mismatch")
    duplicate = order(client, h, phones, [tree["smart"]["id"], tree["smart"]["id"]])
    assert duplicate.status_code == 422
    unknown = order(client, h, str(uuid.uuid4()), [tree["smart"]["id"]])
    assert field_message(unknown, "parent_id") == "Parent category not found."
    assert order(client, h, phones, []).status_code == 422
    db.expire_all()
    assert db.get(Category, uuid.UUID(tree["smart"]["id"])).sort_order == 1
    assert reorder_audits(db) == []


def test_hidden_categories_are_part_of_the_order(client, tree):
    h = tree["h"]
    hidden = category(client, h, "Feature Phones", parent_id=tree["phones"]["id"], is_active=False)
    ids = [tree["smart"]["id"], tree["tablets"]["id"]]
    assert error(order(client, h, tree["phones"]["id"], ids)) == (409, "category_order_mismatch")
    res = order(client, h, tree["phones"]["id"], [hidden["id"], *ids])
    assert res.status_code == 204


def test_reordering_needs_catalog_manage(client, tree, admin_auth, customer_auth):
    ids = [tree["phones"]["id"], tree["laptops"]["id"]]
    assert order(client, admin_auth["headers"], None, ids).status_code == 204
    assert order(client, customer_auth["headers"], None, ids).status_code == 403
    res = client.put(f"{STAFF}/categories/order", json={"category_ids": ids})
    assert res.status_code == 401


# ---- the storefront ------------------------------------------------------------------------------
def test_a_main_category_lists_its_subcategories_products(client, tree):
    assert listing(client, category="phones") == [
        "galaxy-s24",
        "galaxy-tab-s9",
        "universal-phone-stand",
    ]
    assert listing(client, category="smartphones") == ["galaxy-s24"]
    assert listing(client, category="phones", brand="samsung") == ["galaxy-s24", "galaxy-tab-s9"]
    assert listing(client, category="unknown") == []


def test_filter_counts_include_subcategories_and_group_by_main_category(client, tree):
    facets = client.get(f"{PUBLIC}/facets", params={"category": "phones"}).json()
    assert facets["total"] == 3
    assert [(b["slug"], b["count"]) for b in facets["brands"]] == [("samsung", 2)]
    # On a brand page the Category group shows main categories, in menu order.
    facets = client.get(f"{PUBLIC}/facets", params={"brand": "samsung"}).json()
    assert [(c["slug"], c["count"]) for c in facets["categories"]] == [
        ("phones", 2),
        ("laptops", 1),
    ]


def test_hiding_a_main_category_hides_its_subcategories_products(client, db, tree):
    h = tree["h"]
    variant = client.post(
        f"{STAFF}/products/{tree['galaxy']['id']}/variants",
        json={"sku": "GS24", "name": "128 GB", "price": 1000},
        headers=h,
    ).json()
    db.add(InventoryBalance(variant_id=uuid.UUID(variant["id"]), on_hand=5))
    db.commit()
    variant_id = uuid.UUID(variant["id"])
    assert inventory.sellable_variants(db, {variant_id}) == {variant_id: True}

    path = f"{STAFF}/categories/{tree['phones']['id']}"
    assert client.patch(path, json={"is_active": False}, headers=h).status_code == 200
    assert listing(client) == ["galaxy-book4"]
    assert listing(client, q="galaxy") == ["galaxy-book4"]
    assert client.get(f"{PUBLIC}/products/galaxy-s24").status_code == 404
    db.expire_all()
    assert inventory.sellable_variants(db, {variant_id}) == {variant_id: False}

    assert client.patch(path, json={"is_active": True}, headers=h).status_code == 200
    assert "galaxy-s24" in listing(client)


# ---- product assignment --------------------------------------------------------------------------
def test_new_products_cannot_go_into_hidden_categories_or_hidden_brands(client, tree):
    h = tree["h"]
    hidden = category(client, h, "Feature Phones", parent_id=tree["phones"]["id"], is_active=False)
    off = brand(client, h, "Retired", is_active=False)
    res = client.post(
        f"{STAFF}/products", json={"name": "Nokia 105", "category_id": hidden["id"]}, headers=h
    )
    assert "hidden" in field_message(res, "category_id")
    res = client.post(
        f"{STAFF}/products",
        json={"name": "Old phone", "category_id": tree["smart"]["id"], "brand_id": off["id"]},
        headers=h,
    )
    assert "hidden" in field_message(res, "brand_id")

    # A visible subcategory of a hidden main category is hidden too.
    path = f"{STAFF}/categories/{tree['phones']['id']}"
    assert client.patch(path, json={"is_active": False}, headers=h).status_code == 200
    res = client.post(
        f"{STAFF}/products", json={"name": "Pixel 9", "category_id": tree["smart"]["id"]}, headers=h
    )
    assert "hidden" in field_message(res, "category_id")


def test_a_product_keeps_a_category_and_brand_hidden_after_assignment(client, db, tree):
    h = tree["h"]
    galaxy = f"{STAFF}/products/{tree['galaxy']['id']}"
    client.patch(f"{STAFF}/categories/{tree['smart']['id']}", json={"is_active": False}, headers=h)
    client.patch(f"{STAFF}/brands/{tree['samsung']['id']}", json={"is_active": False}, headers=h)

    # Other edits still work, and sending the current category and brand again is not a change.
    res = client.patch(
        galaxy,
        json={
            "name": "Galaxy S24 5G",
            "category_id": tree["smart"]["id"],
            "brand_id": tree["samsung"]["id"],
        },
        headers=h,
    )
    assert res.status_code == 200, res.text
    assert res.json()["category_id"] == tree["smart"]["id"]

    # Moving a product into a hidden category, or giving it a hidden brand, is refused.
    book = f"{STAFF}/products/{tree['book']['id']}"
    res = client.patch(book, json={"category_id": tree["smart"]["id"]}, headers=h)
    assert "hidden" in field_message(res, "category_id")
    res = client.patch(
        f"{STAFF}/products/{tree['phone_case']['id']}",
        json={"brand_id": tree["samsung"]["id"]},
        headers=h,
    )
    assert "hidden" in field_message(res, "brand_id")
    # Out of the hidden category into a visible one is fine.
    res = client.patch(galaxy, json={"category_id": tree["tablets"]["id"]}, headers=h)
    assert res.status_code == 200


def test_a_product_may_sit_directly_in_a_main_category_with_subcategories(client, tree):
    # Subcategory is optional (2026-11-16): Phones has subcategories and still takes products.
    res = client.get(f"{STAFF}/products/{tree['phone_case']['id']}", headers=tree["h"])
    assert res.status_code == 200 and res.json()["category_id"] == tree["phones"]["id"]


def test_legacy_deeper_categories_still_follow_the_hidden_subtree_rule(client, db, tree):
    deep = Category(name="Android", slug="android", parent_id=uuid.UUID(tree["smart"]["id"]))
    db.add(deep)
    db.commit()
    deep_product = product(client, tree["h"], "Legacy Phone", str(deep.id))
    assert "legacy-phone" in listing(client, category="phones")
    db.execute(
        update(Category)
        .where(Category.id == uuid.UUID(tree["phones"]["id"]))
        .values(is_active=False)
    )
    db.commit()
    assert "legacy-phone" not in listing(client)
    assert client.get(f"{PUBLIC}/products/{deep_product['slug']}").status_code == 404


# ---- menu brands (ADR-012 amendment, 2026-11-16) -------------------------------------------------
def menu_brands(client, h, category_id, brand_ids):
    return client.put(
        f"{STAFF}/categories/{category_id}/menu-brands", json={"brand_ids": brand_ids}, headers=h
    )


def public_menu(client) -> dict[str, list[str]]:
    res = client.get(f"{PUBLIC}/categories")
    assert res.status_code == 200, res.text
    return {c["slug"]: [b["slug"] for b in c["menu_brands"]] for c in res.json()}


def staff_menu(client, h, category_id) -> list[str]:
    items = client.get(f"{STAFF}/categories", headers=h).json()["items"]
    return next(c["menu_brand_ids"] for c in items if c["id"] == category_id)


def test_a_main_category_lists_chosen_brands_in_order_even_without_products(client, db, tree):
    h = tree["h"]
    apple = brand(client, h, "Apple")
    pixel = brand(client, h, "Google")
    ids = [apple["id"], tree["samsung"]["id"], pixel["id"]]
    res = menu_brands(client, h, tree["phones"]["id"], ids)
    assert res.status_code == 200, res.text
    assert res.json() == ids
    assert public_menu(client)["phones"] == ["apple", "samsung", "google"]
    assert public_menu(client)["laptops"] == []
    assert staff_menu(client, h, tree["phones"]["id"]) == ids

    records = db.scalars(
        select(AuditRecord).where(AuditRecord.action == "catalog.category_menu_brands")
    ).all()
    assert len(records) == 1
    assert records[0].change_summary["to"] == ids

    # The same list again changes nothing and is not audited; a new order replaces it.
    assert menu_brands(client, h, tree["phones"]["id"], ids).status_code == 200
    reordered = [pixel["id"], apple["id"]]
    assert menu_brands(client, h, tree["phones"]["id"], reordered).json() == reordered
    assert public_menu(client)["phones"] == ["google", "apple"]
    records = db.scalars(
        select(AuditRecord).where(AuditRecord.action == "catalog.category_menu_brands")
    ).all()
    assert len(records) == 2

    assert menu_brands(client, h, tree["phones"]["id"], []).json() == []
    assert public_menu(client)["phones"] == []


def test_menu_brands_are_checked(client, tree):
    h = tree["h"]
    res = menu_brands(client, h, tree["smart"]["id"], [tree["samsung"]["id"]])
    assert "main category" in field_message(res, "brand_ids")
    res = menu_brands(client, h, tree["phones"]["id"], [str(uuid.uuid4())])
    assert field_message(res, "brand_ids") == "Brand not found."
    res = menu_brands(client, h, tree["phones"]["id"], [tree["samsung"]["id"]] * 2)
    assert res.status_code == 422
    res = menu_brands(client, h, str(uuid.uuid4()), [])
    assert error(res) == (404, "category_not_found")
    hidden = brand(client, h, "Nokia", is_active=False)
    res = menu_brands(client, h, tree["phones"]["id"], [hidden["id"]])
    assert "hidden" in field_message(res, "brand_ids")


def test_a_brand_hidden_later_stays_listed_but_leaves_the_storefront(client, tree):
    h = tree["h"]
    apple = brand(client, h, "Apple")
    ids = [apple["id"], tree["samsung"]["id"]]
    assert menu_brands(client, h, tree["phones"]["id"], ids).status_code == 200
    res = client.patch(f"{STAFF}/brands/{apple['id']}", json={"is_active": False}, headers=h)
    assert res.status_code == 200, res.text
    assert public_menu(client)["phones"] == ["samsung"]
    assert staff_menu(client, h, tree["phones"]["id"]) == ids
    # Keeping it (in any order) is allowed; it is not a new addition.
    assert menu_brands(client, h, tree["phones"]["id"], ids[::-1]).status_code == 200


def test_deleting_a_listed_brand_or_category_removes_it_from_menus(client, tree):
    h = tree["h"]
    apple = brand(client, h, "Apple")
    cameras = category(client, h, "Cameras")
    assert menu_brands(client, h, tree["phones"]["id"], [apple["id"]]).status_code == 200
    assert menu_brands(client, h, cameras["id"], [apple["id"]]).status_code == 200
    assert client.delete(f"{STAFF}/categories/{cameras['id']}", headers=h).status_code == 204
    assert client.delete(f"{STAFF}/brands/{apple['id']}", headers=h).status_code == 204
    assert public_menu(client)["phones"] == []


def test_menu_brands_need_catalog_manage(client, tree, customer_auth):
    res = menu_brands(client, customer_auth["headers"], tree["phones"]["id"], [])
    assert error(res) == (403, "permission_denied")


# ---- brand categories (ADR-012 decision 9, 2026-11-17) ------------------------------------------
def staff_brand(client, h, brand_id: str) -> dict:
    res = client.get(f"{STAFF}/brands", headers=h)
    assert res.status_code == 200, res.text
    return next(b for b in res.json()["items"] if b["id"] == brand_id)


def test_a_new_brand_needs_main_categories(client, tree):
    h = tree["h"]
    for body in ({"name": "Oppo"}, {"name": "Oppo", "category_ids": []}):
        res = client.post(f"{STAFF}/brands", json=body, headers=h)
        assert res.status_code == 422, res.text
    phones = tree["phones"]["id"]
    res = client.post(
        f"{STAFF}/brands", json={"name": "Oppo", "category_ids": [phones, phones]}, headers=h
    )
    assert "once" in field_message(res, "category_ids")
    res = client.post(
        f"{STAFF}/brands",
        json={"name": "Oppo", "category_ids": [tree["smart"]["id"]]},
        headers=h,
    )
    assert "main categor" in field_message(res, "category_ids")
    res = client.post(
        f"{STAFF}/brands", json={"name": "Oppo", "category_ids": [str(uuid.uuid4())]}, headers=h
    )
    assert field_message(res, "category_ids") == "Category not found."


def test_a_brand_lists_its_categories_in_menu_order_and_they_can_be_replaced(client, db, tree):
    h = tree["h"]
    phones, laptops = tree["phones"]["id"], tree["laptops"]["id"]
    oppo = brand(client, h, "Oppo", category_ids=[laptops, phones])
    assert staff_brand(client, h, oppo["id"])["category_ids"] == [phones, laptops]
    created = db.scalars(
        select(AuditRecord).where(
            AuditRecord.action == "catalog.brand_create", AuditRecord.entity_id == oppo["id"]
        )
    ).one()
    assert sorted(created.change_summary["category_ids"]) == sorted([laptops, phones])

    path = f"{STAFF}/brands/{oppo['id']}"
    res = client.patch(path, json={"category_ids": [phones]}, headers=h)
    assert res.status_code == 200, res.text
    assert staff_brand(client, h, oppo["id"])["category_ids"] == [phones]
    # The same categories again (any order) change nothing and are not audited.
    assert client.patch(path, json={"category_ids": [phones]}, headers=h).status_code == 200
    updates = db.scalars(
        select(AuditRecord).where(
            AuditRecord.action == "catalog.brand_update", AuditRecord.entity_id == oppo["id"]
        )
    ).all()
    assert [u.change_summary["changes"]["category_ids"]["to"] for u in updates] == [[phones]]
    # A brand keeps at least one; null is not "none".
    assert client.patch(path, json={"category_ids": []}, headers=h).status_code == 422
    assert client.patch(path, json={"category_ids": None}, headers=h).status_code == 422
    # Renaming alone leaves the categories as they are.
    assert client.patch(path, json={"name": "OPPO"}, headers=h).status_code == 200
    assert staff_brand(client, h, oppo["id"])["category_ids"] == [phones]


def test_a_main_category_moved_under_another_hands_its_brands_to_it(client, db, tree):
    h = tree["h"]
    gaming = category(client, h, "Gaming", sort_order=3)
    razer = brand(client, h, "Razer", category_ids=[gaming["id"]])
    both = brand(client, h, "Both", category_ids=[gaming["id"], tree["laptops"]["id"]])
    res = client.patch(
        f"{STAFF}/categories/{gaming['id']}",
        json={"parent_id": tree["laptops"]["id"]},
        headers=h,
    )
    assert res.status_code == 200, res.text
    assert staff_brand(client, h, razer["id"])["category_ids"] == [tree["laptops"]["id"]]
    assert staff_brand(client, h, both["id"])["category_ids"] == [tree["laptops"]["id"]]
    record = db.scalars(
        select(AuditRecord).where(
            AuditRecord.action == "catalog.category_update",
            AuditRecord.entity_id == gaming["id"],
        )
    ).one()
    moved = record.change_summary["changes"]["brands_moved_to_parent"]["to"]
    assert sorted(moved) == sorted([razer["id"], both["id"]])


def test_deleting_a_category_removes_it_from_brands(client, tree):
    h = tree["h"]
    cameras = category(client, h, "Cameras")
    canon = brand(client, h, "Canon", category_ids=[cameras["id"], tree["phones"]["id"]])
    assert client.delete(f"{STAFF}/categories/{cameras['id']}", headers=h).status_code == 204
    assert staff_brand(client, h, canon["id"])["category_ids"] == [tree["phones"]["id"]]


def test_a_brand_in_a_store_menu_belongs_to_that_category(client, db, tree):
    h = tree["h"]
    phones, laptops = tree["phones"]["id"], tree["laptops"]["id"]
    asus = brand(client, h, "Asus", category_ids=[laptops])
    assert menu_brands(client, h, phones, [asus["id"], tree["samsung"]["id"]]).status_code == 200
    # Listing it in the Phones menu made it a Phones brand; Samsung already was one.
    assert staff_brand(client, h, asus["id"])["category_ids"] == [phones, laptops]
    record = db.scalars(
        select(AuditRecord).where(AuditRecord.action == "catalog.category_menu_brands")
    ).one()
    assert record.change_summary["brands_linked"] == [asus["id"]]

    # While the Phones menu lists it, Phones cannot be taken from it.
    path = f"{STAFF}/brands/{asus['id']}"
    res = client.patch(path, json={"category_ids": [laptops]}, headers=h)
    assert "store menu of Phones" in field_message(res, "category_ids")
    # Off the menu, it stays a Phones brand until staff remove it.
    assert menu_brands(client, h, phones, [tree["samsung"]["id"]]).status_code == 200
    assert staff_brand(client, h, asus["id"])["category_ids"] == [phones, laptops]
    assert client.patch(path, json={"category_ids": [laptops]}, headers=h).status_code == 200
    assert staff_brand(client, h, asus["id"])["category_ids"] == [laptops]
