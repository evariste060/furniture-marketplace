"""Order and password-reset emails through the real SmtpProvider and a fake SMTP server
(tests/support/fake_smtp.py), so no real email is sent. Disposable per-test PostgreSQL schema
(tests/conftest.py). A mail failure must never touch a committed order, and one notification
must not become two."""

import logging
import re
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.integrations.notifications import (
    SmtpProvider,
    get_message_sender,
    get_notification_provider,
)
from app.main import app
from app.models import NotificationLog, Order
from app.models.session import PasswordResetCode
from app.services.notification_service import deliver, message_for
from tests.integration.test_checkout_api import (  # noqa: F401
    INLINE,
    checkout,
    delivery,
    guest_cart,
)
from tests.integration.test_notifications_api import logs, make_due, move
from tests.integration.test_password_reset_api import EMAIL, FORGOT, PHONE, reset
from tests.support.fake_smtp import DROP, TAKE_AND_DROP, FakeSmtp

CUSTOMER = "aline@example.rw"
NOTIFICATIONS = "/api/v1/staff/notifications"


@pytest.fixture
def shop(delivery) -> None:  # noqa: F811
    """Delivery zones for checkout (tests.integration.test_checkout_api.delivery)."""


@pytest.fixture
def factory(db: Session):
    return sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)


@pytest.fixture
def smtp(client, monkeypatch) -> Iterator[FakeSmtp]:
    monkeypatch.setattr(get_settings(), "notification_provider", "smtp")
    with FakeSmtp() as server:
        provider = SmtpProvider(
            "127.0.0.1", server.port, "shop@example.rw", use_tls=False, timeout=2
        )
        app.dependency_overrides[get_notification_provider] = lambda: provider
        app.dependency_overrides[get_message_sender] = lambda: provider
        server.provider = provider  # type: ignore[attr-defined]
        app.state.fake_smtp = server
        yield server
    app.state.fake_smtp = None
    app.dependency_overrides.pop(get_notification_provider, None)
    app.dependency_overrides.pop(get_message_sender, None)


def order_for(client, db: Session, email: str | None = CUSTOMER, server=None) -> dict:
    """A placed order. Its checkout email ('received', tested in test_transactional_emails.py)
    is set aside, so these tests see the status emails only."""
    body: dict = {"address": INLINE, "payment_method": "cash_on_delivery"}
    if email:
        body["email"] = email
    res = checkout(client, guest_cart(client, db), body)
    assert res.status_code == 201, res.text
    db.execute(text("DELETE FROM notification_logs WHERE event = 'received'"))
    db.commit()
    fake = server or getattr(app.state, "fake_smtp", None)
    if fake is not None:
        fake.messages.clear()
        fake.commands.clear()
    return res.json()["order"]


def status_of(db: Session, order: dict) -> str:
    db.expire_all()
    found = db.get(Order, uuid.UUID(order["id"]))
    assert found is not None
    return found.status


def run_retry_job(factory_, server: FakeSmtp):
    return deliver(factory_, server.provider)  # type: ignore[attr-defined]


def test_each_order_event_emails_the_customer_once(client, db, admin_auth, shop, smtp):
    order = order_for(client, db)
    assert smtp.messages == []  # the checkout email was set aside
    for status in ("confirmed", "processing", "dispatched", "delivered"):
        res = move(client, order["id"], status, admin_auth["headers"])
        assert res.status_code == 200, res.text
    number = order["order_number"]
    subjects = [mail.email["Subject"] for mail in smtp.messages]
    # Delivering a cash-on-delivery order also records its payment.
    assert f"Payment received for order {number}" in subjects
    smtp.messages[:] = [m for m in smtp.messages if not m.email["Subject"].startswith("Payment")]
    assert [mail.email["Subject"] for mail in smtp.messages] == [
        message_for(event, number)[0] for event in ("confirmed", "dispatched", "delivered")
    ]
    assert all(mail.recipients == [CUSTOMER] for mail in smtp.messages)
    rows = [r for r in logs(db, order["id"]) if r.event != "payment_succeeded"]
    assert {(row.channel, row.recipient, row.status, row.attempts) for row in rows} == {
        ("email", CUSTOMER, "sent", 1)
    }
    assert {row.provider_message_id for row in rows} == {
        mail.email["Message-ID"] for mail in smtp.messages
    }


