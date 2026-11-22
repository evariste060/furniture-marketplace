"""Seller orders (ADR-014 phase 3; owner decisions of 2026-11-21).

One parent order and one payment per checkout, split into one seller order per store with its
commission snapshot. Each store's seller moves only its own seller order; the order's status is
derived from them; stock leaves inventory when each store dispatches; cash on delivery works for
several stores with one payment; commission is charged after each store's share of the
discount. Every seller route is tested across stores: seller A is refused seller B's orders.
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import (
    AuditRecord,
    InventoryBalance,
    OrderItem,
    PaymentAttempt,
    SellerOrder,
    StockReservation,
    Store,
)
from app.services.inventory import expire_due_reservations
from app.services.seller_order_service import _parent_target, commission_amount
from tests.integration.test_cart_api import add, guest, sku
from tests.integration.test_checkout_api import (  # noqa: F401
    INLINE,
    STAFF,
    checkout,
    delivery,
)
from tests.integration.test_payments_api import event, initiate, webhook
from tests.integration.test_promotions_api import apply, create_promotion
from tests.support.commerce import stock_clock_at
from tests.support.seller_orders import (
    SELLER_ORDERS,
    advance,
    move,
    owner_headers,
    seller_orders,
)

EARNINGS = "/api/v1/seller/earnings"


def store_id_of(db, variant_id: str) -> uuid.UUID:
    from app.models import Product, ProductVariant

    db.expire_all()
    store_id = db.scalar(
        select(Product.store_id)
        .join(ProductVariant, ProductVariant.product_id == Product.id)
        .where(ProductVariant.id == uuid.UUID(variant_id))
    )
    assert store_id is not None
    return store_id


@pytest.fixture
def two_stores(client, db, admin_auth, delivery):  # noqa: F811
    """Store A (commission override 15%) sells a 30 000 SKU, store B (platform default 10%) a
    10 000 SKU; each with stock 5."""
    a = sku(db, price=30_000, on_hand=5)
    b = sku(db, price=10_000, on_hand=5)
    store_a = db.get(Store, store_id_of(db, a))
    assert store_a is not None
    store_a.commission_rate_bps = 1500
    db.commit()
    return {"a": a, "b": b, "store_a": store_id_of(db, a), "store_b": store_id_of(db, b)}


def place(client, two_stores, *, method="cash_on_delivery", code: str | None = None) -> dict:
    cart = add(client, two_stores["a"], 1)
    assert cart.status_code == 200, cart.text
    h = guest(cart.json()["cart_token"])
    assert add(client, two_stores["b"], 2, h).status_code == 200
    if code:
        assert apply(client, h, code).status_code == 200
    res = checkout(client, h, {"address": INLINE, "payment_method": method})
    assert res.status_code == 201, res.text
    return res.json()["order"]


def by_store(db, order_id: str) -> dict[uuid.UUID, SellerOrder]:
    return {row.store_id: row for row in seller_orders(db, order_id)}


def holds(db, order_id: str, variant_id: str) -> str:
    db.expire_all()
    return db.scalar(
        select(StockReservation.status).where(
            StockReservation.order_id == uuid.UUID(order_id),
            StockReservation.variant_id == uuid.UUID(variant_id),
        )
    )


def on_hand(db, variant_id: str) -> int:
    db.expire_all()
    return db.scalar(
        select(InventoryBalance.on_hand).where(InventoryBalance.variant_id == uuid.UUID(variant_id))
    )


def parent(client, admin_auth, order_id: str) -> dict:
    res = client.get(f"{STAFF}/{order_id}", headers=admin_auth["headers"])
    assert res.status_code == 200, res.text
    return res.json()


# ---- checkout grouping and commission (owner decision 4) ---------------------------------------
def test_checkout_splits_one_order_into_seller_orders_with_commission_after_discount(
    client, db, admin_auth, two_stores
):
    promo = create_promotion(client, admin_auth["headers"], percent_off=10)
    order = place(client, two_stores, code=promo["code"])
    # One parent order and one payment: 50 000 - 5 000 discount + 2 000 delivery.
    assert (order["subtotal"], order["discount_total"], order["total"]) == (50_000, 5_000, 47_000)
    db.expire_all()
    assert len(db.scalars(select(PaymentAttempt)).all()) == 1
    rows = by_store(db, order["id"])
    a, b = rows[two_stores["store_a"]], rows[two_stores["store_b"]]
    # The discount follows the lines' existing allocation and adds up to the order's exactly.
    assert (a.subtotal, a.discount_total, a.merchandise_total) == (30_000, 3_000, 27_000)
    assert (b.subtotal, b.discount_total, b.merchandise_total) == (20_000, 2_000, 18_000)
    assert a.discount_total + b.discount_total == order["discount_total"]
    # Commission on the discounted merchandise, at each store's rate; delivery is not included.
    assert (a.commission_rate_bps, a.commission_amount, a.seller_net_amount) == (1500, 4050, 22950)
    assert (b.commission_rate_bps, b.commission_amount, b.seller_net_amount) == (1000, 1800, 16200)
    assert {a.status, b.status} == {"pending"}
    lines = {line["sku"]: line for line in order["lines"]}
    names = {line["store_name"] for line in lines.values()}
    assert names == {a.store_name_snapshot, b.store_name_snapshot}
    staff = parent(client, admin_auth, order["id"])
    assert {s["store_id"] for s in staff["seller_orders"]} == {str(a.store_id), str(b.store_id)}
    assert sum(s["commission_amount"] for s in staff["seller_orders"]) == 5850


def test_commission_snapshots_never_follow_a_later_rate_change(client, db, admin_auth, two_stores):
    order = place(client, two_stores)
    store_a = db.get(Store, two_stores["store_a"])
    assert store_a is not None
    store_a.commission_rate_bps = 3000
    db.commit()
    row = by_store(db, order["id"])[two_stores["store_a"]]
    assert (row.commission_rate_bps, row.commission_amount) == (1500, 4500)


@pytest.mark.parametrize(
    ("base", "bps", "expected"),
    [
        (25, 1000, 3),
        (24, 1000, 2),
        (15, 1000, 2),
        (0, 1500, 0),
        (1, 0, 0),
        (99_999, 10_000, 99_999),
    ],
)
def test_commission_is_rounded_half_up_to_whole_rwf(base, bps, expected):
    assert commission_amount(base, bps) == expected


def test_commission_refuses_an_invalid_rate_or_base():
    for base, bps in ((-1, 1000), (10, -1), (10, 10_001)):
        with pytest.raises(ValueError):
            commission_amount(base, bps)


@pytest.mark.parametrize(
    ("parent_status", "groups", "expected"),
    [
        ("received", ["confirmed", "pending"], None),
        ("received", ["confirmed", "confirmed"], "confirmed"),
        ("confirmed", ["processing", "confirmed"], "processing"),
        ("processing", ["dispatched", "processing"], None),
        ("processing", ["dispatched", "delivered"], "dispatched"),
        ("dispatched", ["delivered", "dispatched"], None),
        ("dispatched", ["delivered", "delivered"], "delivered"),
        ("cancelled", ["cancelled", "cancelled"], None),
        ("delivered", ["delivered"], None),
    ],
)
def test_the_order_status_is_derived_from_its_seller_orders(parent_status, groups, expected):
    assert _parent_target(parent_status, groups) == expected


# ---- the stores fulfil, the order follows (owner decisions 1-3) --------------------------------
def test_each_store_issues_its_own_stock_and_the_order_follows_the_last_store(
    client, db, admin_auth, two_stores
):
    order = place(client, two_stores)
    rows = by_store(db, order["id"])
    a, b = rows[two_stores["store_a"]], rows[two_stores["store_b"]]

    # Cash on delivery with two stores: one store's confirmation leaves the order and its
    # stock as they were; processing waits for every store to confirm.
    assert move(client, db, a, "confirmed").json()["order_status"] == "received"
    assert holds(db, order["id"], two_stores["a"]) == "active"
    early = move(client, db, a, "processing")
    assert early.status_code == 409
    assert early.json()["error"]["code"] == "seller_order_awaiting_other_stores"
    assert move(client, db, b, "confirmed").json()["order_status"] == "confirmed"
    assert {holds(db, order["id"], v) for v in (two_stores["a"], two_stores["b"])} == {"committed"}

    assert move(client, db, a, "processing").json()["order_status"] == "processing"
    res = move(client, db, a, "dispatched")
    assert res.status_code == 200 and res.json()["order_status"] == "processing"
    # Store A's stock left inventory; store B's stays committed until B dispatches.
    assert (holds(db, order["id"], two_stores["a"]), on_hand(db, two_stores["a"])) == (
        "fulfilled",
        4,
    )
    assert (holds(db, order["id"], two_stores["b"]), on_hand(db, two_stores["b"])) == (
        "committed",
        5,
    )
    assert move(client, db, a, "delivered").json()["order_status"] == "processing"
    attempt = db.scalar(select(PaymentAttempt))
    assert attempt is not None and attempt.status == "pending"  # not one store's cash

    assert move(client, db, b, "processing").status_code == 200
    assert move(client, db, b, "dispatched").json()["order_status"] == "dispatched"
    assert (holds(db, order["id"], two_stores["b"]), on_hand(db, two_stores["b"])) == (
        "fulfilled",
        3,
    )
    assert move(client, db, b, "delivered").json()["order_status"] == "delivered"
    db.expire_all()
    [attempt] = db.scalars(select(PaymentAttempt)).all()
    assert attempt.status == "succeeded" and attempt.amount == order["total"]  # one payment
    detail = parent(client, admin_auth, order["id"])
    assert [h["status"] for h in detail["status_history"]] == [
        "received",
        "confirmed",
        "processing",
        "dispatched",
        "delivered",
    ]
    dispatches = db.scalars(
        select(AuditRecord).where(
            AuditRecord.action == "inventory.dispatch", AuditRecord.entity_id == order["id"]
        )
    ).all()
    assert len(dispatches) == 2  # one per store, never repeated by the order's dispatch


def test_an_unpaid_mobile_money_order_is_hidden_from_its_stores_until_paid(
    client, db, admin_auth, two_stores
):
    order = place(client, two_stores, method="mtn_momo")
    rows = by_store(db, order["id"])
    a = rows[two_stores["store_a"]]
    headers = owner_headers(db, a.store_id)
    assert client.get(SELLER_ORDERS, headers=headers).json()["items"] == []
    assert client.get(f"{SELLER_ORDERS}/{a.id}", headers=headers).status_code == 404
    assert move(client, db, a, "confirmed").status_code == 404
    started = initiate(client, order["order_number"])
    assert started.status_code == 200, started.text
    paid = webhook(client, event(started.json()["reference"], "succeeded", order["total"]))
    assert paid.status_code == 200, paid.text
    listed = client.get(SELLER_ORDERS, headers=headers).json()["items"]
    assert [i["id"] for i in listed] == [str(a.id)]
    assert listed[0]["payment_status"] == "succeeded"
    advance(client, db, order["id"], "delivered")
    assert parent(client, admin_auth, order["id"])["status"] == "delivered"


def test_a_lapsed_cash_on_delivery_hold_cancels_the_whole_order_even_if_one_store_confirmed(
    client, db, admin_auth, two_stores, monkeypatch
):
    order = place(client, two_stores)
    rows = by_store(db, order["id"])
    assert move(client, db, rows[two_stores["store_a"]], "confirmed").status_code == 200
    due = db.scalar(select(StockReservation.expires_at)) + timedelta(seconds=1)
    with stock_clock_at(monkeypatch, due):
        assert expire_due_reservations(db).orders == 1
    db.expire_all()
    assert parent(client, admin_auth, order["id"])["status"] == "cancelled"
    assert {r.status for r in seller_orders(db, order["id"])} == {"cancelled"}
    history = [h.reason for h in seller_orders(db, order["id"])[0].history]
    assert history[-1] == "payment_timeout"
    late = move(client, db, rows[two_stores["store_b"]], "confirmed")
    assert late.status_code == 409 and late.json()["error"]["code"] == "invalid_transition"


def test_staff_cancellation_cancels_every_seller_order_and_sellers_cannot_cancel(
    client, db, admin_auth, two_stores
):
    order = place(client, two_stores)
    rows = by_store(db, order["id"])
    a = rows[two_stores["store_a"]]
    assert move(client, db, a, "confirmed").status_code == 200
    refused = client.patch(
        f"{SELLER_ORDERS}/{a.id}/status",
        json={"status": "cancelled"},
        headers=owner_headers(db, a.store_id),
    )
    assert refused.status_code == 422
    res = client.patch(
        f"{STAFF}/{order['id']}/status",
        json={"status": "cancelled", "reason": "Customer called."},
        headers=admin_auth["headers"],
    )
    assert res.status_code == 200, res.text
    assert {r.status for r in seller_orders(db, order["id"])} == {"cancelled"}
    assert holds(db, order["id"], two_stores["a"]) == "released"


def test_staff_have_no_fulfilment_controls(client, db, admin_auth, two_stores):
    order = place(client, two_stores)
    for requested in ("confirmed", "processing", "dispatched", "delivered"):
        res = client.patch(
            f"{STAFF}/{order['id']}/status",
            json={"status": requested},
            headers=admin_auth["headers"],
        )
        assert res.status_code == 409, requested
        assert res.json()["error"]["code"] == "order_status_follows_seller_orders"
    # Staff are not sellers: the seller routes refuse them.
    seller_order = seller_orders(db, order["id"])[0]
    res = client.patch(
        f"{SELLER_ORDERS}/{seller_order.id}/status",
        json={"status": "confirmed"},
        headers=admin_auth["headers"],
    )
    assert res.status_code == 403 and res.json()["error"]["code"] == "seller_not_approved"
    assert parent(client, admin_auth, order["id"])["status"] == "received"


# ---- seller isolation (cross-store matrix) ---------------------------------------------------
def test_seller_a_is_refused_seller_b_orders_on_every_route(client, db, admin_auth, two_stores):
    order = place(client, two_stores)
    rows = by_store(db, order["id"])
    a, b = rows[two_stores["store_a"]], rows[two_stores["store_b"]]
    ha, hb = owner_headers(db, a.store_id), owner_headers(db, b.store_id)
    for mine, theirs, headers in ((a, b, ha), (b, a, hb)):
        listed = client.get(SELLER_ORDERS, headers=headers).json()
        assert [i["id"] for i in listed["items"]] == [str(mine.id)] and listed["total"] == 1
        assert client.get(f"{SELLER_ORDERS}/{mine.id}", headers=headers).status_code == 200
        read = client.get(f"{SELLER_ORDERS}/{theirs.id}", headers=headers)
        assert read.status_code == 404 and read.json()["error"]["code"] == "seller_order_not_found"
        moved = client.patch(
            f"{SELLER_ORDERS}/{theirs.id}/status", json={"status": "confirmed"}, headers=headers
        )
        assert moved.status_code == 404
        missing = client.get(f"{SELLER_ORDERS}/{uuid.uuid4()}", headers=headers)
        assert missing.status_code == 404 and missing.json() == read.json()  # indistinguishable
    assert {r.status for r in seller_orders(db, order["id"])} == {"pending"}
    # Earnings are the caller's own store only.
    assert client.get(EARNINGS, headers=ha).json()["store_id"] == str(a.store_id)
    assert client.get(EARNINGS, headers=hb).json()["store_id"] == str(b.store_id)


def test_a_seller_sees_only_their_lines_and_the_delivery_details(
    client, db, admin_auth, two_stores
):
    promo = create_promotion(client, admin_auth["headers"], percent_off=10)
    order = place(client, two_stores, code=promo["code"])
    a = by_store(db, order["id"])[two_stores["store_a"]]
    res = client.get(f"{SELLER_ORDERS}/{a.id}", headers=owner_headers(db, a.store_id))
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["lines"]) == 1 and body["lines"][0]["quantity"] == 1
    assert body["recipient_name"] == INLINE["recipient_name"]
    assert body["recipient_phone"].endswith("788123456")
    assert body["delivery_address"]["street_address"] == INLINE["street_address"]
    assert body["payment_method"] == "cash_on_delivery" and body["merchandise_total"] == 27_000
    text = res.text
    for hidden in (
        "customer_email",
        "user_id",
        promo["code"],
        '"total"',
        "delivery_fee",
        "zone_fee",
        "free_delivery",
        str(two_stores["store_b"]),
    ):
        assert hidden not in text, hidden
    other = by_store(db, order["id"])[two_stores["store_b"]]
    other_skus = {
        i.sku_snapshot for i in db.scalars(select(OrderItem)) if i.store_id == other.store_id
    }
    assert not any(s in text for s in other_skus)
    reads = db.scalars(select(AuditRecord).where(AuditRecord.action == "seller_order.read")).all()
    assert [r.entity_id for r in reads] == [str(a.id)]  # every read is audited


@pytest.mark.parametrize(
    "body",
    [
        {"status": "confirmed", "store_id": str(uuid.uuid4())},
        {"status": "confirmed", "commission_rate_bps": 0},
        {"status": "confirmed", "order_status": "delivered"},
        {"status": "received"},
        {"status": "pending"},
        {"status": "cancelled"},
        {},
    ],
)
def test_the_seller_status_body_refuses_anything_else(client, db, two_stores, body):
    order = place(client, two_stores)
    row = seller_orders(db, order["id"])[0]
    res = client.patch(
        f"{SELLER_ORDERS}/{row.id}/status", json=body, headers=owner_headers(db, row.store_id)
    )
    assert res.status_code == 422, res.text
    assert seller_orders(db, order["id"])[0].status == "pending"


# ---- earnings --------------------------------------------------------------------------------
def test_earnings_are_pending_until_delivered_and_paid(client, db, admin_auth, two_stores):
    order = place(client, two_stores)
    rows = by_store(db, order["id"])
    a, b = rows[two_stores["store_a"]], rows[two_stores["store_b"]]
    ha = owner_headers(db, a.store_id)
    empty = {"orders": 0, "merchandise_total": 0, "commission_amount": 0, "seller_net_amount": 0}
    assert client.get(EARNINGS, headers=ha).json()["pending"] == empty  # not confirmed yet
    advance(client, db, order["id"], "dispatched")
    assert move(client, db, a, "delivered").status_code == 200
    mine = client.get(EARNINGS, headers=ha).json()
    # Delivered, but the order's cash is collected only when the last store delivers.
    assert mine["pending"] == {
        "orders": 1,
        "merchandise_total": 30_000,
        "commission_amount": 4_500,
        "seller_net_amount": 25_500,
    }
    assert mine["earned"] == empty
    assert move(client, db, b, "delivered").status_code == 200
    mine = client.get(EARNINGS, headers=ha).json()
    assert mine["pending"] == empty and mine["earned"]["seller_net_amount"] == 25_500
    staff = client.get(
        f"/api/v1/staff/sellers/{b.store_id}/earnings", headers=admin_auth["headers"]
    )
    assert staff.status_code == 200 and staff.json()["earned"]["commission_amount"] == 2_000
    missing = client.get(
        f"/api/v1/staff/sellers/{uuid.uuid4()}/earnings", headers=admin_auth["headers"]
    )
    assert missing.status_code == 404


def test_staff_earnings_need_the_sellers_permission(client, customer_auth):
    res = client.get(
        f"/api/v1/staff/sellers/{uuid.uuid4()}/earnings", headers=customer_auth["headers"]
    )
    assert res.status_code == 403


def test_the_staff_order_list_filters_by_store(client, db, admin_auth, two_stores):
    both = place(client, two_stores)
    only_b = add(client, two_stores["b"], 1)
    h = guest(only_b.json()["cart_token"])
    single = checkout(client, h).json()["order"]

    def ids(store_id) -> set[str]:
        res = client.get(STAFF, params={"store_id": str(store_id)}, headers=admin_auth["headers"])
        assert res.status_code == 200, res.text
        return {o["id"] for o in res.json()["items"]}

    assert ids(two_stores["store_a"]) == {both["id"]}
    assert ids(two_stores["store_b"]) == {both["id"], single["id"]}
    assert ids(uuid.uuid4()) == set()
