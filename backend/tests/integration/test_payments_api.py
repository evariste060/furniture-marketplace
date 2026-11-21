"""Module 15 — payments (TC-08-TC-12; ADR-002; §7 Q11-Q14, Q17, Q21). Disposable per-test
PostgreSQL schema (tests/conftest.py). The mock provider's secret is the test-only value set in
tests/conftest.py."""

import hashlib
import json
import os
import time
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.payments import ProviderError
from app.integrations.payments.mock import MockProvider, sign
from app.models import DiscountRedemption, Order, PaymentAttempt, PaymentEvent, StockReservation
from app.models.operations import AuditRecord
from app.services import checkout_service, payment_service
from app.services.inventory import expire_due_reservations
from tests.integration.test_cart_api import code
from tests.integration.test_checkout_api import INLINE, STAFF, checkout, guest_cart
from tests.integration.test_delivery_api import create_zone, set_threshold
from tests.integration.test_promotions_api import apply, create_promotion
from tests.support.commerce import hold_expiry, stock_clock_at, wait_until_due

SECRET = os.environ["PAYMENT_MOCK_WEBHOOK_SECRET"]
PAY = "/api/v1/payments"
HOOK = "/api/v1/webhooks"
STAFF_PAYMENTS = "/api/v1/staff/payments"
PHONE = "0788123456"


@pytest.fixture
def delivery(client, admin_auth) -> None:
    create_zone(client, admin_auth["headers"], "Gasabo", 2000)
    set_threshold(client, admin_auth["headers"], 10**9)


def momo_order(client: TestClient, db: Session, headers: dict | None = None) -> dict:
    h = headers or guest_cart(client, db)
    if headers is not None:
        from tests.integration.test_cart_api import add, sku

        add(client, sku(db, price=10_000), 1, headers)
    res = checkout(client, h, {"address": INLINE, "payment_method": "mtn_momo"})
    assert res.status_code == 201, res.text
    return res.json()["order"]


def initiate(client: TestClient, number: str, *, phone: str | None = PHONE, headers=None):
    body = {"phone": phone} if phone is not None else None
    return client.post(f"{PAY}/{number}/initiate", json=body, headers=headers or {})


def status(client: TestClient, number: str, *, phone: str | None = PHONE, headers=None):
    h = {**(headers or {}), **({"X-Order-Phone": phone} if phone else {})}
    return client.get(f"{PAY}/{number}/status", headers=h)


def webhook(
    client: TestClient,
    body: dict,
    *,
    secret: str = SECRET,
    ts: int | None = None,
    provider: str = "mock",
    raw: bytes | None = None,
):
    payload = raw if raw is not None else json.dumps(body).encode()
    stamp = ts if ts is not None else int(time.time())
    return client.post(
        f"{HOOK}/{provider}",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-Mock-Timestamp": str(stamp),
            "X-Mock-Signature": sign(payload, stamp, secret),
        },
    )


def event(reference: str, status_: str, amount: int, **extra) -> dict:
    return {
        "event_id": f"evt-{uuid.uuid4().hex}",
        "reference": reference,
        "status": status_,
        "amount": amount,
        "currency": "RWF",
        **extra,
    }


def started(client, db) -> tuple[dict, dict]:
    order = momo_order(client, db)
    res = initiate(client, order["order_number"])
    assert res.status_code == 200, res.text
    return order, res.json()


def holds(db: Session, order_id: str) -> set[str]:
    db.expire_all()
    return set(
        db.scalars(
            select(StockReservation.status).where(StockReservation.order_id == uuid.UUID(order_id))
        )
    )


def events(db: Session) -> list[PaymentEvent]:
    db.expire_all()
    return list(db.scalars(select(PaymentEvent).order_by(PaymentEvent.received_at)))


# ---- initiation and status -----------------------------------------------------------------
def test_a_guest_initiates_mobile_money_through_the_mock_and_reads_the_status(client, db, delivery):
    order, body = started(client, db)
    assert body["status"] == "pending" and body["provider"] == "mock"
    assert body["reference"].startswith("MOCK-") and "no real mobile-money" in body["instructions"]
    assert body["amount"] == order["total"] and body["currency_code"] == "RWF"
    again = initiate(client, order["order_number"])
    assert again.json()["reference"] == body["reference"]  # idempotent while pending
    assert status(client, order["order_number"]).json()["status"] == "pending"
    db.expire_all()
    assert db.scalar(select(func.count(PaymentAttempt.id))) == 1


