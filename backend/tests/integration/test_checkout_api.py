"""Module 14 — checkout and orders (RE-026; TC-06, TC-07, TC-12, TC-14; §7 Q11-Q16, Q21).
Disposable per-test PostgreSQL schema (tests/conftest.py)."""

import re
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import (
    Cart,
    DiscountRedemption,
    InventoryBalance,
    Order,
    OrderItem,
    OrderStatusHistory,
    PaymentAttempt,
    StockReservation,
)
from app.models.operations import AuditRecord
from app.services import checkout_service
from app.services.inventory import expire_due_reservations
from tests.integration.test_cart_api import add, code, guest, sku
from tests.integration.test_delivery_api import create_zone, set_threshold
from tests.integration.test_promotions_api import apply, create_promotion
from tests.support.commerce import wait_until_due

CHECKOUT = "/api/v1/checkout"
HISTORY = "/api/v1/customers/me/orders"
LOOKUP = "/api/v1/orders/lookup"
STAFF = "/api/v1/staff/orders"
ADDRESSES = "/api/v1/customers/me/addresses"
ORDER_NUMBER = re.compile(r"^ORD-\d{6}-[2-9A-HJ-NP-Z]{6}$")
INLINE = {
    "recipient_name": "Aline Uwase",
    "phone": "0788 123 456",
    "district": "gasabo",
    "street_address": "KG 11 Ave, house 4",
}


@pytest.fixture
def delivery(client, admin_auth) -> dict:
    """Gasabo (COD) 2 000 and Kicukiro (no COD) 1 500; free delivery from 200 000."""
    h = admin_auth["headers"]
    zones = {
        "Gasabo": create_zone(client, h, "Gasabo", 2000),
        "Kicukiro": create_zone(client, h, "Kicukiro", 1500, cod_available=False),
    }
    set_threshold(client, h, 200_000)
    return zones


def key() -> dict:
    return {"Idempotency-Key": f"key-{uuid.uuid4().hex}"}


def checkout(client: TestClient, headers: dict, body: dict | None = None, idem: dict | None = None):
    payload = body or {"address": INLINE, "payment_method": "cash_on_delivery"}
    return client.post(CHECKOUT, json=payload, headers={**headers, **(idem or key())})


def guest_cart(client: TestClient, db: Session, price: int = 10_000, quantity: int = 1) -> dict:
    created = add(client, sku(db, price=price), quantity)
    assert created.status_code == 200, created.text
    return guest(created.json()["cart_token"])


def count(db: Session, model) -> int:
    db.expire_all()
    return db.scalar(select(func.count()).select_from(model)) or 0


