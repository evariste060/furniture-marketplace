"""Catalogue facets and multi-brand filtering (frontend phase 2, approved 2026-10-27).

GET /catalog/facets takes the product list's filters and returns option counts for the listing's
filter panel: brands, price bands, availability and minimum rating. Each group's counts ignore
that group's own filter (ticking one brand still shows the other brands' counts) and apply all
the others, so a count is what the list would show if the customer picked that option.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import InventoryBalance, Product
from tests.support.catalog import force_status

STAFF = "/api/v1/staff"
PUBLIC = "/api/v1/catalog"


@pytest.fixture
def catalogue(client: TestClient, db: Session, admin_auth: dict) -> dict[str, str]:
    """Phones: Samsung A (150k, in stock, 4.5), Samsung B (450k + 1.2M variants, out of stock),
    Apple C (950k, in stock, 3.0); Laptops: Apple D (700k, in stock). Returns name -> id."""
    h = admin_auth["headers"]

    def post(path: str, body: dict) -> dict:
        res = client.post(f"{STAFF}{path}", json=body, headers=h)
        assert res.status_code == 201, res.text
        return res.json()

    phones = post("/categories", {"name": "Phones", "slug": "phones"})
    laptops = post("/categories", {"name": "Laptops", "slug": "laptops"})
    # A brand belongs to its main categories (ADR-012 decision 9).
    samsung = post(
        "/brands", {"name": "Samsung", "slug": "samsung", "category_ids": [phones["id"]]}
    )
    apple = post(
        "/brands",
        {"name": "Apple", "slug": "apple", "category_ids": [phones["id"], laptops["id"]]},
    )
    rows = (
        ("Samsung A", phones, samsung, [(150_000, 5)], Decimal("4.5")),
        ("Samsung B", phones, samsung, [(450_000, 0), (1_200_000, 0)], None),
        ("Apple C", phones, apple, [(950_000, 2)], Decimal("3.0")),
        ("Apple D", laptops, apple, [(700_000, 1)], None),
    )
    ids = {}
    for name, category, brand, variants, rating in rows:
        product = post(
            "/products", {"name": name, "category_id": category["id"], "brand_id": brand["id"]}
        )
        for price, stock in variants:
            variant = post(
                f"/products/{product['id']}/variants",
                {"sku": f"SKU-{uuid.uuid4().hex[:8]}", "name": f"V{price}", "price": price},
            )
            db.add(InventoryBalance(variant_id=uuid.UUID(variant["id"]), on_hand=stock))
        force_status(product["id"])
        if rating is not None:
            db.execute(
                update(Product)
                .where(Product.id == uuid.UUID(product["id"]))
                .values(rating_count=2, rating_average=rating, rating_5_count=1, rating_4_count=1)
                if rating == Decimal("4.5")
                else update(Product)
                .where(Product.id == uuid.UUID(product["id"]))
                .values(rating_count=1, rating_average=rating, rating_3_count=1)
            )
        ids[name] = product["id"]
    db.commit()
    return ids


def facets(client: TestClient, **params) -> dict:
    res = client.get(f"{PUBLIC}/facets", params=params)
    assert res.status_code == 200, res.text
    return res.json()


def names(client: TestClient, **params) -> list[str]:
    res = client.get(f"{PUBLIC}/products", params={"sort_by": "name", **params})
    assert res.status_code == 200, res.text
    return [p["name"] for p in res.json()["items"]]


def bands(body: dict) -> list[int]:
    return [band["count"] for band in body["price_bands"]]


def test_counts_for_the_whole_catalogue(client, catalogue):
    body = facets(client)
    assert body["total"] == 4
    assert body["brands"] == [
        {"slug": "apple", "name": "Apple", "count": 2},
        {"slug": "samsung", "name": "Samsung", "count": 2},
    ]
    assert [(b["min_price"], b["max_price"]) for b in body["price_bands"]] == [
        (None, 199_999),
        (200_000, 399_999),
        (400_000, 599_999),
        (600_000, 999_999),
        (1_000_000, None),
    ]
    # Samsung B has a variant in two bands, so it counts in both.
    assert bands(body) == [1, 0, 1, 2, 1]
    assert body["availability"] == {"in_stock": 3, "out_of_stock": 1}
    assert body["ratings"] == [
        {"min_rating": 4, "count": 1},
        {"min_rating": 3, "count": 2},
        {"min_rating": 2, "count": 2},
        {"min_rating": 1, "count": 2},
    ]


def test_each_group_ignores_its_own_filter_and_applies_the_others(client, catalogue):
    body = facets(client, category="phones", brand="samsung")
    assert body["total"] == 2
    # Brands: every phone brand, so the customer can add Apple.
    assert [(b["slug"], b["count"]) for b in body["brands"]] == [("apple", 1), ("samsung", 2)]
    assert bands(body) == [1, 0, 1, 0, 1]  # Samsung phones only
    assert body["availability"] == {"in_stock": 1, "out_of_stock": 1}

    body = facets(client, category="phones", in_stock="true")
    assert body["total"] == 2
    assert body["availability"] == {"in_stock": 2, "out_of_stock": 1}  # ignores in_stock
    assert [(b["slug"], b["count"]) for b in body["brands"]] == [("apple", 1), ("samsung", 1)]

    body = facets(client, min_rating=4)
    assert body["total"] == 1
    assert [r["count"] for r in body["ratings"]] == [1, 2, 2, 2]  # ignores min_rating
    assert [(b["slug"], b["count"]) for b in body["brands"]] == [("samsung", 1)]

    body = facets(client, min_price=600_000, max_price=999_999)
    assert body["total"] == 2
    assert bands(body) == [1, 0, 1, 2, 1]  # ignores the price filter
    assert body["availability"] == {"in_stock": 2, "out_of_stock": 0}


def test_counts_match_the_product_list(client, catalogue):
    cases = [
        {"brand": ["samsung", "apple"]},
        {"brand": "apple", "category": "phones"},
        {"max_price": 199_999},
        {"min_price": 1_000_000},
        {"in_stock": "false"},
        {"min_rating": 3},
        {"on_sale": "false", "q": "samsung"},
    ]
    for params in cases:
        assert facets(client, **params)["total"] == len(names(client, **params)), params


def test_several_brands_can_be_selected(client, catalogue):
    assert names(client, brand=["samsung", "apple"]) == [
        "Apple C",
        "Apple D",
        "Samsung A",
        "Samsung B",
    ]
    assert names(client, brand=["apple"], category="laptops") == ["Apple D"]
    assert names(client, brand="samsung") == ["Samsung A", "Samsung B"]
    assert names(client, brand=["nokia"]) == []
    too_many = [f"b{i}" for i in range(21)]
    assert client.get(f"{PUBLIC}/products", params={"brand": too_many}).status_code == 422
    assert client.get(f"{PUBLIC}/facets", params={"brand": too_many}).status_code == 422


def test_a_selected_brand_with_no_matches_is_still_listed(client, catalogue):
    """So the customer can untick it: Apple is selected but no Apple product is under 200k."""
    body = facets(client, brand="apple", max_price=199_999)
    assert body["total"] == 0
    assert [(b["slug"], b["count"]) for b in body["brands"]] == [("apple", 0), ("samsung", 1)]


def test_facets_validate_like_the_product_list(client, catalogue):
    for bad in (
        {"min_price": 10, "max_price": 5},
        {"min_rating": 6},
        {"q": "   "},
        {"in_stock": "maybe"},
    ):
        assert client.get(f"{PUBLIC}/facets", params=bad).status_code == 422, bad
    assert facets(client, category="nope")["total"] == 0


def test_category_counts_ignore_the_category_filter(client, catalogue, db):
    """Frontend phase 3 (2026-10-27): the brand page's Category group and the search chips.
    Menu order (sort_order), then name: both test categories have sort_order 0."""
    phones = {"slug": "phones", "name": "Phones"}
    laptops = {"slug": "laptops", "name": "Laptops"}
    assert facets(client)["categories"] == [{**laptops, "count": 1}, {**phones, "count": 3}]
    picked = facets(client, category="laptops")
    assert picked["total"] == 1
    assert picked["categories"] == [{**laptops, "count": 1}, {**phones, "count": 3}]
    assert facets(client, brand="samsung")["categories"] == [{**phones, "count": 2}]
    # A chosen category without matches stays listed with 0, so it can be cleared.
    assert facets(client, brand="samsung", category="laptops")["categories"] == [
        {**laptops, "count": 0},
        {**phones, "count": 2},
    ]
    assert facets(client, q="apple")["categories"] == [
        {**laptops, "count": 1},
        {**phones, "count": 1},
    ]