def test_an_order_without_an_email_gets_no_message_and_still_moves(
    client, db, admin_auth, shop, smtp, caplog
):
    order = order_for(client, db, email=None)
    with caplog.at_level(logging.WARNING, logger="app.notifications"):
        res = move(client, order["id"], "confirmed", admin_auth["headers"])
    assert res.status_code == 200, res.text
    assert status_of(db, order) == "confirmed"
    assert logs(db, order["id"]) == [] and smtp.messages == []
    assert "no usable recipient" in caplog.text


def test_a_server_that_is_down_never_fails_the_order_and_the_retry_job_sends_it_once(
    client, db, admin_auth, shop, smtp, factory
):
    order = order_for(client, db)
    smtp.script("MAIL", DROP)
    res = move(client, order["id"], "confirmed", admin_auth["headers"])
    assert res.status_code == 200, res.text
    assert status_of(db, order) == "confirmed"
    [row] = logs(db, order["id"])
    assert (row.status, row.attempts, row.last_error) == ("failed", 1, "connection_lost")
    assert row.next_attempt_at is not None  # a retry is scheduled
    assert smtp.messages == []

    make_due(db, row.id)
    assert run_retry_job(factory, smtp).sent == 1
    assert run_retry_job(factory, smtp).claimed == 0  # sent is sent
    assert len(smtp.messages) == 1
    db.expire_all()
    [row] = logs(db, order["id"])
    assert (row.status, row.attempts) == ("sent", 2)


def test_the_temporary_gmail_route_keeps_the_same_delivery_and_retry_behaviour(
    client, db, admin_auth, shop, smtp, factory, monkeypatch
):
    live = get_settings()
    monkeypatch.setattr(live, "app_env", "production")
    monkeypatch.setattr(live, "temporary_gmail_smtp_enabled", True)
    assert live.temporary_gmail_smtp_active

    order = order_for(client, db)
    smtp.script("MAIL", DROP)
    res = move(client, order["id"], "confirmed", admin_auth["headers"])
    assert res.status_code == 200, res.text  # the failed delivery does not fail the order
    [row] = logs(db, order["id"])
    assert (row.status, row.attempts, row.last_error) == ("failed", 1, "connection_lost")
    assert row.next_attempt_at is not None

    make_due(db, row.id)
    assert run_retry_job(factory, smtp).sent == 1
    assert run_retry_job(factory, smtp).claimed == 0
    assert len(smtp.messages) == 1


def test_a_refused_recipient_ends_the_retries_and_leaves_the_order_alone(
    client, db, admin_auth, shop, smtp, factory
):
    order = order_for(client, db)
    smtp.script("RCPT", "550 5.1.1 aline@example.rw does not exist")
    assert move(client, order["id"], "confirmed", admin_auth["headers"]).status_code == 200
    assert status_of(db, order) == "confirmed"
    [row] = logs(db, order["id"])
    assert (row.status, row.attempts, row.last_error) == ("failed", 1, "recipient_refused")
    assert CUSTOMER not in (row.last_error or "") and "does not exist" not in (row.last_error or "")
    assert row.next_attempt_at is None
    assert run_retry_job(factory, smtp).claimed == 0
    assert smtp.messages == []


def test_a_temporary_refusal_is_retried_until_the_attempts_run_out(
    client, db, admin_auth, shop, smtp, factory
):
    order = order_for(client, db)
    smtp.script("RCPT", "451 busy", "451 busy", "451 busy")
    assert move(client, order["id"], "confirmed", admin_auth["headers"]).status_code == 200
    [row] = logs(db, order["id"])
    for _ in range(2):
        make_due(db, row.id)
        run_retry_job(factory, smtp)
    db.expire_all()
    [row] = logs(db, order["id"])
    assert (row.status, row.attempts, row.next_attempt_at) == ("failed", 3, None)
    assert smtp.commands.count("RCPT") == 3 and smtp.messages == []
    assert status_of(db, order) == "confirmed"


