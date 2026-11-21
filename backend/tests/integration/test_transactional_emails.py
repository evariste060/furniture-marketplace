"""Transactional email (docs/deployment/email.md): which business events record which message,
what reaches the provider (HTML and plain text, itemised totals, links), duplicates, the test
recipient allowlist and provider failures.

Disposable per-test PostgreSQL schema (tests/conftest.py). The `emails` fixture configures the
email-only provider (NOTIFICATION_PROVIDER=smtp) and replaces it with the capture double from
tests/support/messages.py: nothing is ever sent."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.notifications import DeliveryError, get_notification_provider
from app.main import app
from app.models import NotificationLog, Order
from tests.conftest import verify_email
from tests.integration.test_checkout_api import (  # noqa: F401
    INLINE,
    STAFF,
    checkout,
    delivery,
    guest_cart,
    key,
)
from tests.integration.test_reviews_api import admin_link, delivered_item, submit
from tests.integration.test_settings_content_api import QUOTE, QUOTES
from tests.support.messages import ScriptedProvider

SITE = "https://shop.example.rw"
GUEST_EMAIL = "aline@example.rw"
STAFF_ALERTS = "orders@example.rw, Manager@Example.rw"


@pytest.fixture
def shop(delivery) -> None:  # noqa: F811
    """Delivery zones for checkout (tests.integration.test_checkout_api.delivery)."""


@pytest.fixture
def emails(client, monkeypatch) -> ScriptedProvider:
    settings = get_settings()
    monkeypatch.setattr(settings, "notification_provider", "smtp")
    monkeypatch.setattr(settings, "site_url", SITE)
    monkeypatch.setattr(settings, "staff_order_alert_emails", STAFF_ALERTS)
    monkeypatch.setattr(settings, "email_allowed_recipients", "")
    provider = ScriptedProvider()
    provider.channels = ("email",)
    app.dependency_overrides[get_notification_provider] = lambda: provider
    return provider


def rows(db: Session, event: str | None = None) -> list[NotificationLog]:
    db.expire_all()
    query = select(NotificationLog).order_by(NotificationLog.created_at, NotificationLog.recipient)
    if event is not None:
        query = query.where(NotificationLog.event == event)
    return list(db.scalars(query))


def guest_order(client, db, idem=None):
    h = guest_cart(client, db, price=125_000, quantity=2)
    body = {"address": INLINE, "payment_method": "cash_on_delivery", "email": GUEST_EMAIL}
    res = checkout(client, h, body, idem)
    assert res.status_code in (200, 201), res.text
    return res.json()["order"], h, body


# ---- order placed ----------------------------------------------------------------------------
def test_checkout_emails_the_customer_and_every_staff_address(client, db, shop, emails):
    order, _, _ = guest_order(client, db)
    number = order["order_number"]
    customer = rows(db, "received")
    assert [(r.channel, r.recipient, r.status) for r in customer] == [
        ("email", GUEST_EMAIL, "sent")
    ]
    staff = rows(db, "staff_new_order")
    assert sorted(r.recipient for r in staff) == ["manager@example.rw", "orders@example.rw"]
    assert all(r.status == "sent" and str(r.order_id) == order["id"] for r in staff)

    sent = {m.recipient: m for m in emails.messages}
    mail = sent[GUEST_EMAIL]
    assert mail.subject == f"We received your order {number}"
    assert mail.html and mail.html.startswith("<!doctype html>")
    total = f"RWF {order['total']:,}"
    for part in (mail.text, mail.html):
        assert "2 x " in part and "RWF 250,000" in part and total in part
        assert "Cash on delivery" in part
    assert f'href="{SITE}/track?order={number}"' in mail.html  # a guest: tracking, pre-filled
    assert f"Track your order: {SITE}/track?order={number}" in mail.text
    alert = sent["orders@example.rw"]
    assert alert.subject == f"New order {number}: {total}"
    assert f'href="{SITE}/admin/orders/{order["id"]}"' in alert.html
    assert GUEST_EMAIL in alert.text and "+250788123456" in alert.text


def test_a_signed_in_customer_gets_a_link_to_their_order(client, db, customer_auth, shop, emails):
    from tests.integration.test_cart_api import add, sku

    h = customer_auth["headers"]
    add(client, sku(db), 1, h)
    res = checkout(client, h)
    assert res.status_code == 201, res.text
    number = res.json()["order"]["order_number"]
    mail = next(m for m in emails.messages if m.subject.startswith("We received"))
    assert mail.recipient == customer_auth["user"]["email"]
    assert f'href="{SITE}/account/orders/{number}"' in mail.html


def test_a_replayed_checkout_records_nothing_new(client, db, shop, emails):
    idem = key()
    order, h, body = guest_order(client, db, idem)
    before = len(rows(db))
    replay = checkout(client, h, body, idem)
    assert replay.status_code in (200, 201) and replay.json()["order"]["id"] == order["id"]
    assert len(rows(db)) == before == 3
    assert len(emails.messages) == 3


def test_no_staff_alert_without_a_configured_list(client, db, shop, emails, monkeypatch):
    monkeypatch.setattr(get_settings(), "staff_order_alert_emails", "")
    guest_order(client, db)
    assert [r.event for r in rows(db)] == ["received"]


def test_without_a_site_url_emails_carry_no_link(client, db, shop, emails, monkeypatch):
    monkeypatch.setattr(get_settings(), "site_url", None)
    guest_order(client, db)
    assert emails.messages and all("<a " not in (m.html or "") for m in emails.messages)
    assert all("http" not in m.text for m in emails.messages)


# ---- status changes and payment -------------------------------------------------------------
def test_status_changes_and_cash_on_delivery_payment_are_emailed(
    client, db, shop, emails, operations_auth
):
    order, _, _ = guest_order(client, db)
    h = operations_auth["headers"]
    for status in ("confirmed", "processing", "dispatched", "delivered"):
        res = client.patch(f"{STAFF}/{order['id']}/status", json={"status": status}, headers=h)
        assert res.status_code == 200, res.text
    customer = [r for r in rows(db) if r.recipient == GUEST_EMAIL]
    assert [r.event for r in customer] == [
        "received",
        "confirmed",
        "dispatched",
        "payment_succeeded",  # cash on delivery is recorded as paid on delivery (§7 Q14)
        "delivered",
    ] or [r.event for r in customer] == [
        "received",
        "confirmed",
        "dispatched",
        "delivered",
        "payment_succeeded",
    ]
    assert all(r.status == "sent" for r in customer)
    by_subject = {m.subject: m for m in emails.messages if m.recipient == GUEST_EMAIL}
    number = order["order_number"]
    assert f"Order {number} is on its way" in by_subject
    paid = by_subject[f"Payment received for order {number}"]
    assert f"RWF {order['total']:,} by Cash on delivery" in paid.text


# ---- other events ----------------------------------------------------------------------------
def test_the_welcome_email_follows_email_verification(client, db, emails):
    res = client.post(
        "/api/v1/auth/register",
        json={
            "email": "new.customer@example.rw",
            "phone": "+250788555666",
            "full_name": "Eric Mugisha",
            "password": "SecurePassword123!",
        },
    )
    assert res.status_code == 201, res.text
    # Owner decision 2026-11-12: no welcome to an address that is not proven yet.
    assert rows(db, "welcome") == [] and emails.messages == []
    verify_email(client, "new.customer@example.rw")
    [row] = rows(db, "welcome")
    assert (row.subject_type, row.order_id, row.status) == ("user", None, "sent")
    [mail] = emails.messages
    assert mail.subject == "Welcome to 3 Sixty Technologies" and "Eric Mugisha" in mail.text
    assert f'href="{SITE}/products"' in mail.html


def test_a_quote_request_with_an_email_is_acknowledged(client, db, emails):
    res = client.post(QUOTES, json=QUOTE)
    assert res.status_code == 201, res.text
    reference = res.json()["reference"]
    [row] = rows(db, "quote_received")
    assert row.subject_type == "quote" and row.recipient.lower() == "procurement@example.rw"
    [mail] = emails.messages
    assert reference in mail.subject and "HP Pavilion 15 Laptop: qty 25" in mail.text
    assert f'href="{SITE}/rw/products"' in mail.html  # the buyer's language


def test_a_quote_request_without_an_email_gets_none(client, db, emails):
    minimal = {k: QUOTE[k] for k in ("company", "contact_name", "phone", "lines")}
    assert client.post(QUOTES, json=minimal).status_code == 201
    assert rows(db) == [] and emails.messages == []


def test_a_review_is_thanked(client, db, emails):
    bought = delivered_item(db)
    bought.order.customer_email_snapshot = "reviewer@example.rw"
    db.commit()
    res = submit(client, admin_link(db, bought), rating=5, body="Great")
    assert res.status_code == 201, res.text
    [row] = rows(db, "review_thanks")
    assert (row.subject_type, row.recipient, row.status) == (
        "review",
        "reviewer@example.rw",
        "sent",
    )
    [mail] = emails.messages
    assert mail.subject == "Thank you for your review"
    assert f'href="{SITE}/product/{bought.slug}"' in mail.html


# ---- allowlist, failures, staff view ---------------------------------------------------------
def test_the_allowlist_blocks_every_other_address(client, db, shop, emails, monkeypatch):
    monkeypatch.setattr(get_settings(), "email_allowed_recipients", "orders@example.rw")
    guest_order(client, db)
    blocked = {r.recipient: r for r in rows(db) if r.recipient != "orders@example.rw"}
    assert set(blocked) == {GUEST_EMAIL, "manager@example.rw"}
    for row in blocked.values():
        assert (row.status, row.last_error, row.attempts) == ("failed", "recipient_not_allowed", 0)
        assert row.next_attempt_at is None  # final: never retried by the job
    assert [m.recipient for m in emails.messages] == ["orders@example.rw"]


def test_a_provider_failure_never_undoes_the_order_and_is_retried(
    client, db, shop, emails, monkeypatch
):
    monkeypatch.setattr(get_settings(), "staff_order_alert_emails", "")
    emails.outcomes = [DeliveryError("smtp_error")]
    order, _, _ = guest_order(client, db)
    [row] = rows(db)
    assert (row.status, row.last_error, row.attempts) == ("failed", "smtp_error", 1)
    assert row.next_attempt_at is not None  # retried by the job in 5 minutes
    db.expire_all()
    placed = db.get(Order, uuid.UUID(order["id"]))
    assert placed is not None and placed.status == "received"  # the order stands


def test_staff_see_messages_that_are_not_about_an_order(client, db, emails, admin_auth):
    client.post(QUOTES, json=QUOTE)
    res = client.get("/api/v1/staff/notifications", headers=admin_auth["headers"])
    assert res.status_code == 200, res.text
    [item] = [i for i in res.json()["items"] if i["event"] == "quote_received"]
    assert (item["subject_type"], item["order_id"], item["order_number"]) == ("quote", None, None)
    assert item["recipient"] == "p***@example.rw"
    filtered = client.get(
        "/api/v1/staff/notifications",
        params={"event": "quote_received"},
        headers=admin_auth["headers"],
    )
    assert filtered.json()["total"] == 1


def test_nothing_is_recorded_while_notifications_are_off(client, db, shop, monkeypatch):
    monkeypatch.setattr(get_settings(), "notification_provider", "none")
    guest_order(client, db)
    client.post(QUOTES, json=QUOTE)
    assert rows(db) == []


def test_dedupe_keys_name_the_subject_and_event(client, db, shop, emails):
    order, _, _ = guest_order(client, db)
    keys = {r.dedupe_key for r in rows(db)}
    assert f"order:{order['id']}:received:email" in keys
    assert f"order:{order['id']}:staff_new_order:email:orders@example.rw" in keys
    assert all(uuid.UUID(str(r.subject_id)) == uuid.UUID(order["id"]) for r in rows(db))
