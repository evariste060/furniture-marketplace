"""Module 18 — staff reports (PR-13; UAT scenario 7; plan §5 "18 — reports"; §7 Q25).

Disposable per-test PostgreSQL schema (tests/conftest.py). Orders are made through the real
checkout, payment and fulfilment flows; the boundary tests then set the payment-success instant
of their sales to fixed times, so no test depends on the wall clock or on how long it runs.
"""

import io
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from openpyxl import load_workbook
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.kigali_time import KIGALI
from app.models import Order, Product, ProductVariant
from app.models.commerce import PaymentAttempt
from app.services.report_xlsx import (
    SALES_HEADERS,
    STOCK_HEADERS,
    TOP_PRODUCTS_HEADERS,
    XLSX_CONTENT_TYPE,
)
from tests.integration.test_cart_api import add, code, guest, sku
from tests.integration.test_checkout_api import INLINE, checkout
from tests.integration.test_payments_api import (  # noqa: F401
    delivery,
    event,
    initiate,
    webhook,
)
from tests.support.commerce import hold_expiry, stock_clock_at
from tests.support.seller_orders import step

REPORTS = "/api/v1/staff/reports"
INVENTORY = "/api/v1/inventory"
FIGURES = ("orders", "subtotal", "discount_total", "delivery_fee", "tax_total", "total")


@pytest.fixture
def shop(delivery) -> None:  # noqa: F811
    """Delivery zones for checkout (tests.integration.test_payments_api.delivery)."""


# ---- order fixtures through the real flows -------------------------------------------------
def cart(client, db: Session, lines: list[tuple[str, int]]) -> dict:
    headers: dict = {}
    for variant_id, quantity in lines:
        res = add(client, variant_id, quantity, headers)
        assert res.status_code == 200, res.text
        headers = headers or guest(res.json()["cart_token"])  # issued by the first add only
    return headers


def place(client, db: Session, lines: list[tuple[str, int]], method: str) -> dict:
    res = checkout(client, cart(client, db, lines), {"address": INLINE, "payment_method": method})
    assert res.status_code == 201, res.text
    return res.json()["order"]


def started_momo(client, db: Session, lines) -> tuple[dict, str]:
    order = place(client, db, lines, "mtn_momo")
    begun = initiate(client, order["order_number"])
    assert begun.status_code == 200, begun.text
    return order, begun.json()["reference"]


def paid(client, db: Session, lines) -> dict:
    """A mobile-money order whose verified webhook reported success: a paid order."""
    order, reference = started_momo(client, db, lines)
    res = webhook(client, event(reference, "succeeded", order["total"]))
    assert res.status_code == 200 and res.json()["status"] == "processed", res.text
    return order


def move(client, order: dict, statuses: list[str], headers: dict) -> None:
    for status in statuses:
        step(client, order["id"], status, headers)  # stores move, staff cancel (phase 3)


def cod(client, db: Session, lines, headers: dict, statuses: list[str]) -> dict:
    order = place(client, db, lines, "cash_on_delivery")
    move(client, order, statuses, headers)
    return order


DELIVERED = ["confirmed", "processing", "dispatched", "delivered"]


def product(db: Session, variant_id: str, name: str) -> uuid.UUID:
    row = db.scalar(
        select(Product)
        .join(ProductVariant, ProductVariant.product_id == Product.id)
        .where(ProductVariant.id == uuid.UUID(variant_id))
    )
    assert row is not None
    row.name = name
    db.commit()
    return row.id


def sold_at(db: Session, order: dict, instant: datetime) -> None:
    """Date an existing sale: its succeeded payment attempt(s) succeeded at `instant`."""
    db.execute(
        text(
            "UPDATE payment_attempts SET succeeded_at = :at "
            "WHERE order_id = :id AND status = 'succeeded'"
        ),
        {"at": instant, "id": uuid.UUID(order["id"])},
    )
    db.commit()


