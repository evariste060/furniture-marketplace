"""Module 10 — staff stock list GET /api/v1/inventory (TC-13, TC-14, TC-16; plan §7 Q9).

Runs on the disposable per-test PostgreSQL schema (tests/conftest.py). Reservation transitions
use their own sessions, as the checkout and payment services will.
"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.models import InventoryBalance, Product, ProductVariant
from app.services import inventory as inv
from tests.support.commerce import new_order, seed_sku, soon, wait_until_due

BASE = "/api/v1/inventory"
FIGURES = (
    "on_hand",
    "unavailable_quantity",
    "reserved_quantity",
    "committed_quantity",
    "available_quantity",
)


@pytest.fixture
def sf(pg_engine):
    return sessionmaker(bind=pg_engine, expire_on_commit=False)


def make(db: Session, *, on_hand: int | None = 10, threshold: int = 0, **overrides) -> str:
    variant = seed_sku(db, on_hand=on_hand, low_stock_threshold=threshold, **overrides)
    db.commit()
    return variant.sku


def variant_id(db: Session, sku: str):
    return db.query(ProductVariant.id).filter_by(sku=sku).scalar()


def reserve(sf, db: Session, sku: str, quantity: int, *, expires=None):
    with sf() as s:
        return inv.create_order_with_reservations(
            s, new_order({variant_id(db, sku): quantity}), expires_at=expires or soon()
        ).order.id


def listing(client: TestClient, headers: dict, **params) -> dict:
    res = client.get(BASE, params=params, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


def row(client: TestClient, headers: dict, sku: str) -> dict:
    (item,) = [i for i in listing(client, headers, q=sku, size=100)["items"] if i["sku"] == sku]
    return item


def figures(item: dict) -> tuple[int, ...]:
    return tuple(item[name] for name in FIGURES)


# ---- figures ---------------------------------------------------------------------------------
def test_each_sku_is_one_row_with_every_stock_figure(client, db, sf, admin_auth):
    h = admin_auth["headers"]
    sku = make(db, on_hand=10, threshold=3)
    db.execute(
        update(InventoryBalance)
        .where(InventoryBalance.variant_id == variant_id(db, sku))
        .values(unavailable_quantity=1)
    )
    db.commit()
    reserve(sf, db, sku, 2)  # stays active
    paid = reserve(sf, db, sku, 3)
    with sf() as s:
        inv.commit_order_reservations(s, paid)
    data = listing(client, h)
    assert data["total"] == 1 and len(data["items"]) == 1  # two holds, still one row
    item = data["items"][0]
    assert item["sku"] == sku
    assert figures(item) == (10, 1, 2, 3, 4)
    assert (item["low_stock_threshold"], item["is_low_stock"]) == (3, False)
    assert item["has_inventory_record"] is True and item["is_sellable"] is True
    assert item["variant_name"] == "Test variant" and item["product_name"].startswith("Test phone")
    assert set(item) == {
        "sku",
        "variant_id",
        "is_sellable",
        "has_inventory_record",
        *FIGURES,
        "product_id",
        "product_name",
        "variant_name",
        "low_stock_threshold",
        "is_low_stock",
    }


def test_the_list_and_the_single_sku_read_always_agree(client, db, sf, admin_auth):
    h = admin_auth["headers"]
    skus = [make(db, on_hand=n, threshold=2) for n in (0, 1, 5, 8)] + [make(db, on_hand=None)]
    reserve(sf, db, skus[2], 4)
    committed = reserve(sf, db, skus[3], 6)
    with sf() as s:
        inv.commit_order_reservations(s, committed)
    for item in listing(client, h, size=100)["items"]:
        single = client.get(f"{BASE}/{item['sku']}", headers=h).json()
        assert {k: item[k] for k in single} == single
        with sf() as s:
            assert figures(item) == tuple(
                inv.availability(s, variant_id(db, item["sku"]))[n] for n in FIGURES
            )


def test_a_sku_without_an_inventory_record_has_zeros(client, db, admin_auth):
    sku = make(db, on_hand=None, threshold=1)
    item = row(client, admin_auth["headers"], sku)
    assert figures(item) == (0, 0, 0, 0, 0) and item["has_inventory_record"] is False
    assert item["is_low_stock"] is True  # 0 available <= threshold 1


def test_inactive_variants_are_listed_as_not_sellable(client, db, admin_auth):
    sku = make(db, is_active=False)
    assert row(client, admin_auth["headers"], sku)["is_sellable"] is False


# ---- reservation lifecycle -------------------------------------------------------------------
def test_figures_follow_reservation_release_commit_and_dispatch(client, db, sf, admin_auth):
    h = admin_auth["headers"]
    sku = make(db, on_hand=10)
    first = reserve(sf, db, sku, 2)
    assert figures(row(client, h, sku)) == (10, 0, 2, 0, 8)
    with sf() as s:
        inv.release_order_reservations(s, first, reason="cancelled")
    assert figures(row(client, h, sku)) == (10, 0, 0, 0, 10)
    second = reserve(sf, db, sku, 4)
    with sf() as s:
        inv.commit_order_reservations(s, second)
    assert figures(row(client, h, sku)) == (10, 0, 0, 4, 6)
    with sf() as s:
        inv.dispatch_order_inventory(s, second)
    assert figures(row(client, h, sku)) == (6, 0, 0, 0, 6)


def test_an_overdue_hold_counts_until_the_expiry_job_releases_it(client, db, sf, admin_auth):
    h = admin_auth["headers"]
    sku = make(db, on_hand=5, threshold=3)
    with sf() as s:
        now = s.scalar(text("SELECT clock_timestamp()"))
    reserve(sf, db, sku, 3, expires=now + timedelta(seconds=1))
    wait_until_due()
    overdue = row(client, h, sku)
    assert figures(overdue) == (5, 0, 3, 0, 2) and overdue["is_low_stock"] is True
    with sf() as s:
        assert inv.expire_due_reservations(s).orders == 1
    released = row(client, h, sku)
    assert figures(released) == (5, 0, 0, 0, 5) and released["is_low_stock"] is False


def test_adjustments_show_in_the_list(client, db, admin_auth):
    h = admin_auth["headers"]
    sku = make(db, on_hand=2)
    res = client.post(
        f"{BASE}/{sku}/adjustments",
        json={"reason": "receipt", "quantity_delta": 5},
        headers={**h, "Idempotency-Key": "list-receipt-0001"},
    )
    assert res.status_code == 201, res.text
    assert row(client, h, sku)["on_hand"] == 7


# ---- low stock -------------------------------------------------------------------------------
def test_low_stock_is_available_at_or_below_a_positive_threshold(client, db, sf, admin_auth):
    h = admin_auth["headers"]
    cases = {
        "at": make(db, on_hand=5, threshold=5),  # 5 <= 5: low
        "above": make(db, on_hand=6, threshold=5),  # not low
        "zero_threshold_empty": make(db, on_hand=0, threshold=0),  # threshold 0: never low
        "empty": make(db, on_hand=0, threshold=2),  # 0 <= 2: low
        "reserved_down": make(db, on_hand=9, threshold=4),  # 9 - 5 reserved = 4: low
        "on_hand_high_but_held": make(db, on_hand=10, threshold=3),  # 10 - 8 = 2: low
    }
    reserve(sf, db, cases["reserved_down"], 5)
    paid = reserve(sf, db, cases["on_hand_high_but_held"], 8)
    with sf() as s:
        inv.commit_order_reservations(s, paid)
    low = listing(client, h, low_stock="true", size=100)
    expected_low = sorted(
        cases[k] for k in ("at", "empty", "reserved_down", "on_hand_high_but_held")
    )
    assert [i["sku"] for i in low["items"]] == expected_low and low["total"] == 4
    assert all(i["is_low_stock"] for i in low["items"])
    others = listing(client, h, low_stock="false", size=100)
    assert [i["sku"] for i in others["items"]] == sorted(
        [cases["above"], cases["zero_threshold_empty"]]
    )
    assert not any(i["is_low_stock"] for i in others["items"])
    everything = listing(client, h, size=100)
    assert everything["total"] == low["total"] + others["total"] == 6


# ---- search, order and pages -----------------------------------------------------------------
def test_q_matches_sku_variant_and_product_names_case_insensitively(client, db, admin_auth):
    h = admin_auth["headers"]
    sku = make(db, threshold=20)
    other = make(db)
    product_name = (
        db.query(Product.name).join(ProductVariant).filter(ProductVariant.sku == sku).scalar()
    )
    db.execute(update(ProductVariant).where(ProductVariant.sku == sku).values(name="Midnight 100%"))
    db.commit()
    for term in (sku.lower(), sku[-6:], "MIDNIGHT", "100%", product_name.upper()):
        assert [i["sku"] for i in listing(client, h, q=term)["items"]] == [sku], term
    assert listing(client, h, q="%")["items"][0]["sku"] == sku  # literal %, not a wildcard
    assert listing(client, h, q="_")["total"] == 0
    assert other not in [i["sku"] for i in listing(client, h, q="midnight")["items"]]
    assert [i["sku"] for i in listing(client, h, q="midnight", low_stock="true")["items"]] == [sku]
    assert listing(client, h, q="midnight", low_stock="false")["total"] == 0


def test_rows_are_ordered_by_sku_and_pages_are_stable(client, db, admin_auth):
    h = admin_auth["headers"]
    skus = sorted(make(db) for _ in range(5))
    pages = [listing(client, h, page=n, size=2) for n in (1, 2, 3, 4)]
    assert [i["sku"] for p in pages for i in p["items"]] == skus
    assert [len(p["items"]) for p in pages] == [2, 2, 1, 0]
    assert {p["total"] for p in pages} == {5}
    assert pages[3] == {"items": [], "total": 5, "page": 4, "size": 2}


def test_an_empty_list_is_an_empty_page(client, admin_auth):
    assert listing(client, admin_auth["headers"]) == {
        "items": [],
        "total": 0,
        "page": 1,
        "size": 20,
    }


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"size": 0},
        {"size": 101},
        {"page": "x"},
        {"low_stock": "maybe"},
        {"q": "   "},
        {"q": ""},
        {"q": "x" * 161},
    ],
)
def test_invalid_parameters_are_422(client, admin_auth, params):
    res = client.get(BASE, params=params, headers=admin_auth["headers"])
    assert res.status_code == 422 and res.json()["error"]["code"] == "validation_error"


# ---- authorization ---------------------------------------------------------------------------
def test_the_list_follows_the_inventory_read_matrix(client, db, customer_auth, admin_auth):
    make(db)
    expected = {
        "administrator": (admin_auth, 200),
        "customer": (customer_auth, 403),
    }
    for role, (who, status) in expected.items():
        res = client.get(BASE, headers=who["headers"])
        assert res.status_code == status, role
        if status == 403:
            assert res.json()["error"]["code"] == "permission_denied"
    anonymous = client.get(BASE)
    assert anonymous.status_code == 401 and anonymous.json()["error"]["code"] == "token_missing"


# ---- query count -----------------------------------------------------------------------------
def test_the_list_runs_a_fixed_number_of_queries_whatever_the_page_size(
    client, db, sf, pg_engine, admin_auth
):
    h = admin_auth["headers"]
    skus = [make(db, threshold=1) for _ in range(30)]
    reserve(sf, db, skus[0], 1)
    statements: list[str] = []

    def count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    def stock_queries(size: int) -> list[str]:
        statements.clear()
        assert len(listing(client, h, size=size)["items"]) == size
        return [s for s in statements if "inventory_balances" in s or "product_variants" in s]

    listing(client, h, size=1)  # warm-up: the first request also refreshes the session row
    event.listen(pg_engine, "before_cursor_execute", count)
    try:
        small, large = stock_queries(2), stock_queries(30)
        total_small = len(statements)
        stock_queries(2)
        assert len(statements) == total_small  # stable once the session is fresh
    finally:
        event.remove(pg_engine, "before_cursor_execute", count)
    assert len(small) == len(large) == 2  # one count and one page, never one query per SKU