def test_customers_pay_only_their_own_orders(
    client, db, delivery, customer_auth, second_customer_auth
):
    order = momo_order(client, db, customer_auth["headers"])
    res = initiate(client, order["order_number"], phone=None, headers=customer_auth["headers"])
    assert res.status_code == 200 and res.json()["status"] == "pending"
    other = initiate(
        client, order["order_number"], phone=None, headers=second_customer_auth["headers"]
    )
    assert other.status_code == 404 and code(other) == "order_not_found"
    assert (
        status(
            client, order["order_number"], phone=None, headers=second_customer_auth["headers"]
        ).status_code
        == 404
    )


def test_guest_access_needs_the_orders_phone_and_mismatches_look_alike(client, db, delivery):
    order = momo_order(client, db)
    wrong = initiate(client, order["order_number"], phone="0788999999")
    unknown = initiate(client, "ORD-000000-ZZZZZZ")
    assert wrong.status_code == unknown.status_code == 404 and wrong.json() == unknown.json()
    assert initiate(client, order["order_number"], phone=None).status_code == 422
    assert status(client, order["order_number"], phone=None).status_code == 422
    assert status(client, order["order_number"], phone="nope").status_code == 422


def test_guest_failures_count_on_the_lookup_limits(client, db, delivery):
    order = momo_order(client, db)
    for _ in range(5):  # ADR-008 S6: 5 failures per order number
        assert status(client, order["order_number"], phone="0788999999").status_code == 404
    blocked = initiate(client, order["order_number"])
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) > 0


def test_closed_or_lapsed_orders_cannot_be_paid(client, db, delivery, operations_auth, monkeypatch):
    order = momo_order(client, db)
    client.patch(
        f"{STAFF}/{order['id']}/status",
        json={"status": "cancelled"},
        headers=operations_auth["headers"],
    )
    res = initiate(client, order["order_number"])
    assert res.status_code == 409 and code(res) == "order_not_payable"
    monkeypatch.setitem(checkout_service.HOLDS, "mtn_momo", timedelta(seconds=1))
    lapsed = momo_order(client, db)
    wait_until_due()
    res = initiate(client, lapsed["order_number"])
    assert res.status_code == 409 and code(res) == "order_not_payable"


def test_a_provider_error_fails_the_attempt_and_a_retry_starts_a_new_one(
    client, db, delivery, monkeypatch
):
    order = momo_order(client, db)

    def refuse(self, snapshot):
        raise ProviderError("down")

    monkeypatch.setattr(MockProvider, "initiate", refuse)
    res = initiate(client, order["order_number"])
    assert res.status_code == 502 and code(res) == "payment_provider_error"
    db.expire_all()
    assert db.scalar(select(PaymentAttempt.status)) == "failed"
    monkeypatch.undo()
    retry = initiate(client, order["order_number"])
    assert retry.status_code == 200 and retry.json()["status"] == "pending"
    db.expire_all()
    assert sorted(db.scalars(select(PaymentAttempt.status))) == [
        "failed",
        "pending",
    ]  # history kept


def test_an_unconfigured_mock_answers_503(client, db, delivery, monkeypatch):
    order = momo_order(client, db)
    monkeypatch.setenv("PAYMENT_MOCK_WEBHOOK_SECRET", "")
    get_settings.cache_clear()
    try:
        res = initiate(client, order["order_number"])
        assert res.status_code == 503 and code(res) == "payment_provider_unavailable"
        assert webhook(client, event("MOCK-XXXXXX", "succeeded", 1)).status_code == 503
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


# ---- webhooks: verified outcomes -----------------------------------------------------------
def test_a_verified_success_commits_the_stock_and_marks_the_payment_paid(client, db, delivery):
    order, body = started(client, db)
    res = webhook(client, event(body["reference"], "succeeded", order["total"]))
    assert res.status_code == 200 and res.json() == {"received": True, "status": "processed"}
    assert holds(db, order["id"]) == {"committed"}
    assert status(client, order["order_number"]).json()["status"] == "succeeded"
    again = initiate(client, order["order_number"])
    assert again.status_code == 409 and code(again) == "payment_already_succeeded"
    db.expire_all()
    stored = db.get(Order, uuid.UUID(order["id"]))
    assert stored is not None and stored.status == "received"  # payment never changes fulfilment