def save_address(client: TestClient, headers: dict, district: str = "Gasabo") -> str:
    res = client.post(
        ADDRESSES,
        json={**INLINE, "district": district, "recipient_name": "Saved Name"},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


# ---- TC-06: guest checkout -----------------------------------------------------------------
def test_tc06_guest_checkout_with_cash_on_delivery(client, db, delivery):
    h = guest_cart(client, db, price=10_000, quantity=2)
    res = checkout(
        client,
        h,
        {
            **{"address": INLINE, "payment_method": "cash_on_delivery"},
            "email": "Aline@Example.rw",
            "note": "Call first",
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    order = body["order"]
    assert ORDER_NUMBER.match(order["order_number"])
    assert (order["subtotal"], order["discount_total"], order["delivery_fee"]) == (20_000, 0, 2000)
    assert order["total"] == 22_000
    assert order["tax_total"] == 3356  # 22 000 x 18/118 = 3355.93 -> 3356 (ADR-007)
    assert order["tax_treatment"] == "vat_inclusive"
    assert order["status"] == "received" and order["delivery_zone"] == "Gasabo"
    assert order["recipient_phone"] == "+250788123456"
    assert order["delivery_address"]["district"] == "Gasabo"  # canonical district
    assert order["payment"]["method"] == "cash_on_delivery"
    assert order["payment"]["status"] == "pending"  # due on delivery, not paid (TC-12)
    assert [line["quantity"] for line in order["lines"]] == [2]
    assert order["lines"][0]["line_total"] == 20_000
    assert set(body["payment_methods_available"]) == {
        "mtn_momo",
        "airtel_money",
        "cash_on_delivery",
    }
    assert body["replayed"] is False and body["reservation_expires_at"] is not None
    db.expire_all()
    stored = db.scalar(select(Order))
    assert stored is not None and stored.user_id is None
    assert (
        stored.customer_email_snapshot == "aline@example.rw"
        and stored.customer_note == "Call first"
    )
    assert stored.tax_snapshot["rate_percent"] == 18
    assert count(db, StockReservation) == 1 and count(db, OrderStatusHistory) == 1
    assert db.scalar(select(Cart.status)) == "converted"
    assert client.get("/api/v1/cart", headers=h).status_code == 404  # the cart is closed
    assert (
        len(list(db.scalars(select(AuditRecord).where(AuditRecord.action == "order.checkout"))))
        == 1
    )


def test_mobile_money_holds_15_minutes_and_cod_24_hours(client, db, delivery):
    momo = checkout(
        client, guest_cart(client, db), {"address": INLINE, "payment_method": "mtn_momo"}
    )
    cod = checkout(
        client, guest_cart(client, db), {"address": INLINE, "payment_method": "cash_on_delivery"}
    )
    assert momo.json()["order"]["payment"]["status"] == "created"
    db.expire_all()
    holds = dict(
        db.execute(
            select(PaymentAttempt.method, StockReservation.expires_at - Order.created_at)
            .join(Order, Order.id == PaymentAttempt.order_id)
            .join(StockReservation, StockReservation.order_id == Order.id)
        ).all()
    )
    assert 14 * 60 < holds["mtn_momo"].total_seconds() <= 15 * 60 + 5
    assert 24 * 3600 - 5 < holds["cash_on_delivery"].total_seconds() <= 24 * 3600 + 5
    assert cod.status_code == 201


# ---- TC-07: checkout with an account -------------------------------------------------------
def test_tc07_customer_checkout_with_a_saved_address_and_history(
    client, db, customer_auth, delivery
):
    h = customer_auth["headers"]
    address_id = save_address(client, h)
    add(client, sku(db, price=5_000), 1, h)
    res = checkout(client, h, {"address_id": address_id, "payment_method": "airtel_money"})
    assert res.status_code == 201, res.text
    order = res.json()["order"]
    assert order["recipient_name"] == "Saved Name"
    assert order["delivery_address"]["source"] == "saved"
    history = client.get(HISTORY, headers=h).json()
    assert history["total"] == 1 and history["items"][0]["order_number"] == order["order_number"]
    assert history["items"][0]["payment_status"] == "created"
    assert history["items"][0]["item_count"] == 1
    detail = client.get(f"{HISTORY}/{order['id']}", headers=h).json()
    assert detail["total"] == 7_000 and detail["lines"][0]["sku"]
    db.expire_all()
    assert db.scalar(select(Order.customer_email_snapshot)) == "customer.a@example.com"


def test_customer_checkout_with_an_inline_address(client, db, customer_auth, delivery):
    h = customer_auth["headers"]
    add(client, sku(db), 1, h)
    res = checkout(client, h)
    assert res.status_code == 201 and res.json()["order"]["delivery_address"]["source"] == "inline"
    add(client, sku(db), 1, h)  # a new cart starts after checkout
    assert checkout(client, h).status_code == 201
    assert client.get(HISTORY, headers=h).json()["total"] == 2


def test_saved_addresses_belong_to_their_owner(
    client, db, customer_auth, second_customer_auth, delivery
):
    others = save_address(client, second_customer_auth["headers"])
    h = customer_auth["headers"]
    add(client, sku(db), 1, h)
    res = checkout(client, h, {"address_id": others, "payment_method": "cash_on_delivery"})
    assert res.status_code == 422  # another customer's address is not found
    g = guest_cart(client, db)
    res = checkout(client, g, {"address_id": others, "payment_method": "cash_on_delivery"})
    assert res.status_code == 422  # guests use an inline address
    assert count(db, Order) == 0


# ---- tampered amounts and validation -------------------------------------------------------
@pytest.mark.parametrize(
    "extra",
    [
        {"total": 1},
        {"subtotal": 1},
        {"delivery_fee": 0},
        {"discount_total": 99_999},
        {"tax_total": 0},
        {"lines": [{"variant_id": str(uuid.uuid4()), "unit_price": 1}]},
        {"order_number": "ORD-000000-AAAAAA"},
    ],
)
def test_client_amounts_are_refused(client, db, delivery, extra):
    h = guest_cart(client, db)
    res = checkout(client, h, {"address": INLINE, "payment_method": "cash_on_delivery", **extra})
    assert res.status_code == 422
    assert count(db, Order) == 0


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"payment_method": "cash_on_delivery"}, 422),  # no address
        ({"address": INLINE, "address_id": str(uuid.uuid4()), "payment_method": "mtn_momo"}, 422),
        ({"address": INLINE, "payment_method": "bitcoin"}, 422),
        ({"address": INLINE, "payment_method": "card"}, 422),  # not offered (§7 Q21)
        ({"address": {**INLINE, "phone": "12345"}, "payment_method": "mtn_momo"}, 422),
        ({"address": {**INLINE, "district": "Musanze"}, "payment_method": "mtn_momo"}, 422),
        ({"address": INLINE, "payment_method": "mtn_momo", "email": "not-an-email"}, 422),
    ],
)
def test_invalid_requests_are_refused(client, db, delivery, body, status):
    h = guest_cart(client, db)
    assert checkout(client, h, body).status_code == status
    assert count(db, Order) == 0


