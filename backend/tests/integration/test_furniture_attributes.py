"""Furniture attributes (ADR-014 decision 14, phase 6): the code-defined attributes and attribute
sets, the checks on known attributes in product specifications, and the material, color and
style filters with their facets. No schema change: attributes live in products.specifications.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.furniture import (
    ATTRIBUTES,
    TAXONOMY,
    TAXONOMY_SLUGS,
    attribute_set,
    specification_problems,
)
from app.models import InventoryBalance
from tests.support.catalog import force_status
from tests.support.sellers import default_seller, post_product

STAFF = "/api/v1/staff"
PUBLIC = "/api/v1/catalog"


# ---- the definitions ---------------------------------------------------------------------------
def test_the_taxonomy_has_unique_slugs_and_every_set_names_known_attributes():
    slugs = [m.slug for m in TAXONOMY] + [c.slug for m in TAXONOMY for c in m.children]
    assert len(slugs) == len(set(slugs)) == len(TAXONOMY_SLUGS)
    for slug in slugs:
        assert set(attribute_set(slug)) <= set(ATTRIBUTES)
    assert "seat_height_cm" in attribute_set("sofas", "living-room")
    assert "seat_height_cm" not in attribute_set("coffee-tables", "living-room")
    assert attribute_set("unknown") == attribute_set(None)


def test_known_attributes_are_checked_and_free_specifications_are_not():
    good = {
        "width_cm": 210,
        "depth_cm": 92.5,
        "material": "solid_wood",
        "color": "walnut",
        "assembly_required": False,
        "Fabric care": "Dry clean only",  # a free specification: any name, any text
    }
    assert specification_problems(good) == []
    problems = specification_problems(
        {"material": "Oak", "width_cm": "210", "height_cm": 0, "assembly_required": "no"}
    )
    assert len(problems) == 4
    assert specification_problems({"weight_kg": True}) != []  # a boolean is not a number


def test_the_attributes_endpoint_lists_definitions_and_sets(client: TestClient):
    res = client.get(f"{PUBLIC}/attributes")
    assert res.status_code == 200, res.text
    body = res.json()
    by_key = {a["key"]: a for a in body["attributes"]}
    assert by_key["material"]["kind"] == "choice" and by_key["material"]["filterable"] is True
    assert by_key["width_cm"] == {
        "key": "width_cm",
        "kind": "number",
        "unit": "cm",
        "choices": [],
        "filterable": False,
    }
    assert by_key["assembly_required"]["kind"] == "boolean"
    assert "seat_height_cm" in body["sets"]["sofas"]
    assert body["default_set"] == list(attribute_set(None))


# ---- products ----------------------------------------------------------------------------------
@pytest.fixture
def category(client: TestClient, admin_auth: dict) -> dict:
    res = client.post(
        f"{STAFF}/categories",
        json={"name": "Sofas", "slug": "sofas"},
        headers=admin_auth["headers"],
    )
    assert res.status_code == 201, res.text
    return res.json()


def test_a_seller_product_with_a_wrong_attribute_value_is_422(client, admin_auth, category):
    res = post_product(
        client,
        json={
            "name": "Oak sofa",
            "category_id": category["id"],
            "specifications": {"material": "oak wood", "width_cm": -5},
        },
        headers=admin_auth["headers"],
    )
    assert res.status_code == 422, res.text
    assert "material must be one of" in res.text and "width_cm must be a number" in res.text


def test_an_update_is_checked_too_and_free_specifications_still_work(client, admin_auth, category):
    made = post_product(
        client,
        json={
            "name": "Linen sofa",
            "category_id": category["id"],
            "specifications": {"material": "fabric", "Cushions": "Removable covers"},
        },
        headers=admin_auth["headers"],
    )
    assert made.status_code == 201, made.text
    seller = default_seller(client, admin_auth["headers"])
    path = f"/api/v1/seller/products/{made.json()['id']}"
    bad = client.patch(
        path, json={"specifications": {"style": "baroque"}}, headers=seller["headers"]
    )
    assert bad.status_code == 422, bad.text
    staff = client.patch(
        f"{STAFF}/products/{made.json()['id']}",
        json={"specifications": {"color": "purple"}},
        headers=admin_auth["headers"],
    )
    assert staff.status_code == 422, staff.text


# ---- filters and facets ------------------------------------------------------------------------
@pytest.fixture
def furniture(client: TestClient, db: Session, admin_auth: dict, category: dict) -> dict[str, str]:
    """Oak bench (solid wood, oak, rustic), Walnut sofa (solid wood, walnut, modern), Grey sofa
    (fabric, grey, modern), Plain stool (no attributes). Returns name -> id."""
    h = admin_auth["headers"]
    rows = (
        ("Oak bench", {"material": "solid_wood", "color": "oak", "style": "rustic"}),
        ("Walnut sofa", {"material": "solid_wood", "color": "walnut", "style": "modern"}),
        ("Grey sofa", {"material": "fabric", "color": "grey", "style": "modern"}),
        ("Plain stool", {"Legs": "Four"}),
    )
    ids = {}
    for name, specs in rows:
        made = post_product(
            client,
            json={"name": name, "category_id": category["id"], "specifications": specs},
            headers=h,
        )
        assert made.status_code == 201, made.text
        product = made.json()
        variant = client.post(
            f"{STAFF}/products/{product['id']}/variants",
            json={"sku": f"SKU-{uuid.uuid4().hex[:8]}", "name": "Std", "price": 100_000},
            headers=h,
        )
        assert variant.status_code == 201, variant.text
        db.add(InventoryBalance(variant_id=uuid.UUID(variant.json()["id"]), on_hand=3))
        force_status(product["id"])
        ids[name] = product["id"]
    db.commit()
    return ids


def names(client: TestClient, **params) -> list[str]:
    res = client.get(f"{PUBLIC}/products", params={"sort_by": "name", **params})
    assert res.status_code == 200, res.text
    return [p["name"] for p in res.json()["items"]]


def attribute_facets(client: TestClient, **params) -> dict[str, dict[str, int]]:
    res = client.get(f"{PUBLIC}/facets", params=params)
    assert res.status_code == 200, res.text
    return {
        g["key"]: {v["value"]: v["count"] for v in g["values"]} for g in res.json()["attributes"]
    }


def test_attribute_filters_match_any_code_of_a_key_and_every_key(client, furniture):
    assert names(client, material="solid_wood") == ["Oak bench", "Walnut sofa"]
    assert names(client, material=["solid_wood", "fabric"]) == [
        "Grey sofa",
        "Oak bench",
        "Walnut sofa",
    ]
    assert names(client, material="solid_wood", style="modern") == ["Walnut sofa"]
    assert names(client, color="white") == []


def test_an_unknown_code_is_422(client, furniture):
    res = client.get(f"{PUBLIC}/products", params={"material": "unobtainium"})
    assert res.status_code == 422, res.text
    assert client.get(f"{PUBLIC}/facets", params={"style": "Modern"}).status_code == 422


def test_each_attribute_facet_ignores_its_own_filter_and_applies_the_others(client, furniture):
    whole = attribute_facets(client)
    assert whole["material"] == {"solid_wood": 2, "fabric": 1}
    assert whole["style"] == {"rustic": 1, "modern": 2}
    picked = attribute_facets(client, material="solid_wood")
    assert picked["material"] == {"solid_wood": 2, "fabric": 1}  # still offers fabric
    assert picked["color"] == {"oak": 1, "walnut": 1}
    assert picked["style"] == {"rustic": 1, "modern": 1}
    # A chosen code without matches stays listed, so it can be unticked.
    assert attribute_facets(client, color="white")["color"] == {
        "oak": 1,
        "walnut": 1,
        "white": 0,
        "grey": 1,
    }


def test_codes_are_listed_in_the_attributes_own_order(client, furniture):
    res = client.get(f"{PUBLIC}/facets")
    material = next(g for g in res.json()["attributes"] if g["key"] == "material")
    order = ATTRIBUTES["material"].choices
    assert [v["value"] for v in material["values"]] == sorted(
        (v["value"] for v in material["values"]), key=order.index
    )
