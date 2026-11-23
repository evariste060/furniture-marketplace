"""Reviews part 1 (module 20, scope change SC-01 approved 2026-10-27): the review tables, the
product rating totals on catalogue responses, the min_rating filter and the top_rated sort.

Until part 2 (submission and moderation) exists, the totals are written directly, as the review
service will write them when it approves or rejects a review.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Product, ProductReview, ReviewToken
from tests.support.catalog import force_status
from tests.support.commerce import new_order, seed_sku
from tests.support.sellers import post_product

# SC-06: the staff routes for orders, payments, stock and catalogue editing used here are held by
# no role in V1; these tests grant them to the administrator (tests/conftest.py).
pytestmark = pytest.mark.usefixtures("store_operations_granted")

STAFF = "/api/v1/staff"
PUBLIC = "/api/v1/catalog"
NO_RATING = {"average": None, "count": 0}


@pytest.fixture
def category(client: TestClient, admin_auth: dict) -> dict:
    res = client.post(
        f"{STAFF}/categories",
        json={"name": "Phones", "slug": "phones"},
        headers=admin_auth["headers"],
    )
    assert res.status_code == 201, res.text
    return res.json()


def make_product(client: TestClient, admin_auth: dict, category: dict, name: str) -> dict:
    h = admin_auth["headers"]
    res = post_product(client, json={"name": name, "category_id": category["id"]}, headers=h)
    assert res.status_code == 201, res.text
    product = res.json()
    variant = client.post(
        f"{STAFF}/products/{product['id']}/variants",
        json={"sku": f"SKU-{uuid.uuid4().hex[:8]}", "name": "Std", "price": 1000},
        headers=h,
    )
    assert variant.status_code == 201, variant.text
    force_status(product["id"])
    return product


def set_totals(db: Session, product_id: str, distribution: dict[int, int]) -> None:
    """What the review service will store: approved reviews per star rating."""
    count = sum(distribution.values())
    average = (
        Decimal(sum(s * n for s, n in distribution.items()) / count).quantize(Decimal("0.1"))
        if count
        else None
    )
    db.execute(
        update(Product)
        .where(Product.id == uuid.UUID(product_id))
        .values(
            rating_count=count,
            rating_average=average,
            **{f"rating_{s}_count": distribution.get(s, 0) for s in range(1, 6)},
        )
    )
    db.commit()


def names(client: TestClient, **params) -> list[str]:
    res = client.get(f"{PUBLIC}/products", params=params)
    assert res.status_code == 200, res.text
    return [p["name"] for p in res.json()["items"]]


def test_products_without_reviews_show_the_no_rating_state(client, admin_auth, category):
    product = make_product(client, admin_auth, category, "Galaxy A55")
    (summary,) = client.get(f"{PUBLIC}/products").json()["items"]
    assert summary["rating"] == NO_RATING
    detail = client.get(f"{PUBLIC}/products/{product['slug']}").json()
    assert detail["rating"] == {
        **NO_RATING,
        "distribution": [{"stars": s, "count": 0} for s in (5, 4, 3, 2, 1)],
    }


def test_rating_totals_appear_on_summaries_and_the_detail(client, db, admin_auth, category):
    product = make_product(client, admin_auth, category, "Galaxy A55")
    set_totals(db, product["id"], {5: 3, 4: 1, 2: 1})
    (summary,) = client.get(f"{PUBLIC}/products").json()["items"]
    assert summary["rating"] == {"average": 4.2, "count": 5}  # 21 / 5
    assert "distribution" not in summary["rating"]
    detail = client.get(f"{PUBLIC}/products/{product['slug']}").json()
    assert detail["rating"]["distribution"] == [
        {"stars": 5, "count": 3},
        {"stars": 4, "count": 1},
        {"stars": 3, "count": 0},
        {"stars": 2, "count": 1},
        {"stars": 1, "count": 0},
    ]


def test_min_rating_and_top_rated(client, db, admin_auth, category):
    ids = {
        name: make_product(client, admin_auth, category, name)["id"]
        for name in ("A unreviewed", "B 4.5 of 2", "C 4.5 of 10", "D 3.0", "E 5.0")
    }
    set_totals(db, ids["B 4.5 of 2"], {5: 1, 4: 1})
    set_totals(db, ids["C 4.5 of 10"], {5: 5, 4: 5})
    set_totals(db, ids["D 3.0"], {3: 4})
    set_totals(db, ids["E 5.0"], {5: 1})

    assert names(client, sort_by="top_rated") == [
        "E 5.0",
        "C 4.5 of 10",  # same average: more reviews first
        "B 4.5 of 2",
        "D 3.0",
        "A unreviewed",  # no reviews: last
    ]
    assert names(client, sort_by="top_rated", sort_direction="asc") == [
        "D 3.0",
        "B 4.5 of 2",
        "C 4.5 of 10",
        "E 5.0",
        "A unreviewed",  # still last
    ]
    assert names(client, min_rating=4, sort_by="top_rated") == [
        "E 5.0",
        "C 4.5 of 10",
        "B 4.5 of 2",
    ]
    assert names(client, min_rating=5) == ["E 5.0"]
    assert names(client, min_rating=1, sort_by="name") == [
        "B 4.5 of 2",
        "C 4.5 of 10",
        "D 3.0",
        "E 5.0",
    ]
    for bad in ({"min_rating": 0}, {"min_rating": 6}, {"min_rating": "x"}, {"sort_by": "rating"}):
        assert client.get(f"{PUBLIC}/products", params=bad).status_code == 422, bad


@pytest.mark.parametrize(
    "values",
    [
        {"rating_count": 1},  # does not match the distribution
        {"rating_count": 1, "rating_5_count": 1},  # average missing
        {"rating_average": Decimal("4.0")},  # average without reviews
        {"rating_count": 1, "rating_5_count": 1, "rating_average": Decimal("0.5")},
        {"rating_count": -1, "rating_1_count": -1, "rating_average": Decimal("1.0")},
    ],
)
def test_the_database_keeps_rating_totals_consistent(client, db, admin_auth, category, values):
    product = make_product(client, admin_auth, category, "Galaxy A55")
    with pytest.raises(IntegrityError):
        db.execute(update(Product).where(Product.id == uuid.UUID(product["id"])).values(**values))
        db.flush()
    db.rollback()


def _delivered_item(db: Session):
    variant = seed_sku(db, on_hand=5)
    order = new_order({variant.id: 1})
    db.add(order)
    db.commit()
    return variant.product_id, order.items[0].id


def _review(product_id, item_id, **extra) -> ProductReview:
    return ProductReview(
        product_id=product_id,
        order_item_id=item_id,
        rating=extra.pop("rating", 5),
        author_name="Aline U.",
        **extra,
    )


def test_one_review_per_order_item_with_a_rating_from_1_to_5(db):
    product_id, item_id = _delivered_item(db)
    for bad in (
        {"rating": 0},
        {"rating": 6},
        {"status": "published"},
        {"status": "approved"},  # moderated without moderated_at
        {"moderated_at": datetime.now(UTC)},  # pending but moderated
    ):
        db.add(_review(product_id, item_id, **bad))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    db.add(_review(product_id, item_id))
    db.commit()
    db.add(_review(product_id, item_id, rating=1))
    with pytest.raises(IntegrityError):  # one review per order item
        db.flush()
    db.rollback()


def test_one_review_link_per_order_item_and_unique_hashes(db):
    _, item_id = _delivered_item(db)
    _, other_item = _delivered_item(db)
    expires = datetime.now(UTC) + timedelta(days=90)
    db.add(ReviewToken(order_item_id=item_id, token_hash="a" * 64, expires_at=expires))
    db.commit()
    for item, token_hash in ((item_id, "b" * 64), (other_item, "a" * 64)):
        db.add(ReviewToken(order_item_id=item, token_hash=token_hash, expires_at=expires))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