def kigali(year: int, month: int, day: int, hour: int, minute: int, second: int) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=KIGALI)


def get(client, path: str, headers: dict, **params):
    query = {k: v.isoformat() if isinstance(v, date) else v for k, v in params.items()}
    return client.get(f"{REPORTS}{path}", params=query, headers=headers)


def figures(db: Session, *orders: dict) -> dict:
    rows = [db.get(Order, uuid.UUID(o["id"])) for o in orders]
    return {
        "orders": len(rows),
        **{name: sum(getattr(r, name) for r in rows) for name in FIGURES[1:]},
    }


def today() -> date:
    return datetime.now(UTC).astimezone(KIGALI).date()


def workbook(res):
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == XLSX_CONTENT_TYPE
    assert res.headers["cache-control"] == "no-store"
    return load_workbook(io.BytesIO(res.content))


def sheet_rows(book, title: str) -> list[list]:
    return [list(row) for row in book[title].iter_rows(values_only=True)]


def as_date(value):
    return value.date() if isinstance(value, datetime) else value


# ---- sales: what counts ------------------------------------------------------------------------
def test_sales_count_paid_and_delivered_cod_orders_once_and_nothing_else(
    client, db, shop, admin_auth, monkeypatch
):
    ops = admin_auth["headers"]
    a, b = sku(db, price=7_000), sku(db, price=2_500)
    momo = paid(client, db, [(a, 2), (b, 1)])  # two lines: still one order
    delivered = cod(client, db, [(b, 3)], ops, DELIVERED)
    # Not sales (UAT scenario 7: only paid orders and delivered cash-on-delivery orders):
    place(client, db, [(a, 1)], "mtn_momo")  # created, never initiated
    started_momo(client, db, [(a, 1)])  # pending at the provider
    failed, reference = started_momo(client, db, [(b, 1)])
    assert webhook(client, event(reference, "failed", failed["total"])).status_code == 200
    cod(client, db, [(b, 1)], ops, ["confirmed"])  # cash due, not delivered
    cod(client, db, [(b, 1)], ops, ["confirmed", "processing", "dispatched"])
    cod(client, db, [(b, 1)], ops, ["cancelled"])
    late, late_reference = started_momo(client, db, [(a, 1)])  # paid after its hold lapsed
    expires = hold_expiry(db, uuid.UUID(late["id"]))
    assert expires is not None
    with stock_clock_at(monkeypatch, expires):
        res = webhook(client, event(late_reference, "succeeded", late["total"]))
    assert res.json()["status"] == "needs_reconciliation"
    # A second success on the paid order (a duplicate payment) does not make a second sale.
    first = db.scalar(
        select(PaymentAttempt).where(PaymentAttempt.order_id == uuid.UUID(momo["id"]))
    )
    assert first is not None
    db.add(
        PaymentAttempt(
            order_id=first.order_id,
            method="mtn_momo",
            amount=first.amount,
            status="succeeded",
            provider="mock",
            provider_reference=f"MOCK-DUPLICATE-{uuid.uuid4().hex[:8]}",
            idempotency_key=f"duplicate:{uuid.uuid4().hex}",
            succeeded_at=first.succeeded_at,
        )
    )
    db.commit()

    day = today()
    res = get(
        client,
        "/sales",
        admin_auth["headers"],
        **{"from": (day - timedelta(days=1)).isoformat(), "to": (day + timedelta(days=1))},
        group_by="day",
    )
    assert res.status_code == 200, res.text
    body = res.json()
    expected = figures(db, momo, delivered)
    assert {k: body["totals"][k] for k in FIGURES} == expected
    assert expected["orders"] == 2 and expected["total"] == momo["total"] + delivered["total"]
    assert sum(p["orders"] for p in body["periods"]) == 2
    assert body["timezone"] == "Africa/Kigali" and body["group_by"] == "day"
    assert all(isinstance(body["totals"][k], int) for k in FIGURES)  # whole RWF


