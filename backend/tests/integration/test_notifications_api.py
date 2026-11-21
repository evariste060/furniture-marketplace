"""Module 17 — order notifications (plan §5 "17 — notifications"; §7 Q22; TC-19 backend part).

Disposable per-test PostgreSQL schema (tests/conftest.py). The `notify` fixture turns
notifications on (NOTIFICATION_PROVIDER=mock for this test) and replaces the provider with a
scripted test double, so every send is recorded and can be made to fail."""

import importlib.util
import logging
import threading
import time
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.request_context import RequestContext
from app.db.transaction import atomic
from app.integrations.notifications import (
    DeliveryError,
    DeliveryTimeout,
    OutboundMessage,
    get_notification_provider,
)
from app.main import app
from app.models import NotificationLog, Order
from app.models.identity import User
from app.models.operations import AuditRecord
from app.services import checkout_service, notification_service
from app.services.inventory import expire_due_reservations
from app.services.notification_service import (
    close_abandoned,
    deliver,
    message_for,
    outcome_unknown,
    recipient_for,
    record_order_event,
    sanitise_error,
)
from app.services.order_service import OrderService
from tests.integration.test_cart_api import code
from tests.integration.test_checkout_api import (  # noqa: F401
    STAFF,
    checkout,
    delivery,
    guest_cart,
)
from tests.integration.test_checkout_api import placed as place_order
from tests.support.commerce import wait_until_due
from tests.support.messages import ScriptedProvider

NOTIFICATIONS = "/api/v1/staff/notifications"
PHONE = "+250788123456"  # tests.integration.test_checkout_api.INLINE, canonical
CTX = RequestContext(ip_address="127.0.0.1", user_agent="notification-test")
SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "retry_notifications.py"


@pytest.fixture
def notify(client, monkeypatch) -> ScriptedProvider:
    monkeypatch.setattr(get_settings(), "notification_provider", "mock")
    provider = ScriptedProvider()
    app.dependency_overrides[get_notification_provider] = lambda: provider
    return provider


@pytest.fixture
def shop(delivery) -> None:  # noqa: F811
    """Delivery zones for checkout (tests.integration.test_checkout_api.delivery)."""


@pytest.fixture
def factory(db: Session):
    return sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)


def placed(client, db: Session, admin_auth, **options) -> tuple[dict, str]:
    """A placed order, with its checkout message ('received', tested in
    test_transactional_emails.py) set aside: this module tests the status messages. The
    provider's scripted outcomes are kept for the calls the test is about."""
    provider = app.dependency_overrides.get(get_notification_provider, lambda: None)()
    outcomes = getattr(provider, "outcomes", None)
    if outcomes is not None:
        provider.outcomes = []
    try:
        result = place_order(client, db, admin_auth, **options)
    finally:
        if outcomes is not None:
            provider.outcomes = outcomes
            provider.messages.clear()
    db.execute(text("DELETE FROM notification_logs WHERE event = 'received'"))
    db.commit()
    return result


def move(client, order_id: str, status: str, headers: dict):
    return client.patch(f"{STAFF}/{order_id}/status", json={"status": status}, headers=headers)


def logs(db: Session, order_id: str | uuid.UUID | None = None) -> list[NotificationLog]:
    db.expire_all()
    query = select(NotificationLog).order_by(NotificationLog.created_at, NotificationLog.id)
    if order_id is not None:
        query = query.where(NotificationLog.order_id == uuid.UUID(str(order_id)))
    return list(db.scalars(query))


def db_now(db: Session):
    return db.scalar(text("SELECT statement_timestamp()"))


def make_due(db: Session, *ids: uuid.UUID) -> None:
    db.execute(
        text(
            "UPDATE notification_logs SET next_attempt_at = now() - interval '1 second' "
            "WHERE id = ANY(:ids)"
        ),
        {"ids": list(ids)},
    )
    db.commit()


def add_log(db: Session, order_id: str, event: str, **fields) -> NotificationLog:
    row = NotificationLog(
        order_id=uuid.UUID(order_id),
        subject_type="order",
        subject_id=uuid.UUID(order_id),
        event=event,
        channel="sms",
        recipient=PHONE,
        **{
            "status": "pending",
            "attempts": 0,
            "dedupe_key": f"order:{order_id}:{event}:sms:{uuid.uuid4().hex}",
            **fields,
        },
    )
    if row.status == "pending" and row.next_attempt_at is None:
        row.next_attempt_at = db_now(db) - timedelta(seconds=1)
    db.add(row)
    db.commit()
    return row