def test_districts_outside_the_area_and_cod_where_not_offered(client, db, delivery):
    h = guest_cart(client, db)
    res = checkout(
        client, h, {"address": {**INLINE, "district": "Rubavu"}, "payment_method": "mtn_momo"}
    )
    assert res.status_code == 422 and code(res) == "delivery_unavailable"
    res = checkout(
        client,
        h,
        {"address": {**INLINE, "district": "Kicukiro"}, "payment_method": "cash_on_delivery"},
    )
    assert res.status_code == 422  # Kicukiro has no cash on delivery here
    ok = checkout(
        client, h, {"address": {**INLINE, "district": "Kicukiro"}, "payment_method": "mtn_momo"}
    )
    assert ok.status_code == 201
    assert ok.json()["payment_methods_available"] == ["mtn_momo", "airtel_money"]
    assert ok.json()["order"]["delivery_fee"] == 1500


def test_delivery_configuration_failure_is_503(client, db, admin_auth):
    create_zone(client, admin_auth["headers"], "Gasabo", 2000)  # no threshold configured
    res = checkout(client, guest_cart(client, db))
    assert res.status_code == 503 and code(res) == "delivery_quote_unavailable"
    assert count(db, Order) == 0


def test_the_header_is_required(client, db, delivery):
    h = guest_cart(client, db)
    body = {"address": INLINE, "payment_method": "mtn_momo"}
    assert client.post(CHECKOUT, json=body, headers=h).status_code == 422
    assert (
        client.post(CHECKOUT, json=body, headers={**h, "Idempotency-Key": "short"}).status_code
        == 422
    )


# ---- cart state ----------------------------------------------------------------------------
def test_no_cart_empty_cart_and_flagged_lines(client, db, customer_auth, delivery):
    h = customer_auth["headers"]
    res = checkout(client, h)
    assert res.status_code == 404 and code(res) == "cart_not_found"
    assert checkout(client, {"X-Cart-Token": "z" * 43}).status_code == 404
    line = add(client, sku(db), 1, h).json()["lines"][0]["id"]
    client.delete(f"/api/v1/cart/items/{line}", headers=h)
    res = checkout(client, h)
    assert res.status_code == 409 and code(res) == "cart_empty"
    variant = sku(db, on_hand=3)
    add(client, variant, 3, h)
    db.execute(
        text("UPDATE inventory_balances SET on_hand = 1 WHERE variant_id = :v"), {"v": variant}
    )
    db.commit()
    res = checkout(client, h)
    assert res.status_code == 409 and code(res) == "cart_needs_attention"
    assert res.json()["error"]["details"] == [
        {"variant_id": variant, "status": "insufficient_stock"}
    ]
    db.execute(text("UPDATE product_variants SET is_active = false WHERE id = :v"), {"v": variant})
    db.commit()
    res = checkout(client, h)
    assert res.json()["error"]["details"][0]["status"] == "unavailable"
    assert count(db, Order) == 0