def test_a_sale_is_dated_by_its_payment_in_kigali_days(client, db, shop, admin_auth):
    v = sku(db, price=4_000)
    before, after = paid(client, db, [(v, 1)]), paid(client, db, [(v, 2)])
    # 21:59:59 and 22:00:00 UTC are 23:59:59 on 9 March and 00:00:00 on 10 March in Kigali.
    sold_at(db, before, datetime(2026, 3, 9, 21, 59, 59, tzinfo=UTC))
    sold_at(db, after, datetime(2026, 3, 9, 22, 0, 0, tzinfo=UTC))
    h = admin_auth["headers"]
    body = get(client, "/sales", h, **{"from": "2026-03-09", "to": "2026-03-10"}, group_by="day")
    periods = body.json()["periods"]
    assert [(p["period_start"], p["orders"], p["total"]) for p in periods] == [
        ("2026-03-09", 1, before["total"]),
        ("2026-03-10", 1, after["total"]),
    ]
    only = get(client, "/sales", h, **{"from": "2026-03-10", "to": "2026-03-10"}, group_by="day")
    assert only.json()["totals"]["orders"] == 1  # the range starts at 00:00 Kigali, not UTC
    assert only.json()["totals"]["total"] == after["total"]
    # The orders were placed today: the order date does not decide the period.
    assert (
        get(client, "/sales", h, **{"from": today(), "to": today()}, group_by="day").json()[
            "totals"
        ]["orders"]
        == 0
    )


def test_weeks_start_on_monday_in_kigali_and_are_cut_at_the_range(client, db, shop, admin_auth):
    v = sku(db, price=3_000)
    sunday, monday, tuesday = (paid(client, db, [(v, 1)]) for _ in range(3))
    sold_at(db, sunday, kigali(2026, 3, 8, 23, 59, 59))  # Sunday 8 March, Kigali
    sold_at(db, monday, kigali(2026, 3, 9, 0, 0, 0))  # Monday 9 March: Sunday 22:00 in UTC
    sold_at(db, tuesday, kigali(2026, 3, 10, 12, 0, 0))
    body = get(
        client,
        "/sales",
        admin_auth["headers"],
        **{"from": "2026-03-04", "to": "2026-03-10"},  # Wednesday to Tuesday
        group_by="week",
    ).json()
    assert [(p["period_start"], p["period_end"], p["orders"]) for p in body["periods"]] == [
        ("2026-03-04", "2026-03-08", 1),  # the week of Monday 2 March, from the Wednesday
        ("2026-03-09", "2026-03-10", 2),  # the week of Monday 9 March, to the Tuesday
    ]
    assert body["totals"]["total"] == sunday["total"] + monday["total"] + tuesday["total"]


def test_empty_ranges_list_every_period_with_zeros(client, db, shop, admin_auth):
    h = admin_auth["headers"]
    days = get(client, "/sales", h, **{"from": "2026-02-27", "to": "2026-03-02"}, group_by="day")
    assert days.status_code == 200
    body = days.json()
    assert [p["period_start"] for p in body["periods"]] == [
        "2026-02-27",
        "2026-02-28",
        "2026-03-01",
        "2026-03-02",
    ]
    assert all(p[k] == 0 for p in body["periods"] for k in FIGURES)
    assert all(body["totals"][k] == 0 for k in FIGURES)
    top = get(client, "/top-products", h, **{"from": "2026-02-27", "to": "2026-03-02"})
    assert top.status_code == 200 and top.json()["items"] == []
    weeks = get(client, "/sales", h, **{"from": "2026-03-02", "to": "2026-03-02"}, group_by="week")
    assert [(p["period_start"], p["period_end"]) for p in weeks.json()["periods"]] == [
        ("2026-03-02", "2026-03-02")
    ]


