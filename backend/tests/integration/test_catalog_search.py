"""Module 9 — catalogue full-text search and sorting (TC-02, TC-03; plan §7 Q5).

Runs on the disposable per-test PostgreSQL schema migrated to head (tests/conftest.py), so the
search_vector column, its triggers and the GIN index are the real ones.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Brand, Category, InventoryBalance, Product, ProductVariant
from tests.support.sellers import new_store

URL = "/api/v1/catalog/products"
T0 = datetime(2026, 10, 1, tzinfo=UTC)


def add_product(
    db: Session,
    category: Category,
    name: str,
    *,
    model: str | None = None,
    brand: Brand | None = None,
    prices: tuple[int, ...] = (),
    inactive_prices: tuple[int, ...] = (),
    created: datetime | None = None,
    status: str = "active",
    stock: int = 0,
) -> Product:
    product = Product(
        store=new_store(),
        name=name,
        slug=f"p-{uuid4().hex}",
        model=model,
        brand=brand,
        category=category,
        status=status,
    )
    if created is not None:
        product.created_at = created
    for price in prices:
        variant = ProductVariant(sku=f"S-{uuid4().hex}", name=f"V{price}", price=price)
        if stock:
            variant.inventory = InventoryBalance(on_hand=stock, unavailable_quantity=0)
        product.variants.append(variant)
    for price in inactive_prices:
        product.variants.append(
            ProductVariant(sku=f"S-{uuid4().hex}", name=f"Off{price}", price=price, is_active=False)
        )
    db.add(product)
    return product


@pytest.fixture
def shop(db: Session) -> dict:
    phones = Category(name="Phones", slug="phones")
    laptops = Category(name="Laptops", slug="laptops")
    apple = Brand(name="Apple", slug="apple")
    samsung = Brand(name="Samsung", slug="samsung")
    db.add_all([phones, laptops, apple, samsung])
    items = {
        "iphone": add_product(
            db,
            phones,
            "iPhone 15 Pro",
            model="A3102",
            brand=apple,
            prices=(1_500_000,),
            created=T0,
            stock=3,
        ),
        "galaxy": add_product(
            db,
            phones,
            "Galaxy S24",
            model="SM-S921B",
            brand=samsung,
            prices=(1_200_000, 900_000),
            created=T0 + timedelta(days=2),
            stock=5,
        ),
        "gx10": add_product(
            db,
            laptops,
            "ProBook",
            model="GX-10",
            brand=samsung,
            prices=(800_000,),
            inactive_prices=(1,),
            created=T0 + timedelta(days=1),
        ),
        "gx100": add_product(
            db,
            laptops,
            "ProBook Max",
            model="GX-100",
            prices=(950_000,),
            created=T0 + timedelta(days=3),
        ),
        "case": add_product(
            db, phones, "Samsung phone case", prices=(15_000,), created=T0 + timedelta(days=4)
        ),
        "draft": add_product(db, phones, "iPhone prototype", brand=apple, status="draft"),
    }
    db.commit()
    return {k: v.slug for k, v in items.items()} | {"phones": "phones", "samsung": "samsung"}


def slugs(client: TestClient, **params) -> list[str]:
    res = client.get(URL, params=params)
    assert res.status_code == 200, res.text
    return [item["slug"] for item in res.json()["items"]]


def vector(db: Session, slug: str) -> str:
    return db.execute(
        text("SELECT search_vector::text FROM products WHERE slug = :s"), {"s": slug}
    ).scalar_one()


# ---- matching --------------------------------------------------------------------------------
def test_name_brand_and_model_match(client, shop):
    assert slugs(client, q="iphone") == [shop["iphone"]]  # the draft product stays hidden
    assert set(slugs(client, q="apple")) == {shop["iphone"]}
    assert slugs(client, q="A3102") == [shop["iphone"]]
    assert set(slugs(client, q="samsung")) == {shop["galaxy"], shop["gx10"], shop["case"]}


def test_every_word_matches_as_a_prefix(client, shop):
    assert slugs(client, q="iph") == [shop["iphone"]]
    assert slugs(client, q="phon") == [shop["case"]]  # 'phone' in the case; not inside 'iPhone'
    assert set(slugs(client, q="sams")) == {shop["galaxy"], shop["gx10"], shop["case"]}
    assert slugs(client, q="galaxy s2") == [shop["galaxy"]]


@pytest.mark.parametrize("term", ["GX-10", "gx-1", "gx10", "GX 10", "gx 1", "gx1"])
def test_model_numbers_match_with_or_without_punctuation(client, shop, term):
    assert set(slugs(client, q=term)) == {shop["gx10"], shop["gx100"]}


def test_a_full_model_number_matches_only_longer_models_that_extend_it(client, shop):
    assert slugs(client, q="GX-100") == [shop["gx100"]]
    assert slugs(client, q="SM-S921B") == [shop["galaxy"]]
    assert slugs(client, q="s921") == [shop["galaxy"]]


def test_web_search_syntax(client, shop):
    assert set(slugs(client, q="probook")) == {shop["gx10"], shop["gx100"]}
    assert slugs(client, q="probook -max") == [shop["gx10"]]
    assert set(slugs(client, q="iphone or galaxy")) == {shop["iphone"], shop["galaxy"]}
    assert slugs(client, q='"probook max"') == [shop["gx100"]]
    assert slugs(client, q='"max probook"') == []  # a phrase keeps its word order


def test_words_must_all_match(client, shop):
    assert slugs(client, q="samsung probook") == [shop["gx10"]]
    assert slugs(client, q="apple probook") == []


@pytest.mark.parametrize("term", ["%", "_", "!!", "'", "--", "\\", "&|:*"])
def test_punctuation_only_matches_nothing(client, shop, term):
    res = client.get(URL, params={"q": term})
    assert res.status_code == 200
    assert res.json() == {"items": [], "total": 0, "page": 1, "size": 20}


@pytest.mark.parametrize(
    "term", ["iphone' OR '1'='1", "'; DROP TABLE products; --", "a:* & !b", "x <-> y"]
)
def test_query_syntax_in_input_is_treated_as_words(client, db, shop, term):
    res = client.get(URL, params={"q": term})
    assert res.status_code == 200
    assert db.execute(text("SELECT count(*) FROM products")).scalar_one() == 6


def test_no_match_returns_200_and_an_empty_page(client, shop):
    res = client.get(URL, params={"q": "no-such-device", "page": 2, "size": 5})
    assert res.status_code == 200
    assert res.json() == {"items": [], "total": 0, "page": 2, "size": 5}


@pytest.mark.parametrize(
    "params",
    [{"q": "   "}, {"q": ""}, {"q": "x" * 161}, {"sort_by": "relevance"}, {"sort_direction": "up"}],
)
def test_invalid_queries_and_sorts_are_422(client, shop, params):
    res = client.get(URL, params=params)
    assert res.status_code == 422 and res.json()["error"]["code"] == "validation_error"


# ---- ranking and sorting ---------------------------------------------------------------------
def test_search_orders_by_relevance_then_name_then_id(client, db, shop):
    # "samsung" is in the case's name (weight A) but only the brand of the others (weight C),
    # so the case ranks first; the two equal brand matches follow by name.
    assert slugs(client, q="samsung") == [shop["case"], shop["galaxy"], shop["gx10"]]
    ranks = db.execute(
        text(
            "SELECT slug, ts_rank(search_vector, to_tsquery('simple', 'samsung:*')) "
            "FROM products WHERE slug = ANY(:s)"
        ),
        {"s": [shop["case"], shop["galaxy"], shop["gx10"]]},
    ).all()
    rank = dict(ranks)
    assert rank[shop["case"]] > rank[shop["galaxy"]] == rank[shop["gx10"]]


def test_an_explicit_sort_overrides_relevance(client, shop):
    by_price = slugs(client, q="samsung", sort_by="price")
    assert by_price == [shop["case"], shop["gx10"], shop["galaxy"]]


def test_price_sort_uses_the_lowest_active_variant(client, shop):
    ascending = slugs(client, sort_by="price")
    # Galaxy's cheapest active variant is 900,000; ProBook's inactive 1 RWF variant is ignored;
    # the draft is hidden.
    assert ascending == [shop["case"], shop["gx10"], shop["galaxy"], shop["gx100"], shop["iphone"]]
    descending = slugs(client, sort_by="price", sort_direction="desc")
    assert descending == list(reversed(ascending))


def test_products_without_an_active_variant_come_last_in_both_directions(client, db, shop):
    phones = db.query(Category).filter_by(slug="phones").one()
    lonely = add_product(db, phones, "No variants yet", inactive_prices=(5,))
    db.commit()
    assert slugs(client, sort_by="price")[-1] == lonely.slug
    assert slugs(client, sort_by="price", sort_direction="desc")[-1] == lonely.slug


def test_newest_sort_defaults_to_newest_first(client, shop):
    newest = slugs(client, sort_by="newest")
    assert newest == [shop["case"], shop["gx100"], shop["galaxy"], shop["gx10"], shop["iphone"]]
    assert slugs(client, sort_by="newest", sort_direction="asc") == list(reversed(newest))


def test_name_is_the_default_without_a_search(client, shop):
    names = slugs(client)
    assert names == [shop["galaxy"], shop["iphone"], shop["gx10"], shop["gx100"], shop["case"]]


@pytest.mark.parametrize(
    "params",
    [
        {"sort_by": "name"},
        {"sort_by": "price"},
        {"sort_by": "newest"},
        {"q": "probook"},
        {"sort_by": "price", "sort_direction": "desc"},
    ],
)
def test_equal_sort_values_page_deterministically_by_id(client, db, params):
    category = Category(name="Same", slug="same")
    twins = [add_product(db, category, "ProBook twin", prices=(500,), created=T0) for _ in range(5)]
    db.commit()
    expected = sorted(p.slug for p in twins)  # same name, price, time and rank
    by_id = [p.slug for p in sorted(twins, key=lambda p: str(p.id))]
    pages = [slugs(client, page=n, size=2, category="same", **params) for n in (1, 2, 3)]
    assert sum(pages, []) == by_id and sorted(sum(pages, [])) == expected
    assert [len(p) for p in pages] == [2, 2, 1]


def test_search_combines_with_every_filter(client, shop):
    params = {
        "q": "samsung",
        "category": "phones",
        "brand": "samsung",
        "min_price": 500_000,
        "max_price": 1_000_000,
        "in_stock": "true",
    }
    res = client.get(URL, params=params)
    assert res.status_code == 200
    assert res.json()["total"] == 1 and [i["slug"] for i in res.json()["items"]] == [shop["galaxy"]]
    assert slugs(client, q="samsung", category="laptops") == [shop["gx10"]]
    assert slugs(client, q="samsung", in_stock="false", sort_by="price") == [
        shop["case"],
        shop["gx10"],
    ]


# ---- triggers and index ----------------------------------------------------------------------
def test_insert_sets_the_vector_with_weights(db, shop):
    # Name "ProBook" (A); model "GX-10" (B) as written plus "GX 10" and "GX10"; brand (C).
    assert vector(db, shop["gx10"]) == (
        "'-10':3B '10':5B 'gx':2B,4B 'gx10':6B 'probook':1A 'samsung':7C"
    )
    # Plain words are indexed once, so a quoted phrase keeps its order.
    assert vector(db, shop["iphone"]) == "'15':2A 'a3102':4B 'apple':5C 'iphone':1A 'pro':3A"


def test_product_changes_update_the_vector(client, db, shop):
    db.execute(
        text("UPDATE products SET name = 'Zenbook', model = 'UX-5' WHERE slug = :s"),
        {"s": shop["gx100"]},
    )
    db.commit()
    assert slugs(client, q="zenbook") == [shop["gx100"]]
    assert slugs(client, q="ux5") == [shop["gx100"]]
    assert shop["gx100"] not in slugs(client, q="probook")


def test_changing_the_brand_of_a_product_updates_its_vector(client, db, shop):
    db.execute(
        text(
            "UPDATE products SET brand_id = (SELECT id FROM brands WHERE slug = 'apple') "
            "WHERE slug = :s"
        ),
        {"s": shop["gx100"]},
    )
    db.commit()
    assert set(slugs(client, q="apple")) == {shop["iphone"], shop["gx100"]}
    db.execute(text("UPDATE products SET brand_id = NULL WHERE slug = :s"), {"s": shop["gx100"]})
    db.commit()
    assert slugs(client, q="apple") == [shop["iphone"]]


def test_renaming_a_brand_updates_only_its_products(client, db, shop):
    before_other = vector(db, shop["iphone"])
    db.execute(text("UPDATE brands SET name = 'Hanwha' WHERE slug = 'samsung'"))
    db.commit()
    assert set(slugs(client, q="hanwha")) == {shop["galaxy"], shop["gx10"]}
    assert slugs(client, q="samsung") == [shop["case"]]  # only its own name still says Samsung
    assert vector(db, shop["iphone"]) == before_other


def test_renaming_a_brand_through_the_staff_api_updates_search(client, db, shop, admin_auth):
    brand_id = db.execute(text("SELECT id FROM brands WHERE slug = 'apple'")).scalar_one()
    res = client.patch(
        f"/api/v1/staff/brands/{brand_id}", json={"name": "Pomme"}, headers=admin_auth["headers"]
    )
    assert res.status_code == 200, res.text
    assert slugs(client, q="pomme") == [shop["iphone"]]


def test_the_vector_cannot_be_overwritten(db, shop):
    db.execute(
        text("UPDATE products SET search_vector = ''::tsvector WHERE slug = :s"),
        {"s": shop["iphone"]},
    )
    db.commit()
    assert "'iphone'" in vector(db, shop["iphone"])


def test_the_gin_index_exists_and_serves_the_search(db, shop):
    indexdef = db.execute(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE indexname = 'ix_products_search_vector' AND schemaname = current_schema()"
        )
    ).scalar_one()
    assert "USING gin (search_vector)" in indexdef
    db.execute(text("SET LOCAL enable_seqscan = off"))
    plan = "\n".join(
        row[0]
        for row in db.execute(
            text(
                "EXPLAIN SELECT id FROM products WHERE search_vector @@ "
                "to_tsquery('simple', 'gx:*')"
            )
        )
    )
    db.rollback()
    assert "ix_products_search_vector" in plan
