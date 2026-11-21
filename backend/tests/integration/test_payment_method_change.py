"""Switching an unpaid order's payment method (frontend phase 4, decisions 2 and 2a of
2026-10-27): POST /payments/{order_number}/method. The hold follows the new method from the
order's creation (§7 Q11, Q13), within the database's 24-hour cap (migration a8d2f6c1e3b7).
Disposable per-test PostgreSQL schema (tests/conftest.py)."""

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Order, PaymentAttempt, StockReservation
from app.models.operations import AuditRecord
from app.services import checkout_service
from tests.integration.test_cart_api import code
from tests.integration.test_checkout_api import INLINE, checkout, guest_cart
from tests.integration.test_delivery_api import create_zone, set_threshold
from tests.integration.test_payments_api import PAY, PHONE, event, initiate, webhook
from tests.support.commerce import wait_until_due


@pytest.fixture
def delivery(client, admin_auth) -> None:
    h = admin_auth["headers"]
    create_zone(client, h, "Gasabo", 2000)
    create_zone(client, h, "Kicukiro", 1500, cod_available=False)
    set_threshold(client, h, 10**9)


def place(client: TestClient, db: Session, method: str, district: str = "gasabo") -> dict:
    res = checkout(
        client,
        guest_cart(client, db),
        {"address": {**INLINE, "district": district}, "payment_method": method},
    )
    assert res.status_code == 201, res.text
    return res.json()["order"]


def switch(
    client: TestClient, number: str, method: str, *, phone: str | None = PHONE, headers=None
):
    body = {"payment_method": method, **({"phone": phone} if phone else {})}
    return client.post(f"{PAY}/{number}/method", json=body, headers=headers or {})


def hold(db: Session, order: dict) -> timedelta:
    """How long after the order's creation its active holds lapse."""
    db.expire_all()
    expires = db.scalar(
        select(StockReservation.expires_at).where(
            StockReservation.order_id == uuid.UUID(order["id"]),
            StockReservation.status == "active",
        )
    )
    created = db.scalar(select(Order.created_at).where(Order.id == uuid.UUID(order["id"])))
    assert expires is not None and created is not None
    return expires - created


def attempts(db: Session, order: dict) -> list[tuple[str, str]]:
    db.expire_all()
    return [
        (method, status)
        for method, status in db.execute(
            select(PaymentAttempt.method, PaymentAttempt.status)
            .where(PaymentAttempt.order_id == uuid.UUID(order["id"]))
            .order_by(PaymentAttempt.created_at, PaymentAttempt.id)
        ).all()
    ]


def test_a_failed_mobile_money_payment_switches_to_cash_on_delivery(client, db, delivery):
    order = place(client, db, "mtn_momo")
    started = initiate(client, order["order_number"]).json()
    failed = webhook(client, event(started["reference"], "failed", order["total"]))
    assert failed.status_code == 200
    assert hold(db, order) <= timedelta(minutes=15, seconds=5)

    res = switch(client, order["order_number"], "cash_on_delivery")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["method"] == "cash_on_delivery" and body["status"] == "pending"
    assert body["amount"] == order["total"] and body["reservation_expires_at"] is not None
    # The hold now follows the cash-on-delivery rule from the order's creation.
    assert timedelta(hours=24) - timedelta(seconds=5) < hold(db, order) <= timedelta(hours=24)
    assert attempts(db, order) == [("mtn_momo", "failed"), ("cash_on_delivery", "pending")]
    audit = db.scalar(select(AuditRecord).where(AuditRecord.action == "payment.method_change"))
    assert audit is not None and audit.change_summary["from"] == "mtn_momo"
    assert audit.change_summary["to"] == "cash_on_delivery"
    moved = db.scalar(
        select(AuditRecord).where(AuditRecord.action == "inventory.reservation_hold_change")
    )
    assert moved is not None