def test_a_lost_answer_is_labelled_unknown_and_its_retry_keeps_the_message_id(
    client, db, admin_auth, shop, smtp, factory
):
    order = order_for(client, db)
    smtp.script("DATA_END", TAKE_AND_DROP)
    assert move(client, order["id"], "confirmed", admin_auth["headers"]).status_code == 200
    [row] = logs(db, order["id"])
    assert (row.status, row.last_error) == ("failed", "connection_lost")
    make_due(db, row.id)
    run_retry_job(factory, smtp)
    first, second = smtp.messages
    assert first.email["Message-ID"] == second.email["Message-ID"]


def test_repeating_an_event_sends_one_email(client, db, admin_auth, shop, smtp):
    order = order_for(client, db)
    headers = admin_auth["headers"]
    assert move(client, order["id"], "confirmed", headers).status_code == 200
    assert move(client, order["id"], "confirmed", headers).status_code in (200, 409)
    assert len(smtp.messages) == 1 and len(logs(db, order["id"])) == 1


def test_a_staff_retry_cannot_send_a_delivered_notification_again(
    client, db, admin_auth, shop, smtp
):
    order = order_for(client, db)
    assert move(client, order["id"], "confirmed", admin_auth["headers"]).status_code == 200
    [row] = logs(db, order["id"])
    res = client.post(f"{NOTIFICATIONS}/{row.id}/retry", headers=admin_auth["headers"])
    assert res.status_code == 409 and res.json()["error"]["code"] == "notification_already_sent"
    assert len(smtp.messages) == 1


def test_an_old_sms_row_is_closed_rather_than_retried_for_ever(
    client, db, admin_auth, shop, smtp, factory, monkeypatch
):
    # Recorded under another provider, then sent after the switch to smtp.
    order = order_for(client, db)
    monkeypatch.setattr(get_settings(), "notification_provider", "mock")
    assert move(client, order["id"], "confirmed", admin_auth["headers"]).status_code == 200
    [row] = logs(db, order["id"])
    assert row.channel == "sms"
    make_due(db, row.id)
    run_retry_job(factory, smtp)
    db.expire_all()
    [row] = logs(db, order["id"])
    assert (row.status, row.last_error) == ("failed", "channel_unsupported")
    assert smtp.messages == []


def test_a_password_reset_code_arrives_by_email_and_works_once(
    client, db, customer_auth, smtp, caplog
):
    with caplog.at_level(logging.DEBUG):
        res = client.post(FORGOT, json={"identifier": EMAIL})
    assert res.status_code == 202
    [mail] = smtp.messages
    assert mail.recipients == [EMAIL]
    match = re.search(r"\b(\d{6})\b", mail.email.get_body(("plain",)).get_content())
    assert match
    code = match.group(1)
    assert code not in caplog.text and EMAIL not in caplog.text
    assert reset(client, code).status_code == 200
    assert reset(client, code).status_code == 422
    assert db.scalar(select(func.count(NotificationLog.id))) == 0  # codes are never stored


def test_a_failed_reset_email_gives_the_same_reply_and_the_code_stays_valid(
    client, db, customer_auth, smtp, caplog
):
    smtp.script("RCPT", "550 5.1.1 secret-server-text")
    with caplog.at_level(logging.DEBUG):
        res = client.post(FORGOT, json={"identifier": EMAIL})
    assert res.status_code == 202  # nothing to enumerate
    assert smtp.messages == []
    assert "Password reset code not delivered" in caplog.text
    assert "secret-server-text" not in caplog.text and EMAIL not in caplog.text
    assert db.scalar(select(func.count(PasswordResetCode.id))) == 1
    assert len(smtp.commands) > 0 and smtp.commands.count("RCPT") == 1  # sent once, never retried


def test_a_reset_for_an_unknown_email_sends_nothing_with_the_same_reply(client, smtp):
    res = client.post(FORGOT, json={"identifier": "nobody@example.rw"})
    assert res.status_code == 202
    assert smtp.commands == []


@pytest.mark.parametrize("identifier", [PHONE, "+250700000001"])
def test_a_reset_by_phone_answers_503_whether_or_not_the_account_exists(
    client, db, customer_auth, smtp, identifier
):
    res = client.post(FORGOT, json={"identifier": identifier})
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "password_reset_unavailable"
    assert smtp.commands == []
    assert db.scalar(select(func.count(PasswordResetCode.id))) == 0