def test_a_duplicate_event_is_acknowledged_and_repeats_nothing(client, db, delivery):
    order, body = started(client, db)
    payload = event(body["reference"], "succeeded", order["total"])
    assert webhook(client, payload).json()["status"] == "processed"
    dup = webhook(client, payload)
    assert dup.status_code == 200 and dup.json()["status"] == "duplicate"
    assert len(events(db)) == 1
    commits = db.scalar(
        select(func.count(AuditRecord.id)).where(
            AuditRecord.action == "inventory.reservation_commit"
        )
    )
    assert commits == 1


@pytest.mark.parametrize("outcome", ["failed", "cancelled"])
def test_failure_and_cancellation_keep_the_hold_for_a_retry(client, db, delivery, outcome):
    order, body = started(client, db)
    assert (
        webhook(client, event(body["reference"], outcome, order["total"])).json()["status"]
        == "processed"
    )
    assert status(client, order["order_number"]).json()["status"] == outcome
    assert holds(db, order["id"]) == {"active"}  # D-Y2: the customer may retry until it lapses
    retry = initiate(client, order["order_number"]).json()
    assert retry["status"] == "pending" and retry["reference"] != body["reference"]
    assert (
        webhook(client, event(retry["reference"], "succeeded", order["total"])).json()["status"]
        == "processed"
    )
    assert holds(db, order["id"]) == {"committed"}


def test_a_delayed_outcome_stays_pending_until_the_final_event(client, db, delivery):
    order, body = started(client, db)
    assert (
        webhook(client, event(body["reference"], "pending", order["total"])).json()["status"]
        == "processed"
    )
    assert status(client, order["order_number"]).json()["status"] == "pending"
    assert holds(db, order["id"]) == {"active"}
    webhook(client, event(body["reference"], "succeeded", order["total"]))
    assert status(client, order["order_number"]).json()["status"] == "succeeded"


def test_a_success_never_regresses_on_a_later_failure(client, db, delivery):
    order, body = started(client, db)
    webhook(client, event(body["reference"], "succeeded", order["total"]))
    late = webhook(client, event(body["reference"], "failed", order["total"]))
    assert late.status_code == 200 and late.json()["status"] == "processed"
    assert status(client, order["order_number"]).json()["status"] == "succeeded"
    assert holds(db, order["id"]) == {"committed"}
    assert events(db)[-1].result_summary == "failed ignored: already succeeded"


@pytest.mark.parametrize("change", [{"amount": 1}, {"currency": "USD"}])
def test_a_mismatched_success_needs_reconciliation_and_changes_nothing(
    client, db, delivery, admin_auth, change
):
    order, body = started(client, db)
    res = webhook(client, {**event(body["reference"], "succeeded", order["total"]), **change})
    assert res.status_code == 200 and res.json()["status"] == "needs_reconciliation"
    assert status(client, order["order_number"]).json()["status"] == "pending"
    assert holds(db, order["id"]) == {"active"}
    flagged = client.get(
        STAFF_PAYMENTS, params={"needs_reconciliation": "true"}, headers=admin_auth["headers"]
    ).json()
    assert [p["order_number"] for p in flagged["items"]] == [order["order_number"]]
    assert flagged["amount_total"] == order["total"]


def test_the_staff_list_sums_every_matching_attempt(client, db, delivery, admin_auth):
    first, _ = started(client, db)
    second, _ = started(client, db)
    page = client.get(
        STAFF_PAYMENTS, params={"size": 1, "method": "mtn_momo"}, headers=admin_auth["headers"]
    ).json()
    assert page["total"] == 2 and len(page["items"]) == 1
    assert page["amount_total"] == first["total"] + second["total"]
    none = client.get(
        STAFF_PAYMENTS, params={"status": "refunded"}, headers=admin_auth["headers"]
    ).json()
    assert none["total"] == 0 and none["amount_total"] == 0


def test_an_unknown_reference_is_kept_for_reconciliation(client, db, delivery):
    res = webhook(client, event("MOCK-UNKNOWN-REF", "succeeded", 1000))
    assert res.status_code == 200 and res.json()["status"] == "needs_reconciliation"
    [stored] = events(db)
    assert stored.attempt_id is None and stored.result_summary == "unknown reference"