def test_cash_on_delivery_switches_to_mobile_money_and_pays(client, db, delivery):
    order = place(client, db, "cash_on_delivery")
    res = switch(client, order["order_number"], "airtel_money")
    assert res.status_code == 200, res.text
    assert res.json()["method"] == "airtel_money" and res.json()["status"] == "created"
    assert hold(db, order) <= timedelta(minutes=15, seconds=5)
    assert attempts(db, order) == [
        ("cash_on_delivery", "cancelled"),
        ("airtel_money", "created"),
    ]
    started = initiate(client, order["order_number"])
    assert started.status_code == 200 and started.json()["status"] == "pending"
    paid = webhook(client, event(started.json()["reference"], "succeeded", order["total"]))
    assert paid.status_code == 200 and paid.json()["status"] == "processed"
    db.expire_all()
    assert attempts(db, order)[-1] == ("airtel_money", "succeeded")


def test_the_same_method_changes_nothing(client, db, delivery):
    order = place(client, db, "mtn_momo")
    res = switch(client, order["order_number"], "mtn_momo")
    assert res.status_code == 200 and res.json()["method"] == "mtn_momo"
    assert attempts(db, order) == [("mtn_momo", "created")]


def test_an_open_mobile_money_request_blocks_switching(client, db, delivery):
    order = place(client, db, "mtn_momo")
    assert initiate(client, order["order_number"]).json()["status"] == "pending"
    res = switch(client, order["order_number"], "cash_on_delivery")
    assert res.status_code == 409 and code(res) == "payment_in_progress"
    assert attempts(db, order) == [("mtn_momo", "pending")]


def test_a_paid_order_cannot_switch(client, db, delivery):
    order = place(client, db, "mtn_momo")
    started = initiate(client, order["order_number"]).json()
    webhook(client, event(started["reference"], "succeeded", order["total"]))
    res = switch(client, order["order_number"], "cash_on_delivery")
    assert res.status_code == 409 and code(res) == "payment_already_succeeded"


def test_card_and_cash_where_the_zone_has_none_are_refused(client, db, delivery):
    order = place(client, db, "mtn_momo", district="kicukiro")
    res = switch(client, order["order_number"], "cash_on_delivery")
    assert res.status_code == 422 and res.json()["error"]["details"][0]["loc"] == [
        "body",
        "payment_method",
    ]
    card = switch(client, order["order_number"], "card")
    assert card.status_code == 422
    assert attempts(db, order) == [("mtn_momo", "created")]


def test_mobile_money_after_its_15_minutes_is_too_late(client, db, delivery, monkeypatch):
    # Waiting 15 minutes is not practical: the mobile-money hold is made one second long.
    monkeypatch.setitem(checkout_service.HOLDS, "mtn_momo", timedelta(seconds=1))
    order = place(client, db, "cash_on_delivery")
    wait_until_due()
    res = switch(client, order["order_number"], "mtn_momo")
    assert res.status_code == 409 and code(res) == "payment_method_change_too_late"
    assert attempts(db, order) == [("cash_on_delivery", "pending")]
    assert hold(db, order) > timedelta(hours=23)


def test_an_expired_hold_cannot_be_revived(client, db, delivery, monkeypatch):
    monkeypatch.setitem(checkout_service.HOLDS, "mtn_momo", timedelta(seconds=1))
    order = place(client, db, "mtn_momo")
    wait_until_due()
    res = switch(client, order["order_number"], "cash_on_delivery")
    assert res.status_code == 409 and code(res) == "order_not_payable"


def test_guests_prove_the_order_with_its_phone(client, db, delivery, customer_auth):
    order = place(client, db, "cash_on_delivery")
    wrong = switch(client, order["order_number"], "mtn_momo", phone="0788999999")
    assert wrong.status_code == 404 and code(wrong) == "order_not_found"
    missing = switch(client, order["order_number"], "mtn_momo", phone=None)
    assert missing.status_code == 422
    other = switch(
        client, order["order_number"], "mtn_momo", phone=None, headers=customer_auth["headers"]
    )
    assert other.status_code == 404  # not this customer's order
    assert attempts(db, order) == [("cash_on_delivery", "pending")]


def test_unknown_fields_are_refused(client, db, delivery):
    order = place(client, db, "cash_on_delivery")
    res = client.post(
        f"{PAY}/{order['order_number']}/method",
        json={"payment_method": "mtn_momo", "phone": PHONE, "amount": 1},
    )
    assert res.status_code == 422