@pytest.mark.parametrize(
    ("path", "params", "field"),
    [
        ("/sales", {"from": "2026-03-10", "to": "2026-03-09", "group_by": "day"}, "to"),
        ("/sales", {"from": "2025-01-01", "to": "2026-01-02", "group_by": "day"}, "to"),
        ("/sales", {"from": "2026-03-01", "to": "2026-03-09", "group_by": "month"}, "group_by"),
        ("/sales", {"from": "09/03/2026", "to": "2026-03-09", "group_by": "day"}, "from"),
        ("/sales", {"from": "2026-02-30", "to": "2026-03-09", "group_by": "day"}, "from"),
        ("/sales", {"to": "2026-03-09", "group_by": "day"}, "from"),
        ("/sales", {"from": "2026-03-01", "to": "2026-03-09"}, "group_by"),
        ("/top-products", {"from": "2026-03-10", "to": "2026-03-01"}, "to"),
        ("/top-products", {"from": "2026-03-01", "to": "2026-03-09", "limit": 0}, "limit"),
        ("/top-products", {"from": "2026-03-01", "to": "2026-03-09", "limit": 101}, "limit"),
        ("/stock", {"size": 0}, "size"),
        ("/stock", {"page": 0}, "page"),
        ("/sales/export", {"from": "2026-03-01", "to": "2026-03-09"}, "group_by"),
        ("/sales/export", {"to": "2026-03-09", "group_by": "day"}, "from"),
        ("/top-products/export", {"from": "2026-03-01"}, "to"),
        ("/top-products/export", {"from": "2026-03-09", "to": "2026-03-01"}, "to"),
        ("/invoices/export", {}, "report_type"),
    ],
)
def test_invalid_parameters_are_422_validation_errors(client, admin_auth, path, params, field):
    res = client.get(f"{REPORTS}{path}", params=params, headers=admin_auth["headers"])
    assert res.status_code == 422, res.text
    assert code(res) == "validation_error"
    assert field in str(res.json()["error"]["details"])


# ---- top products --------------------------------------------------------------------------
def test_top_products_rank_by_units_then_revenue_then_name(client, db, shop, admin_auth):
    big, bravo, alpha, unsold = (sku(db, price=p) for p in (3_000, 1_000, 1_000, 9_000))
    big_id = product(db, big, "Zulu laptop")
    bravo_id = product(db, bravo, "Bravo cable")
    alpha_id = product(db, alpha, "Alpha charger")
    product(db, unsold, "Only in a pending order")
    paid(client, db, [(big, 2), (bravo, 2)])
    paid(client, db, [(bravo, 1), (alpha, 1)])
    cod(client, db, [(big, 1), (alpha, 2)], admin_auth["headers"], DELIVERED)
    started_momo(client, db, [(unsold, 5)])  # not a sale
    day = today()
    window = {"from": day - timedelta(days=1), "to": day + timedelta(days=1)}
    res = get(client, "/top-products", admin_auth["headers"], **window)
    assert res.status_code == 200, res.text
    items = res.json()["items"]
    assert [(i["rank"], i["product_id"], i["units"], i["revenue"], i["orders"]) for i in items] == [
        (1, str(big_id), 3, 9_000, 2),  # most units and most revenue
        (2, str(alpha_id), 3, 3_000, 2),  # same units and revenue as Bravo: by name
        (3, str(bravo_id), 3, 3_000, 2),
    ]
    assert [i["product_name"] for i in items] == ["Zulu laptop", "Alpha charger", "Bravo cable"]
    limited = get(client, "/top-products", admin_auth["headers"], **window, limit=2).json()
    assert [i["product_id"] for i in limited["items"]] == [str(big_id), str(alpha_id)]
    assert limited["limit"] == 2