def test_a_late_success_after_expiry_needs_reconciliation(
    client, db, admin_auth, delivery, monkeypatch
):
    """ADR-002: nothing is committed or re-reserved; the order is not marked paid."""
    create_promotion(client, admin_auth["headers"], code="LATEPAY", kind="fixed", amount_off=100)
    h = guest_cart(client, db)
    apply(client, h, "LATEPAY")
    order = checkout(client, h, {"address": INLINE, "payment_method": "mtn_momo"}).json()["order"]
    begun = initiate(client, order["order_number"])  # the normal hold: always still valid here
    assert begun.status_code == 200 and begun.json()["status"] == "pending", begun.text
    reference = begun.json()["reference"]  # the provider was called and started a payment
    expires = hold_expiry(db, uuid.UUID(order["id"]))
    assert expires is not None
    with stock_clock_at(monkeypatch, expires):  # due, but the expiry job has not run yet
        res = webhook(client, event(reference, "succeeded", order["total"]))
    assert res.status_code == 200 and res.json()["status"] == "needs_reconciliation"
    assert holds(db, order["id"]) == {"expired"}
    db.expire_all()
    stored = db.get(Order, uuid.UUID(order["id"]))
    assert stored is not None and stored.status == "cancelled"
    assert db.scalar(select(PaymentAttempt.status)) == "expired"  # never 'succeeded'
    assert db.scalar(select(DiscountRedemption.release_reason)) == "expired"
    assert events(db)[-1].result_summary == "late success: the stock hold had lapsed"
    assert expire_due_reservations(db).orders == 0


def test_a_success_after_the_expiry_job_ran_needs_reconciliation(client, db, delivery, monkeypatch):
    order = momo_order(client, db)
    begun = initiate(client, order["order_number"])  # the normal hold: always still valid here
    assert begun.status_code == 200 and begun.json()["status"] == "pending", begun.text
    reference = begun.json()["reference"]  # the provider was called and started a payment
    expires = hold_expiry(db, uuid.UUID(order["id"]))
    assert expires is not None
    with stock_clock_at(monkeypatch, expires):  # the expiry job runs once the hold is due
        assert expire_due_reservations(db).orders == 1
    res = webhook(client, event(reference, "succeeded", order["total"]))
    assert res.status_code == 200 and res.json()["status"] == "needs_reconciliation"
    assert holds(db, order["id"]) == {"expired"}
    assert events(db)[-1].result_summary == "late success: the stock hold had lapsed"
    db.expire_all()
    assert db.scalar(select(PaymentAttempt.status)) == "expired"  # never 'succeeded'
    assert status(client, order["order_number"]).json()["status"] == "expired"


# ---- webhooks: refused requests ------------------------------------------------------------
def test_forged_stale_and_unsigned_callbacks_store_nothing(client, db, delivery):
    order, body = started(client, db)
    payload = event(body["reference"], "succeeded", order["total"])
    forged = webhook(client, payload, secret="x" * 40)
    stale = webhook(client, payload, ts=int(time.time()) - 3600)
    unsigned = client.post(f"{HOOK}/mock", json=payload)
    assert [r.status_code for r in (forged, stale, unsigned)] == [401, 401, 401]
    assert code(forged) == "invalid_signature"
    assert events(db) == [] and holds(db, order["id"]) == {"active"}


def test_unknown_providers_cod_and_malformed_payloads(client, db, delivery):
    assert webhook(client, {}, provider="stripe").status_code == 404
    assert webhook(client, {}, provider="cod").status_code == 404  # cash on delivery has none
    for raw in (b"not json", b"[1]", json.dumps({"event_id": "evt-123456"}).encode()):
        res = webhook(client, {}, raw=raw)
        assert res.status_code == 422 and code(res) == "malformed_event"
    assert events(db) == []


def test_event_metadata_is_sanitised(client, db, delivery, admin_auth):
    order, body = started(client, db)
    payload = event(
        body["reference"],
        "succeeded",
        order["total"],
        payer_phone="+250788123456",
        card_number="4111111111111111",
        cvv="123",
        secret="s3cr3t",
    )
    raw = json.dumps(payload).encode()
    webhook(client, {}, raw=raw)
    [stored] = events(db)
    assert stored.payload_metadata["payer_phone_masked"] == "+250******456"
    assert {"card_number", "cvv", "secret", "payer_phone"}.isdisjoint(stored.payload_metadata)
    assert stored.payload_digest == hashlib.sha256(raw).hexdigest()
    listed = client.get(f"{STAFF_PAYMENTS}/events", headers=admin_auth["headers"]).text
    assert "788123456" not in listed and "4111" not in listed and "s3cr3t" not in listed