def load_script():
    spec = importlib.util.spec_from_file_location("retry_notifications", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---- events, after commit only -------------------------------------------------------------
def test_each_order_event_sends_one_sms_after_the_change(client, db, admin_auth, shop, notify):
    order, _ = placed(client, db, admin_auth, with_code=False)
    assert logs(db) == []  # placed() set the checkout message aside
    h = admin_auth["headers"]
    for status in ("confirmed", "processing", "dispatched", "delivered"):
        assert move(client, order["id"], status, h).status_code == 200, status
    everything = logs(db, order["id"])
    # Delivering a cash-on-delivery order also records its payment (test_transactional_emails).
    assert [r.event for r in everything if r.event == "payment_succeeded"] == ["payment_succeeded"]
    rows = [r for r in everything if r.event != "payment_succeeded"]
    assert [r.event for r in rows] == ["confirmed", "dispatched", "delivered"]  # not processing
    keys = {f"notification:{r.id}" for r in rows}
    notify.messages[:] = [m for m in notify.messages if m.idempotency_key in keys]
    for row in rows:
        assert (row.channel, row.recipient, row.status, row.attempts) == ("sms", PHONE, "sent", 1)
        assert row.sent_at is not None and row.provider_message_id
        assert row.next_attempt_at is None and row.claimed_until is None and row.last_error is None
    assert [m.idempotency_key for m in notify.messages] == [f"notification:{r.id}" for r in rows]
    number = order["order_number"]
    assert [m.text for m in notify.messages] == [
        message_for(event, number)[1] for event in ("confirmed", "dispatched", "delivered")
    ]
    assert all(m.channel == "sms" and m.recipient == PHONE for m in notify.messages)


def test_a_cancellation_is_notified(client, db, admin_auth, shop, notify):
    order, _ = placed(client, db, admin_auth, with_code=False)
    assert move(client, order["id"], "cancelled", admin_auth["headers"]).status_code == 200
    [row] = logs(db, order["id"])
    assert (row.event, row.status) == ("cancelled", "sent")
    assert (
        notify.messages[0].text == f"Your order {order['order_number']} has been cancelled. "
        "Contact us if you have any questions."
    )


def test_the_provider_runs_only_after_the_order_change_committed(
    client, db, admin_auth, shop, notify, factory
):
    order, _ = placed(client, db, admin_auth, with_code=False)
    seen: list[tuple[str, int]] = []

    class Observing(ScriptedProvider):
        def send(self, message: OutboundMessage) -> str:
            with factory() as other:  # another connection sees only committed data
                status = other.scalar(
                    select(Order.status).where(Order.id == uuid.UUID(order["id"]))
                )
                count = other.scalar(
                    text("SELECT count(*) FROM notification_logs WHERE order_id = :id"),
                    {"id": uuid.UUID(order["id"])},
                )
            seen.append((status, count))
            return super().send(message)

    app.dependency_overrides[get_notification_provider] = lambda: Observing()
    assert move(client, order["id"], "confirmed", admin_auth["headers"]).status_code == 200
    assert seen == [("confirmed", 1)]


def test_a_rolled_back_order_change_records_and_sends_nothing(
    client, db, admin_auth, shop, notify, monkeypatch
):
    order, _ = placed(client, db, admin_auth, with_code=False)
    invalid = move(client, order["id"], "delivered", admin_auth["headers"])
    assert invalid.status_code == 409 and code(invalid) == "invalid_transition"

    # A failure after the notification was recorded (the status-change audit insert) rolls the
    # whole transaction back, the notification row with it.
    from app.services import order_service

    real = order_service.AuditService.log_event

    def failing(*args, **kwargs):
        if kwargs.get("action") == "order.status_change":
            raise RuntimeError("audit store down")
        return real(*args, **kwargs)

    monkeypatch.setattr(order_service.AuditService, "log_event", staticmethod(failing))
    actor = db.get(User, admin_auth["user"].id)
    assert actor is not None
    with pytest.raises(RuntimeError):
        OrderService.change_status(
            db, order_id=uuid.UUID(order["id"]), actor=actor, new_status="confirmed", ctx=CTX
        )
    [recorded] = notification_service.take_recorded_ids(db)  # it was inserted, then rolled back
    assert deliver(sessionmaker(bind=db.get_bind()), notify, ids=[recorded]).claimed == 0
    assert logs(db) == [] and notify.messages == []
    db.expire_all()
    assert db.get(Order, uuid.UUID(order["id"])).status == "received"


def test_nothing_is_recorded_while_notifications_are_off(
    client, db, admin_auth, shop, notify, monkeypatch
):
    monkeypatch.setattr(get_settings(), "notification_provider", "none")
    order, _ = placed(client, db, admin_auth, with_code=False)
    assert move(client, order["id"], "confirmed", admin_auth["headers"]).status_code == 200
    assert logs(db) == [] and notify.messages == []


def test_a_repeated_event_records_one_notification(client, db, admin_auth, shop, notify):
    order_row, _ = placed(client, db, admin_auth, with_code=False)
    order = db.get(Order, uuid.UUID(order_row["id"]))
    assert order is not None
    for _ in range(2):
        with atomic(db):
            record_order_event(db, order, "confirmed")
            record_order_event(db, order, "confirmed")
    assert len(logs(db)) == 1
    assert len(notification_service.take_recorded_ids(db)) == 1  # only the inserted row


def test_the_expiry_jobs_cancellation_is_recorded_and_sent_by_the_retry_job(
    client, db, admin_auth, shop, notify, factory, monkeypatch
):
    monkeypatch.setitem(checkout_service.HOLDS, "mtn_momo", timedelta(seconds=1))
    order, _ = placed(client, db, admin_auth, method="mtn_momo", with_code=False)
    wait_until_due()
    assert expire_due_reservations(db).orders == 1
    db.commit()  # the test session had a transaction open, so the job ran in a savepoint
    [row] = logs(db, order["id"])
    assert (row.event, row.status, row.attempts) == ("cancelled", "pending", 0)
    assert deliver(factory, notify).sent == 1
    assert logs(db, order["id"])[0].status == "sent"


# ---- provider failures never fail the order ------------------------------------------------
def test_status_changes_succeed_when_the_provider_raises_or_times_out(
    client, db, admin_auth, shop, notify, caplog
):
    notify.outcomes = [
        RuntimeError(f"gateway said token=sk_live_123 for {PHONE}"),
        DeliveryTimeout(),
    ]
    order, _ = placed(client, db, admin_auth, with_code=False)
    h = admin_auth["headers"]
    with caplog.at_level(logging.INFO):
        for status in ("confirmed", "processing", "dispatched"):
            assert move(client, order["id"], status, h).status_code == 200, status
    db.expire_all()
    assert db.get(Order, uuid.UUID(order["id"])).status == "dispatched"
    confirmed, dispatched = logs(db, order["id"])
    now = db_now(db)
    for row, error in ((confirmed, "unexpected_error:RuntimeError"), (dispatched, "timeout")):
        assert (row.status, row.attempts, row.last_error) == ("failed", 1, error)
        assert row.sent_at is None and row.provider_message_id is None
        assert timedelta(minutes=4) < row.next_attempt_at - now <= timedelta(minutes=5)
    assert (
        "sk_live" not in caplog.text and PHONE not in caplog.text and "gateway" not in caplog.text
    )


def test_checkout_succeeds_with_a_failing_provider(client, db, shop, notify):
    notify.outcomes = [RuntimeError("down")] * 3
    res = checkout(client, guest_cart(client, db))
    assert res.status_code == 201, res.text  # the order stands
    [row] = logs(db)
    assert (row.event, row.status, row.attempts) == ("received", "failed", 1)
    assert row.last_error == "unexpected_error:RuntimeError" and row.next_attempt_at is not None


def test_failures_are_retried_at_most_three_times_with_backoff(
    client, db, admin_auth, shop, notify, factory
):
    notify.outcomes = [DeliveryError("gateway_unavailable")] * 3
    order, _ = placed(client, db, admin_auth, with_code=False)
    assert move(client, order["id"], "confirmed", admin_auth["headers"]).status_code == 200
    [row] = logs(db)
    assert (row.status, row.attempts, row.last_error) == ("failed", 1, "gateway_unavailable")
    assert deliver(factory, notify).claimed == 0  # not due for 5 minutes
    make_due(db, row.id)
    assert deliver(factory, notify).retry_scheduled == 1
    [row] = logs(db)
    assert row.attempts == 2
    assert timedelta(minutes=29) < row.next_attempt_at - db_now(db) <= timedelta(minutes=30)
    make_due(db, row.id)
    assert deliver(factory, notify).failed == 1
    [row] = logs(db)
    assert (row.status, row.attempts, row.next_attempt_at) == ("failed", 3, None)
    make_due(db, row.id)  # even if made due again, no fourth attempt
    assert deliver(factory, notify).claimed == 0
    assert len(notify.messages) == 3
    assert {m.idempotency_key for m in notify.messages} == {f"notification:{row.id}"}


def test_a_permanent_provider_error_ends_the_retries(client, db, admin_auth, shop, notify):
    notify.outcomes = [DeliveryError("recipient_rejected", retryable=False)]
    order, _ = placed(client, db, admin_auth, with_code=False)
    assert move(client, order["id"], "confirmed", admin_auth["headers"]).status_code == 200
    [row] = logs(db)
    assert (row.status, row.attempts, row.next_attempt_at) == ("failed", 1, None)
    assert row.last_error == "recipient_rejected"


def test_provider_errors_are_sanitised_and_bounded():
    assert sanitise_error(DeliveryError("Bad Request: +250788123456")) == ("provider_error", True)
    assert sanitise_error(DeliveryError("x" * 65)) == ("provider_error", True)
    assert sanitise_error(DeliveryTimeout()) == ("timeout", True)
    assert sanitise_error(TimeoutError("read timed out after 10s")) == ("timeout", True)
    stored, retryable = sanitise_error(ValueError("api_key=abc"))
    assert stored == "unexpected_error:ValueError" and retryable
    long_name = type("E" * 300, (Exception,), {})("secret")
    stored, _ = sanitise_error(long_name)
    assert len(stored) <= 200 and "secret" not in stored


def test_messages_carry_only_the_order_number():
    for event in ("confirmed", "dispatched", "delivered", "cancelled"):
        subject, body = message_for(event, "ORD-261026-ABCDEF")
        assert "ORD-261026-ABCDEF" in subject and "ORD-261026-ABCDEF" in body
        assert "http" not in body and "code" not in body.lower()


# ---- retry job -------------------------------------------------------------------------------
def test_the_retry_job_sends_only_due_records(client, db, admin_auth, shop, notify, monkeypatch):
    order, _ = placed(client, db, admin_auth, with_code=False)
    now = db_now(db)
    due = add_log(db, order["id"], "confirmed")
    future = add_log(
        db,
        order["id"],
        "dispatched",
        status="failed",
        attempts=1,
        last_error="timeout",
        next_attempt_at=now + timedelta(hours=1),
    )
    exhausted = add_log(
        db, order["id"], "delivered", status="failed", attempts=3, last_error="timeout"
    )
    sent = add_log(
        db,
        order["id"],
        "cancelled",
        status="sent",
        attempts=1,
        sent_at=now,
        provider_message_id="earlier-1",
    )
    script = load_script()
    monkeypatch.setattr(script, "get_notification_provider", lambda: notify)
    result, closed = script.run(sessionmaker(bind=db.get_bind()), batch_size=10, max_batches=3)
    assert (result.sent, result.claimed, closed) == (1, 1, 0)
    assert [m.idempotency_key for m in notify.messages] == [f"notification:{due.id}"]
    state = {r.id: (r.status, r.attempts) for r in logs(db)}
    assert state == {
        due.id: ("sent", 1),
        future.id: ("failed", 1),
        exhausted.id: ("failed", 3),
        sent.id: ("sent", 1),
    }


def test_the_retry_job_recovers_from_a_stopped_worker(
    client, db, admin_auth, shop, notify, monkeypatch
):
    order, _ = placed(client, db, admin_auth, with_code=False)
    past = db_now(db) - timedelta(minutes=1)
    retryable = add_log(db, order["id"], "confirmed", attempts=1, claimed_until=past)
    abandoned = add_log(db, order["id"], "dispatched", attempts=3, claimed_until=past)
    leased = add_log(
        db, order["id"], "delivered", attempts=1, claimed_until=past + timedelta(minutes=5)
    )
    script = load_script()
    monkeypatch.setattr(script, "get_notification_provider", lambda: notify)
    result, closed = script.run(sessionmaker(bind=db.get_bind()), batch_size=10, max_batches=3)
    assert (result.sent, closed) == (1, 1)
    rows = {r.id: r for r in logs(db)}
    assert (rows[retryable.id].status, rows[retryable.id].attempts) == ("sent", 2)
    assert (rows[abandoned.id].status, rows[abandoned.id].last_error) == (
        "failed",
        "outcome_unknown",
    )
    assert rows[abandoned.id].next_attempt_at is None and rows[abandoned.id].claimed_until is None
    assert (rows[leased.id].status, rows[leased.id].attempts) == ("pending", 1)  # still leased


def test_the_retry_script_does_nothing_without_a_provider(monkeypatch, capsys):
    script = load_script()
    monkeypatch.setattr(script, "get_notification_provider", lambda: None)
    assert script.main([]) == 0
    assert "nothing sent" in capsys.readouterr().out


def test_concurrent_workers_send_each_notification_once(
    client, db, admin_auth, shop, notify, factory
):
    ids = []
    for _ in range(2):
        order, _ = placed(client, db, admin_auth, with_code=False)
        for event in ("confirmed", "dispatched", "delivered", "cancelled"):
            ids.append(add_log(db, order["id"], event).id)
    provider = ScriptedProvider(delay=0.05)
    start = threading.Barrier(4)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            start.wait()
            deliver(factory, provider, limit=3)
            deliver(factory, provider, limit=3)
            deliver(factory, provider, limit=3)
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert errors == []
    keys = [m.idempotency_key for m in provider.messages]
    assert sorted(keys) == sorted(f"notification:{i}" for i in ids)  # each once
    assert {(r.status, r.attempts) for r in logs(db)} == {("sent", 1)}


# ---- slow providers, competing workers, recording failures -----------------------------------
# Real threads on separate PostgreSQL connections; each pause waits on an Event or a polled
# database condition, never a fixed sleep.
class HeldProvider(ScriptedProvider):
    """The first call waits inside the provider until release(), like a slow or hung gateway;
    later calls answer at once. `entered` is set, and `held_key` known, once that call started."""

    def __init__(self, outcomes=()):
        super().__init__(outcomes)
        self.entered = threading.Event()
        self.held_key = ""
        self._release = threading.Event()
        self._gate = threading.Lock()

    def release(self) -> None:
        self._release.set()

    def send(self, message: OutboundMessage) -> str:
        with self._gate:
            hold = not self.entered.is_set()
            if hold:
                self.held_key = message.idempotency_key
                self.entered.set()
        if hold:
            assert self._release.wait(30), "the held call was never released"
        return super().send(message)


def in_background(target, *args, **kwargs) -> tuple[threading.Thread, dict]:
    outcome: dict = {}

    def run() -> None:
        try:
            outcome["result"] = target(*args, **kwargs)
        except BaseException as exc:  # reported by the test
            outcome["error"] = exc

    thread = threading.Thread(target=run)
    thread.start()
    return thread, outcome


def key_id(key: str) -> uuid.UUID:
    return uuid.UUID(key.removeprefix("notification:"))


def state(db: Session, *ids: uuid.UUID) -> list[tuple]:
    """(status, attempts, claimed, last_error) per row."""
    rows = {r.id: r for r in logs(db)}
    return [
        (rows[i].status, rows[i].attempts, rows[i].claimed_until is not None, rows[i].last_error)
        for i in ids
    ]


def wait_for(condition, what: str) -> None:
    deadline = time.monotonic() + 15
    while not condition():
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        time.sleep(0.02)


def lost_connection(*args, **kwargs):
    raise OperationalError("UPDATE notification_logs", {}, Exception("server closed connection"))


def test_a_slow_call_does_not_hold_the_rest_of_its_batch(client, db, admin_auth, shop, factory):
    order, _ = placed(client, db, admin_auth, with_code=False)
    ids = [add_log(db, order["id"], e).id for e in ("confirmed", "dispatched", "delivered")]
    slow = HeldProvider()
    worker, outcome = in_background(deliver, factory, slow, limit=3)
    assert slow.entered.wait(15)
    held = key_id(slow.held_key)
    others = [i for i in ids if i != held]
    # Only the row being sent is claimed: the rest of the batch has no lease to outlive and no
    # attempt counted.
    assert state(db, held) == [("pending", 1, True, None)]
    assert state(db, *others) == [("pending", 0, False, None)] * 2
    fast = ScriptedProvider()
    assert deliver(factory, fast, limit=3).sent == 2  # a second worker sends them meanwhile
    slow.release()
    worker.join(30)
    assert "error" not in outcome
    assert (outcome["result"].sent, outcome["result"].claimed) == (1, 1)
    keys = [m.idempotency_key for m in slow.messages + fast.messages]
    assert sorted(keys) == sorted(f"notification:{i}" for i in ids)  # each sent once
    assert {(r.status, r.attempts, r.claimed_until) for r in logs(db)} == {("sent", 1, None)}


def test_a_call_that_outlives_its_first_lease_is_not_sent_again(
    client, db, admin_auth, shop, notify, factory, monkeypatch
):
    monkeypatch.setattr(notification_service, "CLAIM_LEASE", timedelta(seconds=1))
    monkeypatch.setattr(notification_service, "LEASE_RENEWAL", timedelta(milliseconds=100))
    order, _ = placed(client, db, admin_auth, with_code=False)
    row = add_log(db, order["id"], "confirmed")
    slow = HeldProvider()
    worker, outcome = in_background(deliver, factory, slow)
    assert slow.entered.wait(15)
    [claimed] = logs(db)
    first_lease = claimed.claimed_until
    # On the database clock the claim's first lease is long over; only renewals keep it.
    wait_for(lambda: db_now(db) > first_lease + timedelta(seconds=2), "the first lease to end")
    [current] = logs(db)
    assert current.claimed_until > db_now(db)
    other = ScriptedProvider()
    assert deliver(factory, other).claimed == 0  # a competing worker finds nothing due
    retry = client.post(f"{NOTIFICATIONS}/{row.id}/retry", headers=admin_auth["headers"])
    assert retry.status_code == 409 and code(retry) == "notification_in_progress"
    slow.release()
    worker.join(30)
    assert "error" not in outcome and outcome["result"].sent == 1
    assert other.messages == [] and notify.messages == [] and len(slow.messages) == 1
    assert state(db, row.id) == [("sent", 1, False, None)]


def test_a_stale_worker_cannot_overwrite_a_newer_attempt(
    client, db, admin_auth, shop, factory, monkeypatch, caplog
):
    # The first worker cannot reach the database to renew its lease, so the lease ends mid-call.
    monkeypatch.setattr(notification_service, "LEASE_RENEWAL", timedelta(milliseconds=50))
    monkeypatch.setattr(notification_service, "_renew", lost_connection)
    order, _ = placed(client, db, admin_auth, with_code=False)
    row = add_log(db, order["id"], "confirmed")
    slow = HeldProvider(outcomes=[DeliveryTimeout()])
    with caplog.at_level(logging.WARNING, logger="app.notifications"):
        worker, outcome = in_background(deliver, factory, slow)
        assert slow.entered.wait(15)
        wait_for(lambda: "lease not renewed" in caplog.text, "a failed renewal")
    db.execute(  # its lease ends
        text("UPDATE notification_logs SET claimed_until = now() - interval '1 second'")
    )
    db.commit()
    seen: list[tuple] = []

    class Observing(ScriptedProvider):
        def send(self, message: OutboundMessage) -> str:
            with factory() as other:
                found = other.execute(text("SELECT attempts, last_error FROM notification_logs"))
                seen.append(tuple(found.one()))
            return super().send(message)

    newer = Observing()
    assert deliver(factory, newer).sent == 1
    # The second worker counted attempt 2 and recorded attempt 1's outcome as unknown.
    assert seen == [(2, "outcome_unknown")]
    slow.release()
    worker.join(30)
    assert "error" not in outcome and outcome["result"].lost_claims == 1  # fenced off
    [stored] = logs(db)
    assert (stored.status, stored.attempts, stored.last_error) == ("sent", 2, None)
    assert stored.provider_message_id == "recorded-1"  # the newer worker's result stands
    # Both calls carried one idempotency key: only an idempotent provider drops the second.
    keys = [m.idempotency_key for m in slow.messages + newer.messages]
    assert keys == [f"notification:{row.id}"] * 2


def test_a_recording_failure_stops_the_batch_without_spending_later_attempts(
    client, db, admin_auth, shop, notify, factory, monkeypatch
):
    order, _ = placed(client, db, admin_auth, with_code=False)
    events = ("confirmed", "dispatched", "delivered", "cancelled")
    ids = [add_log(db, order["id"], e).id for e in events]
    real = notification_service._record
    calls: list[int] = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            lost_connection()
        return real(*args, **kwargs)

    monkeypatch.setattr(notification_service, "_record", flaky)
    with pytest.raises(OperationalError):
        deliver(factory, notify, limit=10)
    done, unrecorded = (key_id(m.idempotency_key) for m in notify.messages)
    untouched = [i for i in ids if i not in (done, unrecorded)]
    assert state(db, done) == [("sent", 1, False, None)]
    assert state(db, unrecorded) == [("pending", 1, True, None)]  # one call, result unknown
    assert state(db, *untouched) == [("pending", 0, False, None)] * 2  # never claimed or called
    with factory() as session:
        assert close_abandoned(session) == 0  # nothing mislabelled outcome_unknown

    monkeypatch.setattr(notification_service, "_record", real)
    assert deliver(factory, notify, limit=10).sent == 2  # first attempts; that lease still holds
    assert state(db, *untouched) == [("sent", 1, False, None)] * 2
    db.execute(
        text(
            "UPDATE notification_logs SET claimed_until = now() - interval '1 second' "
            "WHERE id = :id"
        ),
        {"id": unrecorded},
    )
    db.commit()
    assert deliver(factory, notify, limit=10).sent == 1  # recovered once its lease ended
    assert state(db, unrecorded) == [("sent", 2, False, None)]
    keys = [m.idempotency_key for m in notify.messages]
    assert keys.count(f"notification:{unrecorded}") == 2  # same key: idempotency decides
    assert all(keys.count(f"notification:{i}") == 1 for i in (done, *untouched))


def test_a_failed_claim_counts_no_attempt(
    client, db, admin_auth, shop, notify, factory, monkeypatch
):
    order, _ = placed(client, db, admin_auth, with_code=False)
    row = add_log(db, order["id"], "confirmed")
    monkeypatch.setattr(notification_service, "Claim", lost_connection)  # fails mid-claim
    with pytest.raises(OperationalError):
        deliver(factory, notify)
    assert state(db, row.id) == [("pending", 0, False, None)] and notify.messages == []


def test_unknown_outcomes_are_told_apart_from_refusals():
    for unknown in ("timeout", "invalid_provider_response", "outcome_unknown"):
        assert outcome_unknown(unknown)
    assert outcome_unknown("unexpected_error:RuntimeError")
    for refused in ("gateway_unavailable", "recipient_rejected", "provider_error", None):
        assert not outcome_unknown(refused)


# ---- channel and recipient ---------------------------------------------------------------
def test_sms_goes_to_the_orders_phone_otherwise_email():
    order = Order(recipient_phone=PHONE, customer_email_snapshot="a@example.rw")
    assert recipient_for(order) == ("sms", PHONE)
    order.recipient_phone = "0788123456"  # not canonical: not used for SMS
    assert recipient_for(order) == ("email", "a@example.rw")
    order.customer_email_snapshot = "not an email"
    assert recipient_for(order) is None
    order.customer_email_snapshot = None
    assert recipient_for(order) is None


def test_an_order_without_a_usable_phone_is_emailed(client, db, admin_auth, shop, notify):
    order, _ = placed(client, db, admin_auth, with_code=False)
    db.execute(
        text(
            "UPDATE orders SET recipient_phone = 'unknown', customer_email_snapshot = "
            "'aline@example.rw' WHERE id = :id"
        ),
        {"id": uuid.UUID(order["id"])},
    )
    db.commit()
    assert move(client, order["id"], "confirmed", admin_auth["headers"]).status_code == 200
    [row] = logs(db)
    assert (row.channel, row.recipient, row.status) == ("email", "aline@example.rw", "sent")
    assert notify.messages[0].subject == f"Order {order['order_number']} confirmed"


@pytest.mark.parametrize(
    "fields",
    [
        {"channel": "sms", "recipient": "aline@example.rw"},
        {"channel": "email", "recipient": PHONE.removeprefix("+")},
        {"channel": "whatsapp", "recipient": PHONE},
        {"event": "processing"},
        {"status": "queued"},
        {"attempts": 4},
        {"status": "sent"},  # sent needs sent_at and a provider message ID
    ],
)
def test_the_database_refuses_invalid_records(client, db, admin_auth, shop, fields):
    order, _ = placed(client, db, admin_auth, with_code=False)
    values = {
        "order_id": uuid.UUID(order["id"]),
        "event": "confirmed",
        "channel": "sms",
        "recipient": PHONE,
        "status": "pending",
        "attempts": 0,
        "next_attempt_at": db_now(db),
        **fields,
    }
    db.add(NotificationLog(**values))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# ---- staff endpoints -------------------------------------------------------------------------
def test_the_log_is_paginated_filtered_and_masked(client, db, admin_auth, shop, notify):
    notify.outcomes = [None, RuntimeError("down")]
    order, _ = placed(client, db, admin_auth, with_code=False)
    h = admin_auth["headers"]
    for status in ("confirmed", "processing", "dispatched"):
        assert move(client, order["id"], status, h).status_code == 200
    res = client.get(NOTIFICATIONS, params={"size": 1}, headers=admin_auth["headers"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["total"], body["page"], body["size"], len(body["items"])) == (2, 1, 1, 1)
    newest = body["items"][0]
    assert newest["event"] == "dispatched" and newest["status"] == "failed"
    assert newest["last_error"] == "unexpected_error:RuntimeError"
    assert newest["recipient"] == "+250******456" and PHONE not in res.text
    assert newest["order_number"] == order["order_number"]
    assert (newest["attempts"], newest["max_attempts"], newest["in_progress"]) == (1, 3, False)
    assert set(newest) == {
        "id",
        "subject_type",
        "order_id",
        "order_number",
        "event",
        "channel",
        "recipient",
        "status",
        "attempts",
        "max_attempts",
        "in_progress",
        "last_error",
        "provider_message_id",
        "next_attempt_at",
        "sent_at",
        "created_at",
        "updated_at",
    }
    sent = client.get(NOTIFICATIONS, params={"status": "sent"}, headers=admin_auth["headers"])
    assert [i["event"] for i in sent.json()["items"]] == ["confirmed"]
    by_order = client.get(
        NOTIFICATIONS,
        params={"order_id": order["id"], "event": "dispatched", "channel": "sms"},
        headers=admin_auth["headers"],
    )
    assert by_order.json()["total"] == 1
    assert (
        client.get(
            NOTIFICATIONS, params={"channel": "email"}, headers=admin_auth["headers"]
        ).json()["total"]
        == 0
    )


@pytest.mark.parametrize(
    "params",
    [
        {"status": "queued"},
        {"channel": "fax"},
        {"size": 101},
        {"page": 0},
        {"order_id": "nope"},
        {"event": "processing"},
    ],
)
def test_invalid_list_queries_are_422(client, admin_auth, params):
    res = client.get(NOTIFICATIONS, params=params, headers=admin_auth["headers"])
    assert res.status_code == 422 and code(res) == "validation_error"


@pytest.mark.parametrize(
    "who",
    ["customer_auth"],
)
def test_only_notifications_manage_reads_or_retries(client, db, request, who):
    # Final staff matrix (2026-10-26): finance reads orders and payments but holds no
    # notifications:manage, so it can neither read the log nor retry.
    headers = request.getfixturevalue(who)["headers"]
    listing = client.get(NOTIFICATIONS, headers=headers)
    retry = client.post(f"{NOTIFICATIONS}/{uuid.uuid4()}/retry", headers=headers)
    for res in (listing, retry):
        assert res.status_code == 403 and code(res) == "permission_denied"


def test_anonymous_callers_are_401(client):
    assert client.get(NOTIFICATIONS).status_code == 401
    assert client.post(f"{NOTIFICATIONS}/{uuid.uuid4()}/retry").status_code == 401


def test_retry_sends_a_failed_notification_now_and_is_audited(client, db, admin_auth, shop, notify):
    notify.outcomes = [DeliveryTimeout()]
    order, _ = placed(client, db, admin_auth, with_code=False)
    assert move(client, order["id"], "confirmed", admin_auth["headers"]).status_code == 200
    [row] = logs(db)
    assert row.status == "failed"
    res = client.post(f"{NOTIFICATIONS}/{row.id}/retry", headers=admin_auth["headers"])
    assert res.status_code == 202, res.text
    assert res.json()["id"] == str(row.id) and res.json()["status"] == "failed"
    [row] = logs(db)
    assert (row.status, row.attempts, row.last_error) == ("sent", 2, None)  # sent after the reply
    db.expire_all()
    [audit] = db.scalars(select(AuditRecord).where(AuditRecord.action == "notification.retry"))
    assert audit.actor_user_id == admin_auth["user"].id and audit.entity_id == str(row.id)
    summary = audit.change_summary
    assert summary["status"] == "success" and summary["attempts"] == 1
    assert summary["notification_status"] == "failed" and PHONE not in str(summary)


def test_retry_without_a_provider_leaves_the_notification_due(client, db, admin_auth, shop, notify):
    notify.outcomes = [DeliveryTimeout()]
    order, _ = placed(client, db, admin_auth, with_code=False)
    assert move(client, order["id"], "confirmed", admin_auth["headers"]).status_code == 200
    [row] = logs(db)
    app.dependency_overrides[get_notification_provider] = lambda: None
    res = client.post(f"{NOTIFICATIONS}/{row.id}/retry", headers=admin_auth["headers"])
    assert res.status_code == 202
    [row] = logs(db)
    assert row.status == "failed" and row.attempts == 1 and row.next_attempt_at <= db_now(db)


@pytest.mark.parametrize(
    ("fields", "error"),
    [
        (
            {"status": "sent", "attempts": 1, "provider_message_id": "m-1"},
            "notification_already_sent",
        ),
        ({"status": "failed", "attempts": 3}, "notification_attempts_exhausted"),
        ({"attempts": 1, "in_progress": True}, "notification_in_progress"),
    ],
)
def test_ineligible_retries_are_409_and_audited(
    client, db, admin_auth, shop, notify, fields, error
):
    order, _ = placed(client, db, admin_auth, with_code=False)
    now = db_now(db)
    if fields.pop("in_progress", False):
        fields["claimed_until"] = now + timedelta(minutes=1)
    if fields.get("status") == "sent":
        fields["sent_at"] = now
    row = add_log(db, order["id"], "confirmed", **fields)
    res = client.post(f"{NOTIFICATIONS}/{row.id}/retry", headers=admin_auth["headers"])
    assert res.status_code == 409 and code(res) == error
    assert notify.messages == []
    db.expire_all()
    [audit] = db.scalars(select(AuditRecord).where(AuditRecord.action == "notification.retry"))
    assert audit.change_summary["status"] == "conflict"
    assert audit.change_summary["reason"] == error


def test_retry_of_a_missing_or_malformed_id(client, admin_auth):
    missing = client.post(f"{NOTIFICATIONS}/{uuid.uuid4()}/retry", headers=admin_auth["headers"])
    assert missing.status_code == 404 and code(missing) == "notification_not_found"
    malformed = client.post(f"{NOTIFICATIONS}/not-a-uuid/retry", headers=admin_auth["headers"])
    assert malformed.status_code == 422 and code(malformed) == "validation_error"


def test_a_failed_notification_insert_never_fails_the_order_change(
    client, db, admin_auth, shop, notify, monkeypatch, caplog
):
    # A recipient the database refuses for its channel: the insert fails inside its savepoint.
    monkeypatch.setattr(notification_service, "recipient_for", lambda order: ("sms", "a@b.rw"))
    order, _ = placed(client, db, admin_auth, with_code=False)
    with caplog.at_level(logging.ERROR, logger="app.notifications"):
        res = move(client, order["id"], "confirmed", admin_auth["headers"])
    assert res.status_code == 200, res.text
    db.expire_all()
    assert db.get(Order, uuid.UUID(order["id"])).status == "confirmed"
    assert db.scalar(
        select(AuditRecord.id).where(
            AuditRecord.action == "order.status_change", AuditRecord.entity_id == order["id"]
        )
    )
    assert logs(db) == [] and notify.messages == []
    assert "Notification not recorded" in caplog.text and "IntegrityError" in caplog.text
    assert "a@b.rw" not in caplog.text