def test_a_deleted_products_sales_stay_under_the_name_it_was_sold_with(
    client, db, shop, admin_auth
):
    v = sku(db, price=5_000)
    order = paid(client, db, [(v, 2)])
    db.execute(
        text("UPDATE order_items SET product_id = NULL WHERE order_id = :id"),
        {"id": uuid.UUID(order["id"])},
    )  # as ON DELETE SET NULL leaves it
    db.commit()
    snapshot = db.scalar(
        text("SELECT product_name_snapshot FROM order_items WHERE order_id = :id"),
        {"id": uuid.UUID(order["id"])},
    )
    day = today()
    window = {"from": day - timedelta(days=1), "to": day + timedelta(days=1)}
    [item] = get(client, "/top-products", admin_auth["headers"], **window).json()["items"]
    assert (item["product_id"], item["product_name"], item["units"], item["revenue"]) == (
        None,
        snapshot,
        2,
        10_000,
    )


# ---- stock -------------------------------------------------------------------------------------
def all_pages(client, path: str, headers: dict) -> list[dict]:
    items, page = [], 1
    while True:
        body = client.get(path, params={"page": page, "size": 2}, headers=headers).json()
        items += body["items"]
        if page * 2 >= body["total"]:
            return items
        page += 1


def test_stock_report_is_the_inventory_list_with_totals(client, db, shop, admin_auth):
    held, committed, idle = sku(db, on_hand=5), sku(db, on_hand=4), sku(db, on_hand=0)
    started_momo(client, db, [(held, 2)])  # an active (unpaid) hold
    paid(client, db, [(committed, 3)])  # committed stock (paid, not dispatched)
    h = admin_auth["headers"]
    report = all_pages(client, f"{REPORTS}/stock", h)
    assert report == all_pages(client, INVENTORY, h)  # one calculation, same rows
    by_id = {row["variant_id"]: row for row in report}
    assert (by_id[held]["reserved_quantity"], by_id[held]["available_quantity"]) == (2, 3)
    assert (by_id[committed]["committed_quantity"], by_id[committed]["available_quantity"]) == (
        3,
        1,
    )
    assert by_id[idle]["available_quantity"] == 0
    body = get(client, "/stock", h).json()
    totals = body["totals"]
    assert totals["skus"] == body["total"] == len(report)
    for name in ("on_hand", "reserved_quantity", "committed_quantity", "available_quantity"):
        assert totals[name] == sum(row[name] for row in report), name
    assert totals["low_stock_skus"] == sum(row["is_low_stock"] for row in report)
    assert datetime.fromisoformat(body["generated_at"]).utcoffset() == timedelta(hours=2)


# ---- authorization -------------------------------------------------------------------------
ENDPOINTS = [
    ("/sales", {"from": "2026-03-01", "to": "2026-03-07", "group_by": "day"}),
    ("/top-products", {"from": "2026-03-01", "to": "2026-03-07"}),
    ("/stock", {}),
    ("/sales/export", {"from": "2026-03-01", "to": "2026-03-07", "group_by": "week"}),
    ("/top-products/export", {"from": "2026-03-01", "to": "2026-03-07"}),
    ("/stock/export", {}),
]


@pytest.mark.parametrize("who", ["admin_auth"])
def test_reports_read_holders_can_use_every_report(client, request, who):
    headers = request.getfixturevalue(who)["headers"]
    for path, params in ENDPOINTS:
        res = client.get(f"{REPORTS}{path}", params=params, headers=headers)
        assert res.status_code == 200, (path, res.text)


@pytest.mark.parametrize("who", ["customer_auth"])
def test_everyone_else_gets_403_on_every_report(client, request, who):
    headers = request.getfixturevalue(who)["headers"]
    for path, params in ENDPOINTS:
        res = client.get(f"{REPORTS}{path}", params=params, headers=headers)
        assert res.status_code == 403 and code(res) == "permission_denied", path


def test_anonymous_callers_are_401(client):
    for path, params in ENDPOINTS:
        assert client.get(f"{REPORTS}{path}", params=params).status_code == 401, path