def test_a_changed_price_is_charged_at_the_current_price(client, db, delivery):
    variant = sku(db, price=10_000)
    created = add(client, variant, 1)
    h = guest(created.json()["cart_token"])
    db.execute(text("UPDATE product_variants SET price = 12_345 WHERE id = :v"), {"v": variant})
    db.commit()
    order = checkout(client, h).json()["order"]
    assert order["subtotal"] == 12_345 and order["lines"][0]["unit_price"] == 12_345


# ---- promotions ----------------------------------------------------------------------------
def test_a_promotion_is_snapshotted_allocated_and_redeemed(client, db, admin_auth, delivery):
    create_promotion(client, admin_auth["headers"], code="TENOFF", percent_off=10)
    first, second = sku(db, price=150_000), sku(db, price=55_000)
    h = guest(add(client, first, 1).json()["cart_token"])
    add(client, second, 1, h)
    apply(client, h, "TENOFF")
    order = checkout(client, h).json()["order"]
    # 205 000 - 20 500 = 184 500: below the 200 000 threshold after discount, so delivery is due
    assert (order["subtotal"], order["discount_total"]) == (205_000, 20_500)
    assert order["delivery_fee"] == 2000 and order["total"] == 186_500
    assert order["discount_code"] == "TENOFF"
    assert sum(line["discount_amount"] for line in order["lines"]) == 20_500
    assert {line["discount_amount"] for line in order["lines"]} == {15_000, 5_500}
    db.expire_all()
    redemption = db.scalar(select(DiscountRedemption))
    assert redemption is not None and redemption.status == "active" and redemption.amount == 20_500
    assert redemption.customer_phone == "+250788123456"
    stored = db.scalar(select(Order))
    assert stored is not None and stored.discount_rules_snapshot["percent_off"] == 10


def test_a_code_that_stopped_applying_refuses_checkout(client, db, admin_auth, delivery):
    promo = create_promotion(client, admin_auth["headers"], code="SHORTLIVED")
    h = guest_cart(client, db)
    apply(client, h, "SHORTLIVED")
    client.patch(
        f"/api/v1/staff/promotions/{promo['id']}",
        json={"status": "disabled"},
        headers=admin_auth["headers"],
    )
    res = checkout(client, h)
    assert res.status_code == 422 and code(res) == "promotion_not_applicable"
    assert res.json()["error"]["details"][0]["reason"] == "not_active"
    assert count(db, Order) == 0 and count(db, DiscountRedemption) == 0


def test_an_exhausted_limit_refuses_checkout(client, db, admin_auth, delivery):
    create_promotion(client, admin_auth["headers"], code="ONLYONE", usage_limit_total=1)
    first, second = guest_cart(client, db), guest_cart(client, db)
    apply(client, first, "ONLYONE")
    apply(client, second, "ONLYONE")
    assert checkout(client, first).status_code == 201
    res = checkout(client, second)
    assert res.status_code == 422 and res.json()["error"]["details"][0]["reason"] == (
        "usage_limit_reached"
    )
    assert count(db, Order) == 1 and count(db, DiscountRedemption) == 1


# ---- idempotency ---------------------------------------------------------------------------
def test_a_retry_replays_the_order_and_writes_nothing(client, db, customer_auth, delivery):
    h = customer_auth["headers"]
    add(client, sku(db), 1, h)
    idem = key()
    first = checkout(client, h, idem=idem)
    again = checkout(client, h, idem=idem)
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["replayed"] is True
    assert again.json()["order"]["id"] == first.json()["order"]["id"]
    assert count(db, Order) == 1 and count(db, StockReservation) == 1
    assert count(db, PaymentAttempt) == 1
    changed = checkout(client, h, {"address": INLINE, "payment_method": "mtn_momo"}, idem=idem)
    assert changed.status_code == 409 and code(changed) == "idempotency_key_reused"