def test_a_failure_while_applying_rolls_everything_back(client, db, delivery, monkeypatch):
    order, body = started(client, db)
    payload = event(body["reference"], "succeeded", order["total"])

    def boom(*args, **kwargs):
        raise RuntimeError("simulated failure while committing")

    monkeypatch.setattr(payment_service, "commit_order_reservations", boom)
    with pytest.raises(RuntimeError, match="simulated"):
        webhook(client, payload)
    assert events(db) == []  # not recorded, so the provider's retry is processed
    assert holds(db, order["id"]) == {"active"}
    monkeypatch.undo()
    assert webhook(client, payload).json()["status"] == "processed"
    assert holds(db, order["id"]) == {"committed"}


# ---- cash on delivery (TC-12) --------------------------------------------------------------
def test_cash_on_delivery_stays_pending_until_delivery(
    client, db, delivery, admin_auth, operations_auth
):
    order = checkout(client, guest_cart(client, db)).json()["order"]
    res = initiate(client, order["order_number"])
    assert res.status_code == 200 and res.json()["provider"] == "cod"
    assert res.json()["status"] == "pending"  # never paid at order time
    db.expire_all()
    attempt = db.scalar(select(PaymentAttempt))
    assert attempt is not None
    confirm = f"{STAFF_PAYMENTS}/{attempt.id}/confirm-cod"
    early = client.post(confirm, headers=admin_auth["headers"])
    assert early.status_code == 409 and code(early) == "order_not_delivered"
    url = f"{STAFF}/{order['id']}/status"
    for step in ("confirmed", "processing", "dispatched", "delivered"):
        assert (
            client.patch(url, json={"status": step}, headers=operations_auth["headers"]).status_code
            == 200
        )
    done = client.post(confirm, headers=admin_auth["headers"])
    assert done.status_code == 200 and done.json()["status"] == "succeeded"  # Q14 already did it


def test_only_cod_payments_can_be_confirmed_as_cash(client, db, delivery, admin_auth):
    started(client, db)
    db.expire_all()
    attempt = db.scalar(select(PaymentAttempt))
    assert attempt is not None
    res = client.post(f"{STAFF_PAYMENTS}/{attempt.id}/confirm-cod", headers=admin_auth["headers"])
    assert res.status_code == 409 and code(res) == "payment_not_cod"
    assert (
        client.post(
            f"{STAFF_PAYMENTS}/{uuid.uuid4()}/confirm-cod", headers=admin_auth["headers"]
        ).status_code
        == 404
    )


# ---- staff ---------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("who", "read", "manage"),
    [
        ("admin_auth", 200, 409),
        ("management_auth", 200, 403),
        ("sales_auth", 403, 403),
        ("operations_auth", 403, 403),
        ("customer_auth", 403, 403),
        (None, 401, 401),
    ],
)
def test_payment_permissions(client, db, delivery, request, who, read, manage):
    started(client, db)
    db.expire_all()
    attempt = db.scalar(select(PaymentAttempt))
    assert attempt is not None
    headers = request.getfixturevalue(who)["headers"] if who else {}
    assert client.get(STAFF_PAYMENTS, headers=headers).status_code == read
    assert client.get(f"{STAFF_PAYMENTS}/events", headers=headers).status_code == read
    res = client.post(f"{STAFF_PAYMENTS}/{attempt.id}/confirm-cod", headers=headers)
    assert res.status_code == manage  # admin: allowed, but a mobile-money payment is refused


def test_the_staff_list_filters_and_shows_no_secrets(client, db, delivery, admin_auth):
    order, body = started(client, db)
    webhook(client, event(body["reference"], "succeeded", order["total"]))
    h = admin_auth["headers"]
    listed = client.get(STAFF_PAYMENTS, params={"status": "succeeded"}, headers=h).json()
    assert [p["order_number"] for p in listed["items"]] == [order["order_number"]]
    assert client.get(STAFF_PAYMENTS, params={"status": "failed"}, headers=h).json()["total"] == 0
    assert (
        client.get(STAFF_PAYMENTS, params={"method": "cash_on_delivery"}, headers=h).json()["total"]
        == 0
    )
    assert client.get(STAFF_PAYMENTS, params={"status": "bogus"}, headers=h).status_code == 422
    assert "idempotency" not in str(listed) and SECRET not in str(listed)