# ---- exports match the JSON ----------------------------------------------------------------
def test_the_sales_export_matches_the_json_report(client, db, shop, admin_auth):
    v = sku(db, price=6_000)
    first, second = paid(client, db, [(v, 1)]), paid(client, db, [(v, 3)])
    sold_at(db, first, kigali(2026, 3, 9, 8, 0, 0))
    sold_at(db, second, kigali(2026, 3, 11, 20, 0, 0))
    params = {"from": "2026-03-09", "to": "2026-03-12", "group_by": "day"}
    h = admin_auth["headers"]
    body = get(client, "/sales", h, **params).json()
    res = get(client, "/sales/export", h, **params)
    book = workbook(res)
    assert (
        res.headers["content-disposition"]
        == 'attachment; filename="sales-2026-03-09-to-2026-03-12-by-day.xlsx"'
    )
    rows = sheet_rows(book, "Sales")
    assert tuple(rows[0]) == SALES_HEADERS
    expected = [
        [date.fromisoformat(p["period_start"]), date.fromisoformat(p["period_end"])]
        + [p[k] for k in FIGURES]
        for p in body["periods"]
    ]
    assert [[as_date(c) for c in row[:2]] + row[2:] for row in rows[1:-1]] == expected
    assert rows[-1] == ["Total", None] + [body["totals"][k] for k in FIGURES]
    assert body["totals"]["orders"] == 2
    about = dict(sheet_rows(book, "About"))
    assert about["Grouped by"] == "day" and about["Time zone"] == "Africa/Kigali"
    assert as_date(about["From"]) == date(2026, 3, 9) and as_date(about["To"]) == date(2026, 3, 12)


def test_the_top_products_export_matches_the_json_and_never_writes_formulas(
    client, db, shop, admin_auth
):
    risky = sku(db, price=2_000)
    product(db, risky, '=HYPERLINK("http://example.invalid","click")')
    other = sku(db, price=1_000)
    paid(client, db, [(risky, 2), (other, 1)])
    day = today()
    params = {"from": day - timedelta(days=1), "to": day + timedelta(days=1), "limit": 5}
    h = admin_auth["headers"]
    body = get(client, "/top-products", h, **params).json()
    book = workbook(get(client, "/top-products/export", h, **params))
    rows = sheet_rows(book, "Top products")
    assert tuple(rows[0]) == TOP_PRODUCTS_HEADERS
    assert rows[1:] == [
        [i["rank"], i["product_name"], i["product_id"], i["units"], i["revenue"], i["orders"]]
        for i in body["items"]
    ]
    cell = book["Top products"]["B2"]
    assert cell.value == '=HYPERLINK("http://example.invalid","click")'
    assert cell.data_type == "s"  # stored as text: it never runs as a formula


def test_the_stock_export_matches_the_json_report(client, db, shop, admin_auth):
    variant = sku(db, on_hand=3)
    started_momo(client, db, [(variant, 1)])
    h = admin_auth["headers"]
    rows_json = all_pages(client, f"{REPORTS}/stock", h)
    totals = get(client, "/stock", h).json()["totals"]
    res = get(client, "/stock/export", h)
    book = workbook(res)
    assert res.headers["content-disposition"].startswith('attachment; filename="stock-')
    rows = sheet_rows(book, "Stock")
    assert tuple(rows[0]) == STOCK_HEADERS

    def yes(flag: bool) -> str:
        return "yes" if flag else "no"

    assert rows[1:-1] == [
        [
            r["sku"],
            r["product_name"],
            r["variant_name"],
            yes(r["is_sellable"]),
            r["on_hand"],
            r["unavailable_quantity"],
            r["reserved_quantity"],
            r["committed_quantity"],
            r["available_quantity"],
            r["low_stock_threshold"],
            yes(r["is_low_stock"]),
        ]
        for r in rows_json
    ]
    assert rows[-1] == [
        "Total",
        f"{totals['skus']} SKUs",
        None,
        None,
        totals["on_hand"],
        totals["unavailable_quantity"],
        totals["reserved_quantity"],
        totals["committed_quantity"],
        totals["available_quantity"],
        None,
        f"{totals['low_stock_skus']} low",
    ]