def test_keys_are_scoped_to_their_owner(client, db, customer_auth, second_customer_auth, delivery):
    shared = {"Idempotency-Key": "the-same-key-123"}
    for auth in (customer_auth, second_customer_auth):
        add(client, sku(db), 1, auth["headers"])
        assert checkout(client, auth["headers"], idem=shared).status_code == 201
    assert count(db, Order) == 2  # neither replays the other's order


def test_a_guest_retry_after_the_cart_closed_still_replays(client, db, delivery):
    h = guest_cart(client, db)
    idem = key()
    first = checkout(client, h, idem=idem).json()["order"]["id"]
    assert checkout(client, h, idem=idem).json()["order"]["id"] == first


# ---- atomicity -----------------------------------------------------------------------------
def test_a_failure_late_in_checkout_writes_nothing(client, db, admin_auth, delivery, monkeypatch):
    create_promotion(client, admin_auth["headers"], code="ROLLBACK")
    h = guest_cart(client, db)
    apply(client, h, "ROLLBACK")

    def fail(*args, **kwargs):
        raise RuntimeError("simulated failure after the reservations")

    monkeypatch.setattr(checkout_service.promotion_service, "redeem", fail)
    with pytest.raises(RuntimeError, match="simulated"):
        checkout(client, h)
    for model in (
        Order,
        OrderItem,
        StockReservation,
        DiscountRedemption,
        OrderStatusHistory,
        PaymentAttempt,
    ):
        assert count(db, model) == 0, model
    assert db.scalar(select(Cart.status)) == "active"


# ---- TC-14 and §7 Q12-Q14: cancellation, COD, expiry ----------------------------------------
def placed(client, db, admin_auth, method="cash_on_delivery", with_code=True) -> tuple[dict, str]:
    variant = sku(db, price=10_000, on_hand=1)
    h = guest(add(client, variant, 1).json()["cart_token"])
    if with_code:
        create_promotion(client, admin_auth["headers"], code=f"C{uuid.uuid4().hex[:6].upper()}")
        promo_code = db.scalar(text("SELECT code FROM discounts ORDER BY created_at DESC LIMIT 1"))
        apply(client, h, promo_code)
    res = checkout(client, h, {"address": INLINE, "payment_method": method})
    assert res.status_code == 201, res.text
    return res.json()["order"], variant


def available(db: Session, variant: str) -> int:
    db.expire_all()
    on_hand = db.scalar(
        select(InventoryBalance.on_hand).where(InventoryBalance.variant_id == uuid.UUID(variant))
    )
    held = db.scalar(
        select(func.coalesce(func.sum(StockReservation.quantity), 0)).where(
            StockReservation.variant_id == uuid.UUID(variant),
            StockReservation.status.in_(("active", "committed")),
        )
    )
    return int(on_hand or 0) - int(held or 0)


def test_tc14_cancellation_releases_stock_and_code_exactly_once(
    client, db, admin_auth, operations_auth, delivery
):
    order, variant = placed(client, db, admin_auth)
    assert available(db, variant) == 0
    url = f"{STAFF}/{order['id']}/status"
    res = client.patch(
        url,
        json={"status": "cancelled", "reason": "Customer called"},
        headers=operations_auth["headers"],
    )
    assert res.status_code == 200, res.text
    assert available(db, variant) == 1
    db.expire_all()
    assert db.scalar(select(DiscountRedemption.status)) == "released"
    assert db.scalar(select(PaymentAttempt.status)) == "cancelled"
    history = db.scalars(
        select(OrderStatusHistory.reason).where(OrderStatusHistory.status == "cancelled")
    ).all()
    assert history == ["Customer called"]
    again = client.patch(url, json={"status": "cancelled"}, headers=operations_auth["headers"])
    assert again.status_code == 409 and code(again) == "invalid_transition"
    assert available(db, variant) == 1
    assert (
        len(
            db.scalars(
                select(AuditRecord).where(AuditRecord.action == "promotion.redemption_release")
            ).all()
        )
        == 1
    )


