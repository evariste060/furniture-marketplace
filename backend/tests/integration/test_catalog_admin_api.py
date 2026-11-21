"""Module 5 — categories and brands (RE-018; TC-02 browsing, TC-16 staff roles).

Staff management needs 'catalog:manage' (administrator, sales). Public views: the active
category tree and active brands with public product counts.
"""

import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Brand, Category, Product
from app.models.operations import AuditRecord
from app.repositories.audit_repository import AuditRepository
from app.services import catalog_admin

STAFF = "/api/v1/staff"
PUBLIC = "/api/v1/catalog"


def create_category(client, headers, name, **fields):
    res = client.post(f"{STAFF}/categories", json={"name": name, **fields}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def create_brand(client, headers, name, **fields):
    """A brand needs a main category (ADR-012 decision 9); one is made when none is given."""
    if "category_ids" not in fields:
        tag = uuid.uuid4().hex[:8]
        fields["category_ids"] = [create_category(client, headers, f"Main {tag}")["id"]]
    res = client.post(f"{STAFF}/brands", json={"name": name, **fields}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def add_product(db: Session, category_id, brand_id=None, status="active") -> Product:
    tag = uuid.uuid4().hex[:10]
    product = Product(
        name=f"Product {tag}",
        slug=f"product-{tag}",
        category_id=uuid.UUID(str(category_id)),
        brand_id=uuid.UUID(str(brand_id)) if brand_id else None,
        status=status,
        specifications={},
    )
    db.add(product)
    db.commit()
    return product


def audits(db: Session, action: str, entity_id) -> list[AuditRecord]:
    db.expire_all()
    return list(
        db.scalars(
            select(AuditRecord).where(
                AuditRecord.action == action, AuditRecord.entity_id == str(entity_id)
            )
        )
    )


def error_code(res) -> str:
    return res.json()["error"]["code"]


def legacy_category(db: Session, name: str, parent_id, **fields) -> dict:
    """A category stored directly, below a subcategory: the API caps the tree at two levels
    (2026-11-16), but data created before the cap may be deeper and must still behave."""
    slug = name.lower().replace(" ", "-")
    category = Category(name=name, slug=slug, parent_id=uuid.UUID(str(parent_id)), **fields)
    db.add(category)
    db.commit()
    return {"id": str(category.id), "slug": slug}


# ---- public category tree ----------------------------------------------------------------
def test_category_tree_nests_active_children_in_merchandising_order(
    client: TestClient, db: Session, admin_auth: dict
):
    h = admin_auth["headers"]
    phones = create_category(client, h, "Phones", sort_order=2)
    laptops = create_category(client, h, "Laptops", sort_order=1)
    smart = create_category(client, h, "Smartphones", parent_id=phones["id"], sort_order=1)
    basic = create_category(client, h, "Basic Phones", parent_id=phones["id"], sort_order=0)
    android = legacy_category(db, "Android", smart["id"])
    # Inactive branches are hidden together with everything under them.
    retired = create_category(client, h, "Retired", is_active=False)
    create_category(client, h, "Under Retired", parent_id=retired["id"])
    hidden_child = create_category(client, h, "Feature Phones", parent_id=phones["id"])
    legacy_category(db, "Under Hidden", hidden_child["id"])
    assert (
        client.patch(
            f"{STAFF}/categories/{hidden_child['id']}", json={"is_active": False}, headers=h
        ).status_code
        == 200
    )

    tree = client.get(f"{PUBLIC}/categories").json()

    def shape(nodes):
        return [(n["slug"], shape(n["children"])) for n in nodes]

    assert shape(tree) == [
        ("laptops", []),
        ("phones", [("basic-phones", []), ("smartphones", [("android", [])])]),
    ]
    assert tree[1]["id"] == phones["id"] and tree[0]["id"] == laptops["id"]
    assert tree[1]["children"][1]["parent_id"] == phones["id"]
    assert tree[1]["children"][1]["children"][0]["id"] == android["id"]
    assert tree[1]["children"][0]["id"] == basic["id"]


def test_category_tree_is_empty_without_categories(client: TestClient):
    res = client.get(f"{PUBLIC}/categories")
    assert res.status_code == 200 and res.json() == []


# ---- public brands -------------------------------------------------------------------------
def test_brands_count_only_public_products_and_hide_inactive_brands(
    client: TestClient, db: Session, admin_auth: dict
):
    h = admin_auth["headers"]
    shown = create_category(client, h, "Shown")
    hidden = create_category(client, h, "Hidden Category", is_active=False)
    acme = create_brand(client, h, "Acme")
    zeta = create_brand(client, h, "Zeta")
    retired = create_brand(client, h, "Retired Brand", is_active=False)
    add_product(db, shown["id"], acme["id"])
    add_product(db, shown["id"], acme["id"])
    add_product(db, shown["id"], acme["id"], status="draft")
    add_product(db, shown["id"], acme["id"], status="hidden")
    add_product(db, hidden["id"], acme["id"])
    add_product(db, shown["id"], retired["id"])
    add_product(db, shown["id"])  # no brand

    brands = client.get(f"{PUBLIC}/brands").json()
    assert [(b["slug"], b["product_count"]) for b in brands] == [("acme", 2), ("zeta", 0)]
    assert brands[1]["id"] == zeta["id"]


# ---- slugs -----------------------------------------------------------------------------------
def test_slugs_are_generated_with_numeric_suffixes_and_explicit_slugs_must_be_free(
    client: TestClient, admin_auth: dict
):
    h = admin_auth["headers"]
    first = create_category(client, h, "Smart Phones")
    second = create_category(client, h, "smart  phones!")
    third = create_category(client, h, "Smart-Phones")
    assert [first["slug"], second["slug"], third["slug"]] == [
        "smart-phones",
        "smart-phones-2",
        "smart-phones-3",
    ]
    assert create_category(client, h, "Écouteurs")["slug"] == "ecouteurs"
    assert create_category(client, h, "Custom", slug="my-custom")["slug"] == "my-custom"

    taken = client.post(
        f"{STAFF}/categories", json={"name": "Other", "slug": "smart-phones"}, headers=h
    )
    assert taken.status_code == 409 and error_code(taken) == "slug_taken"
    # Slugs are unique per table: a brand may reuse a category slug.
    assert create_brand(client, h, "Smart Phones")["slug"] == "smart-phones"


@pytest.mark.parametrize("slug", ["Bad Slug", "UPPER", "double--hyphen", "-edge", "a" * 181, ""])
def test_malformed_slugs_are_rejected(client: TestClient, admin_auth: dict, slug):
    res = client.post(
        f"{STAFF}/categories", json={"name": "X", "slug": slug}, headers=admin_auth["headers"]
    )
    assert res.status_code == 422 and error_code(res) == "validation_error"


def test_name_without_letters_or_digits_needs_an_explicit_slug(
    client: TestClient, admin_auth: dict
):
    h = admin_auth["headers"]
    main = create_category(client, h, "Main")["id"]
    res = client.post(f"{STAFF}/brands", json={"name": "!!!", "category_ids": [main]}, headers=h)
    assert res.status_code == 422
    assert res.json()["error"]["details"][0]["loc"] == ["body", "name"]
    assert create_brand(client, h, "!!!", slug="bang")["slug"] == "bang"


def test_rename_keeps_the_slug_and_slugs_can_be_edited(client: TestClient, admin_auth: dict):
    h = admin_auth["headers"]
    category = create_category(client, h, "Tablets")
    other = create_category(client, h, "Watches")
    renamed = client.patch(
        f"{STAFF}/categories/{category['id']}", json={"name": "Tablets & iPads"}, headers=h
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Tablets & iPads" and renamed.json()["slug"] == "tablets"

    edited = client.patch(
        f"{STAFF}/categories/{category['id']}", json={"slug": "tablets-ipads"}, headers=h
    )
    assert edited.status_code == 200 and edited.json()["slug"] == "tablets-ipads"
    clash = client.patch(
        f"{STAFF}/categories/{other['id']}", json={"slug": "tablets-ipads"}, headers=h
    )
    assert clash.status_code == 409 and error_code(clash) == "slug_taken"
    same = client.patch(
        f"{STAFF}/categories/{category['id']}", json={"slug": "tablets-ipads"}, headers=h
    )
    assert same.status_code == 200  # keeping its own slug is not a conflict

    brand = create_brand(client, h, "Samsung")
    brand_edit = client.patch(
        f"{STAFF}/brands/{brand['id']}", json={"name": "Samsung Electronics"}, headers=h
    )
    assert brand_edit.json()["slug"] == "samsung"
    assert (
        client.patch(
            f"{STAFF}/brands/{brand['id']}", json={"slug": "samsung-electronics"}, headers=h
        ).json()["slug"]
        == "samsung-electronics"
    )


# ---- hierarchy -------------------------------------------------------------------------------
def test_direct_and_indirect_cycles_are_rejected(client: TestClient, db: Session, admin_auth: dict):
    h = admin_auth["headers"]
    top = create_category(client, h, "Top")
    middle = create_category(client, h, "Middle", parent_id=top["id"])
    leaf = legacy_category(db, "Leaf", middle["id"])  # a third level only exists as legacy data

    for target, parent in ((top, top), (top, leaf), (top, middle), (middle, leaf)):
        res = client.patch(
            f"{STAFF}/categories/{target['id']}", json={"parent_id": parent["id"]}, headers=h
        )
        assert res.status_code == 409 and error_code(res) == "category_cycle", (target, parent)
    db.expire_all()
    stored_top = db.get(Category, uuid.UUID(top["id"]))
    assert stored_top is not None and stored_top.parent_id is None

    moved = client.patch(
        f"{STAFF}/categories/{leaf['id']}", json={"parent_id": top["id"]}, headers=h
    )
    assert moved.status_code == 200 and moved.json()["parent_id"] == top["id"]
    to_root = client.patch(f"{STAFF}/categories/{leaf['id']}", json={"parent_id": None}, headers=h)
    assert to_root.status_code == 200 and to_root.json()["parent_id"] is None


def test_unknown_parent_is_a_validation_error(client: TestClient, admin_auth: dict):
    h = admin_auth["headers"]
    res = client.post(
        f"{STAFF}/categories", json={"name": "Orphan", "parent_id": str(uuid.uuid4())}, headers=h
    )
    assert res.status_code == 422
    assert res.json()["error"]["details"][0]["loc"] == ["body", "parent_id"]


# ---- delete and deactivate -------------------------------------------------------------------
def test_category_delete_conflicts_while_in_use_and_deactivation_works(
    client: TestClient, db: Session, admin_auth: dict
):
    h = admin_auth["headers"]
    with_product = create_category(client, h, "With Product")
    add_product(db, with_product["id"])
    parent = create_category(client, h, "Parent")
    create_category(client, h, "Child", parent_id=parent["id"])
    unused = create_category(client, h, "Unused")

    in_use = client.delete(f"{STAFF}/categories/{with_product['id']}", headers=h)
    assert in_use.status_code == 409 and error_code(in_use) == "category_in_use"
    assert in_use.json()["error"]["details"] == {"products": 1, "child_categories": 0}
    has_child = client.delete(f"{STAFF}/categories/{parent['id']}", headers=h)
    assert has_child.status_code == 409
    assert has_child.json()["error"]["details"] == {"products": 0, "child_categories": 1}

    deactivated = client.patch(
        f"{STAFF}/categories/{with_product['id']}", json={"is_active": False}, headers=h
    )
    assert deactivated.status_code == 200 and deactivated.json()["is_active"] is False
    assert "with-product" not in [c["slug"] for c in client.get(f"{PUBLIC}/categories").json()]

    deleted = client.delete(f"{STAFF}/categories/{unused['id']}", headers=h)
    assert deleted.status_code == 204 and deleted.content == b""
    db.expire_all()
    assert db.get(Category, uuid.UUID(unused["id"])) is None
    gone = client.patch(f"{STAFF}/categories/{unused['id']}", json={"name": "X"}, headers=h)
    assert gone.status_code == 404 and error_code(gone) == "category_not_found"
    again = client.delete(f"{STAFF}/categories/{unused['id']}", headers=h)
    assert again.status_code == 404


def test_brand_delete_conflicts_while_in_use_and_deactivation_works(
    client: TestClient, db: Session, admin_auth: dict
):
    h = admin_auth["headers"]
    category = create_category(client, h, "Audio")
    used = create_brand(client, h, "Used Brand")
    add_product(db, category["id"], used["id"], status="draft")  # any product blocks deletion
    unused = create_brand(client, h, "Unused Brand")

    in_use = client.delete(f"{STAFF}/brands/{used['id']}", headers=h)
    assert in_use.status_code == 409 and error_code(in_use) == "brand_in_use"
    assert in_use.json()["error"]["details"] == {"products": 1}
    off = client.patch(f"{STAFF}/brands/{used['id']}", json={"is_active": False}, headers=h)
    assert off.status_code == 200 and off.json()["is_active"] is False
    assert "used-brand" not in [b["slug"] for b in client.get(f"{PUBLIC}/brands").json()]

    assert client.delete(f"{STAFF}/brands/{unused['id']}", headers=h).status_code == 204
    db.expire_all()
    assert db.get(Brand, uuid.UUID(unused["id"])) is None
    missing = client.patch(f"{STAFF}/brands/{unused['id']}", json={"name": "X"}, headers=h)
    assert missing.status_code == 404 and error_code(missing) == "brand_not_found"


# ---- audit -----------------------------------------------------------------------------------
def test_every_successful_change_is_audited_and_no_ops_are_not(
    client: TestClient, db: Session, admin_auth: dict
):
    h = admin_auth["headers"]
    actor_id = admin_auth["user"].id
    category = create_category(client, h, "Cameras", sort_order=3)
    (created,) = audits(db, "catalog.category_create", category["id"])
    assert created.actor_user_id == actor_id and created.entity_type == "category"
    assert created.change_summary["slug"] == "cameras" and created.change_summary["status"] == (
        "success"
    )

    client.patch(
        f"{STAFF}/categories/{category['id']}", json={"name": "Cameras", "sort_order": 3}, headers=h
    )
    assert audits(db, "catalog.category_update", category["id"]) == []  # nothing changed

    client.patch(
        f"{STAFF}/categories/{category['id']}", json={"name": "Digital Cameras"}, headers=h
    )
    (updated,) = audits(db, "catalog.category_update", category["id"])
    assert updated.change_summary["changes"] == {
        "name": {"from": "Cameras", "to": "Digital Cameras"}
    }

    client.delete(f"{STAFF}/categories/{category['id']}", headers=h)
    (deleted,) = audits(db, "catalog.category_delete", category["id"])
    assert deleted.change_summary["name"] == "Digital Cameras"

    brand = create_brand(client, h, "Canon")
    client.patch(f"{STAFF}/brands/{brand['id']}", json={"is_active": False}, headers=h)
    client.delete(f"{STAFF}/brands/{brand['id']}", headers=h)
    for action in ("catalog.brand_create", "catalog.brand_update", "catalog.brand_delete"):
        (record,) = audits(db, action, brand["id"])
        assert record.actor_user_id == actor_id and record.entity_type == "brand"
    (brand_update,) = audits(db, "catalog.brand_update", brand["id"])
    assert brand_update.change_summary["changes"] == {"is_active": {"from": True, "to": False}}


def test_rejected_changes_write_no_catalogue_audit(client: TestClient, db: Session, admin_auth):
    h = admin_auth["headers"]
    category = create_category(client, h, "Drones")
    add_product(db, category["id"])
    client.delete(f"{STAFF}/categories/{category['id']}", headers=h)
    client.post(f"{STAFF}/categories", json={"name": "X", "slug": "drones"}, headers=h)
    db.expire_all()
    count = db.scalar(
        select(func.count(AuditRecord.id)).where(AuditRecord.action.like("catalog.%"))
    )
    assert count == 1  # only the create


def test_audit_failure_rolls_back_the_change(
    client: TestClient, db: Session, admin_auth: dict, monkeypatch
):
    def fail(*args, **kwargs):
        raise RuntimeError("simulated audit persistence failure")

    monkeypatch.setattr(AuditRepository, "create", staticmethod(fail))
    with pytest.raises(RuntimeError):
        client.post(
            f"{STAFF}/categories", json={"name": "Never Saved"}, headers=admin_auth["headers"]
        )
    db.expire_all()
    assert db.scalar(select(Category).where(Category.slug == "never-saved")) is None


# ---- delete: database guard behind the in-use checks ---------------------------------------
@pytest.mark.parametrize("kind", ["category", "brand"])
def test_foreign_key_violation_on_delete_is_reported_as_in_use_and_changes_nothing(
    client: TestClient, db: Session, admin_auth: dict, monkeypatch, kind: str
):
    # The in-use check misses the product, as a race could; PostgreSQL's ON DELETE RESTRICT key
    # refuses the DELETE (restrict_violation, SQLSTATE 23001). An ORM session.delete() would
    # instead have set the product's brand_id to NULL and succeeded.
    h = admin_auth["headers"]
    category = create_category(client, h, "Guarded")
    brand = create_brand(client, h, "Guarded Brand")
    product = add_product(db, category["id"], brand["id"])
    monkeypatch.setattr(catalog_admin, "_category_usage", lambda db, category_id: (0, 0))
    monkeypatch.setattr(catalog_admin, "_brand_usage", lambda db, brand_id: 0)
    target = category if kind == "category" else brand
    path = "categories" if kind == "category" else "brands"

    res = client.delete(f"{STAFF}/{path}/{target['id']}", headers=h)

    assert res.status_code == 409 and error_code(res) == f"{kind}_in_use"
    db.expire_all()
    stored = db.get(Product, product.id)
    assert stored is not None
    assert (stored.category_id, stored.brand_id) == (
        uuid.UUID(category["id"]),
        uuid.UUID(brand["id"]),
    )
    model = Category if kind == "category" else Brand
    assert db.get(model, uuid.UUID(target["id"])) is not None
    assert audits(db, f"catalog.{kind}_delete", target["id"]) == []


def test_no_action_foreign_key_violation_is_also_reported_as_in_use(
    client: TestClient, admin_auth: dict, monkeypatch
):
    category = create_category(client, admin_auth["headers"], "No Action")

    def fail(*args, **kwargs):
        raise IntegrityError("DELETE ...", {}, psycopg.errors.ForeignKeyViolation("simulated"))

    monkeypatch.setattr(catalog_admin, "_delete_row", fail)
    res = client.delete(f"{STAFF}/categories/{category['id']}", headers=admin_auth["headers"])
    assert res.status_code == 409 and error_code(res) == "category_in_use"


@pytest.mark.parametrize(
    "driver_error",
    [
        psycopg.errors.UniqueViolation("simulated unique violation"),
        psycopg.errors.NotNullViolation("simulated not-null violation"),
        RuntimeError("driver error without a SQLSTATE"),
    ],
    ids=["unique_violation", "not_null_violation", "no_sqlstate"],
)
@pytest.mark.parametrize("kind", ["category", "brand"])
def test_other_integrity_errors_on_delete_are_not_reported_as_in_use(
    client: TestClient, db: Session, admin_auth: dict, monkeypatch, kind: str, driver_error
):
    h = admin_auth["headers"]
    target = (
        create_category(client, h, "Unused") if kind == "category" else create_brand(client, h, "U")
    )

    def fail(*args, **kwargs):
        raise IntegrityError("DELETE ...", {}, driver_error)

    monkeypatch.setattr(catalog_admin, "_delete_row", fail)
    path = "categories" if kind == "category" else "brands"
    with pytest.raises(IntegrityError):
        client.delete(f"{STAFF}/{path}/{target['id']}", headers=h)
    db.expire_all()
    model = Category if kind == "category" else Brand
    assert db.get(model, uuid.UUID(target["id"])) is not None
    assert audits(db, f"catalog.{kind}_delete", target["id"]) == []


# ---- authorization ---------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["customer_auth"])
def test_other_roles_are_forbidden_and_nothing_changes(
    client: TestClient, db: Session, admin_auth: dict, who: str, request
):
    category = create_category(client, admin_auth["headers"], "Protected")
    brand = create_brand(
        client, admin_auth["headers"], "Protected Brand", category_ids=[category["id"]]
    )
    h = request.getfixturevalue(who)["headers"]
    attempts = [
        client.post(f"{STAFF}/categories", json={"name": "Nope"}, headers=h),
        client.patch(f"{STAFF}/categories/{category['id']}", json={"name": "Nope"}, headers=h),
        client.delete(f"{STAFF}/categories/{category['id']}", headers=h),
        client.post(f"{STAFF}/brands", json={"name": "Nope"}, headers=h),
        client.patch(f"{STAFF}/brands/{brand['id']}", json={"name": "Nope"}, headers=h),
        client.delete(f"{STAFF}/brands/{brand['id']}", headers=h),
    ]
    assert [r.status_code for r in attempts] == [403] * 6
    assert {error_code(r) for r in attempts} == {"permission_denied"}
    db.expire_all()
    assert db.scalar(select(func.count(Category.id))) == 1
    assert db.scalar(select(func.count(Brand.id))) == 1
    stored = db.get(Category, uuid.UUID(category["id"]))
    assert stored is not None and stored.name == "Protected"


def test_anonymous_requests_are_unauthorized(client: TestClient):
    res = client.post(f"{STAFF}/categories", json={"name": "Anon"})
    assert res.status_code == 401 and error_code(res) == "token_missing"
    assert client.delete(f"{STAFF}/brands/{uuid.uuid4()}").status_code == 401


# ---- request validation ------------------------------------------------------------------
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": None},
        {"slug": None},
        {"is_active": None},
        {"sort_order": None},
        {"name": "   "},
        {"name": "x" * 161},
        {"sort_order": 2**31},
        {"id": str(uuid.uuid4())},
        {"created_at": "2026-01-01T00:00:00Z"},
    ],
)
def test_invalid_category_updates_are_rejected(client: TestClient, admin_auth: dict, body):
    category = create_category(client, admin_auth["headers"], "Valid")
    res = client.patch(
        f"{STAFF}/categories/{category['id']}", json=body, headers=admin_auth["headers"]
    )
    assert res.status_code == 422 and error_code(res) == "validation_error"


def test_malformed_ids_are_validation_errors(client: TestClient, admin_auth: dict):
    h = admin_auth["headers"]
    assert (
        client.patch(f"{STAFF}/categories/not-a-uuid", json={"name": "X"}, headers=h).status_code
        == 422
    )
    assert client.delete(f"{STAFF}/brands/not-a-uuid", headers=h).status_code == 422


# ---- {staff_id:uuid} route converter ---------------------------------------------------------
def test_catalogue_routes_are_not_captured_by_staff_account_routes(
    client: TestClient, admin_auth: dict
):
    h = admin_auth["headers"]
    # Before the converter, these matched GET/PATCH /staff/{staff_id} and failed with 422.
    # GET /staff/categories is the staff category list (frontend phase 6).
    assert client.get(f"{STAFF}/categories", headers=h).status_code == 200
    assert client.patch(f"{STAFF}/brands", json={"name": "X"}, headers=h).status_code == 405
    # Staff-account URLs are unchanged.
    staff_id = admin_auth["user"].id
    assert client.get(f"{STAFF}/{staff_id}", headers=h).json()["role"] == "administrator"
    assert client.get(f"{STAFF}/{str(staff_id).upper()}", headers=h).status_code == 200
    assert client.get(f"{STAFF}/not-a-uuid", headers=h).status_code == 404