def test_q13_confirming_cod_commits_stock_so_it_can_no_longer_be_cancelled(
    client, db, admin_auth, operations_auth, delivery
):
    order, variant = placed(client, db, admin_auth, with_code=False)
    h = operations_auth["headers"]
    url = f"{STAFF}/{order['id']}/status"
    assert client.patch(url, json={"status": "confirmed"}, headers=h).status_code == 200
    db.expire_all()
    assert db.scalar(select(StockReservation.status)) == "committed"
    res = client.patch(url, json={"status": "cancelled"}, headers=h)
    assert res.status_code == 409  # committed stock is never released (ADR-002)
    assert available(db, variant) == 0


def test_q14_delivering_cod_marks_the_payment_succeeded(
    client, db, admin_auth, operations_auth, delivery
):
    order, _ = placed(client, db, admin_auth, with_code=False)
    h = operations_auth["headers"]
    url = f"{STAFF}/{order['id']}/status"
    for status in ("confirmed", "processing", "dispatched"):
        assert client.patch(url, json={"status": status}, headers=h).status_code == 200, status
        db.expire_all()
        assert db.scalar(select(PaymentAttempt.status)) == "pending"  # not paid before delivery
    assert client.patch(url, json={"status": "delivered"}, headers=h).status_code == 200
    db.expire_all()
    attempt = db.scalar(select(PaymentAttempt))
    assert attempt is not None and attempt.status == "succeeded" and attempt.succeeded_at
    assert client.patch(url, json={"status": "cancelled"}, headers=h).status_code == 409  # cutoff


def test_q12_an_expired_unpaid_order_is_cancelled_with_its_code_released(
    client, db, admin_auth, delivery, monkeypatch
):
    # Holds are immutable apart from their status (database trigger), so the hold is made short
    # instead of backdated; the 15-minute value itself is checked above.
    monkeypatch.setitem(checkout_service.HOLDS, "mtn_momo", timedelta(seconds=1))
    order, variant = placed(client, db, admin_auth, method="mtn_momo")
    wait_until_due()
    assert expire_due_reservations(db).orders == 1
    db.expire_all()
    stored = db.get(Order, uuid.UUID(order["id"]))
    assert stored is not None and stored.status == "cancelled"
    reason = db.scalar(
        select(OrderStatusHistory.reason).where(OrderStatusHistory.status == "cancelled")
    )
    assert reason == "payment_timeout"
    assert db.scalar(select(PaymentAttempt.status)) == "expired"
    assert db.scalar(select(DiscountRedemption.release_reason)) == "expired"
    assert available(db, variant) == 1
    assert expire_due_reservations(db).orders == 0


# ---- guest lookup and ownership ------------------------------------------------------------
def test_guest_lookup_needs_the_number_and_the_phone(client, db, delivery):
    order = checkout(client, guest_cart(client, db)).json()["order"]
    ok = client.post(
        LOOKUP, json={"order_number": order["order_number"].lower(), "phone": "+250788123456"}
    )
    assert ok.status_code == 200 and ok.json()["id"] == order["id"]
    wrong_phone = client.post(
        LOOKUP, json={"order_number": order["order_number"], "phone": "0788999999"}
    )
    unknown = client.post(LOOKUP, json={"order_number": "ORD-000000-ZZZZZZ", "phone": "0788123456"})
    assert wrong_phone.status_code == unknown.status_code == 404
    assert wrong_phone.json() == unknown.json()  # nothing reveals that the number exists
    assert client.post(LOOKUP, json={"order_number": "x", "phone": "nope"}).status_code == 422


def test_customers_see_only_their_own_orders(
    client, db, customer_auth, second_customer_auth, delivery
):
    a, b = customer_auth["headers"], second_customer_auth["headers"]
    add(client, sku(db), 1, a)
    order = checkout(client, a).json()["order"]
    assert client.get(f"{HISTORY}/{order['id']}", headers=b).status_code == 404
    assert client.get(HISTORY, headers=b).json()["total"] == 0
    assert client.get(HISTORY).status_code == 401


# ---- staff ---------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("who", "expected"),
    [
        ("admin_auth", 200),
        ("sales_auth", 200),
        ("operations_auth", 200),
        ("finance_auth", 200),
        ("management_auth", 200),  # orders:read since 2026-10-26
        ("customer_auth", 403),
        (None, 401),
    ],
)
def test_staff_order_read_permissions(client, db, request, delivery, who, expected):
    order = checkout(client, guest_cart(client, db)).json()["order"]
    headers = request.getfixturevalue(who)["headers"] if who else {}
    assert client.get(STAFF, headers=headers).status_code == expected
    assert client.get(f"{STAFF}/{order['id']}", headers=headers).status_code == expected


def test_staff_list_filters_and_detail(client, db, admin_auth, operations_auth, delivery):
    h = admin_auth["headers"]
    cod = checkout(client, guest_cart(client, db)).json()["order"]
    momo = checkout(
        client, guest_cart(client, db), {"address": INLINE, "payment_method": "mtn_momo"}
    ).json()["order"]
    client.patch(
        f"{STAFF}/{momo['id']}/status",
        json={"status": "cancelled"},
        headers=operations_auth["headers"],
    )

    def ids(**params):
        return {o["id"] for o in client.get(STAFF, params=params, headers=h).json()["items"]}

    assert ids() == {cod["id"], momo["id"]}
    assert ids(status="cancelled") == {momo["id"]}
    assert ids(payment_status="pending") == {cod["id"]}
    assert ids(payment_status="cancelled") == {momo["id"]}
    assert ids(**{"from": "2000-01-01T00:00:00Z", "to": "2000-01-02T00:00:00Z"}) == set()
    bad = client.get(
        STAFF, params={"from": "2030-01-02T00:00:00Z", "to": "2030-01-01T00:00:00Z"}, headers=h
    )
    assert bad.status_code == 422
    assert client.get(STAFF, params={"status": "lost"}, headers=h).status_code == 422
    detail = client.get(f"{STAFF}/{cod['id']}", headers=h).json()
    assert detail["user_id"] is None and detail["payments"][0]["method"] == "cash_on_delivery"
    assert "provider_reference" not in str(detail) and "idempotency" not in str(detail)
    assert client.get(f"{STAFF}/{uuid.uuid4()}", headers=h).status_code == 404


def test_sales_can_read_but_not_change_order_status(client, db, sales_auth, delivery):
    order = checkout(client, guest_cart(client, db)).json()["order"]
    res = client.patch(
        f"{STAFF}/{order['id']}/status", json={"status": "confirmed"}, headers=sales_auth["headers"]
    )
    assert res.status_code == 403
    long_reason = {"status": "cancelled", "reason": "x" * 501}
    assert client.patch(
        f"{STAFF}/{order['id']}/status", json=long_reason, headers=sales_auth["headers"]
    ).status_code in (403, 422)


def test_order_numbers_are_random_not_sequential(client, db, delivery):
    numbers = {
        checkout(client, guest_cart(client, db)).json()["order"]["order_number"] for _ in range(3)
    }
    assert len(numbers) == 3 and all(ORDER_NUMBER.match(n) for n in numbers)


# ---- D-O2: mobile money is never shown as paid before the payments module ------------------
def test_mobile_money_orders_stay_unpaid_and_cannot_be_dispatched(
    client, db, admin_auth, operations_auth, delivery
):
    res = checkout(
        client, guest_cart(client, db), {"address": INLINE, "payment_method": "mtn_momo"}
    )
    order = res.json()["order"]
    assert order["payment"]["status"] == "created"  # not started: no provider exists yet
    h = operations_auth["headers"]
    url = f"{STAFF}/{order['id']}/status"
    assert client.patch(url, json={"status": "confirmed"}, headers=h).status_code == 200
    assert client.patch(url, json={"status": "processing"}, headers=h).status_code == 200
    blocked = client.patch(url, json={"status": "dispatched"}, headers=h)
    assert blocked.status_code == 409  # no committed (paid) stock to dispatch
    detail = client.get(f"{STAFF}/{order['id']}", headers=admin_auth["headers"]).json()
    assert [p["status"] for p in detail["payments"]] == ["created"]
    assert detail["payments"][0]["succeeded_at"] is None
    db.expire_all()
    assert db.scalar(select(StockReservation.status)) == "active"  # still a lapsing hold
