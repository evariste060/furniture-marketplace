"""Module 15 hardening: one provider call per attempt under concurrent initiation, durable
reconciliation records (late references, unknown initiation outcomes), allow-listed webhook
reason codes, and malformed status types (422, not 500). Disposable per-test schema of
rwanda_ecommerce_test; the concurrency test uses separate real sessions in threads."""

import threading
import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.core.errors import Conflict
from app.core.request_context import RequestContext
from app.db.transaction import atomic
from app.integrations.payments import OrderForPayment, ProviderOutcomeUnknown
from app.integrations.payments.mock import MockProvider
from app.models import Order, PaymentAttempt, PaymentEvent
from app.models.identity import User
from app.models.operations import AuditRecord
from app.services import payment_service
from app.services.inventory import expire_due_reservations, lock_order
from app.services.payment_service import (
    INTERNAL_SOURCE,
    PaymentService,
    _record_late_reference,
)
from tests.integration.test_cart_api import code
from tests.integration.test_payments_api import (  # noqa: F401
    STAFF_PAYMENTS,
    delivery,
    event,
    events,
    holds,
    initiate,
    momo_order,
    started,
    webhook,
)
from tests.support.commerce import hold_expiry, stock_clock_at

CTX = RequestContext(ip_address="127.0.0.1", user_agent="payment-hardening-test")
TIMEOUT = 20


def records(db) -> list[PaymentEvent]:
    """The service's own reconciliation records (source 'internal')."""
    db.expire_all()
    return list(db.scalars(select(PaymentEvent).where(PaymentEvent.provider == INTERNAL_SOURCE)))


def flagged(client, headers) -> set[str]:
    """Attempt ids the staff payment list flags for reconciliation."""
    res = client.get(STAFF_PAYMENTS, params={"needs_reconciliation": "true"}, headers=headers)
    assert res.status_code == 200, res.text
    return {item["id"] for item in res.json()["items"]}


# ---- 1. concurrent initiation: one provider call per attempt -------------------------------
def test_concurrent_initiations_make_one_provider_call(
    pg_engine: Engine,
    client,
    db,
    delivery,  # noqa: F811
    customer_auth,
    lookup_limiter,
    monkeypatch,
):
    assert pg_engine.url.database == "rwanda_ecommerce_test"
    order = momo_order(client, db, customer_auth["headers"])
    user_id = uuid.UUID(customer_auth["user"]["id"])
    calls: list[str] = []
    entered, release = threading.Event(), threading.Event()
    original = MockProvider.initiate

    def slow_initiate(self, snapshot):
        calls.append(snapshot.idempotency_key)
        entered.set()
        assert release.wait(TIMEOUT)
        return original(self, snapshot)

    monkeypatch.setattr(MockProvider, "initiate", slow_initiate)
    make = sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)
    results: dict[str, object] = {}

    def run(name: str) -> None:
        session = make()
        try:
            user = session.get(User, user_id)
            results[name] = PaymentService.initiate(
                session, order["order_number"], user, None, lookup_limiter, CTX
            )
        except Conflict as exc:
            results[name] = exc
        finally:
            session.close()

    first = threading.Thread(target=run, args=("first",))
    first.start()
    assert entered.wait(TIMEOUT)  # the first request is inside the provider call
    second = threading.Thread(target=run, args=("second",))
    second.start()
    second.join(TIMEOUT)
    assert not second.is_alive()  # refused at once, not queued behind the provider call
    refused = results["second"]
    assert isinstance(refused, Conflict) and refused.code == "payment_initiation_in_progress"
    release.set()
    first.join(TIMEOUT)
    assert not first.is_alive()
    assert getattr(results["first"], "status", None) == "pending"
    assert len(calls) == 1  # one provider call for the attempt
    db.expire_all()
    attempt = db.scalar(select(PaymentAttempt))
    assert attempt is not None and calls == [attempt.idempotency_key]  # sent to the provider
    assert db.scalar(select(func.count(PaymentAttempt.id))) == 1


def claim(db, *, stale: bool) -> PaymentAttempt:
    """Leave the attempt as a request would that claimed it and never saved a reference."""
    age = "interval '10 minutes'" if stale else "interval '0 seconds'"
    db.execute(text(f"UPDATE payment_attempts SET provider = 'mock', updated_at = now() - {age}"))
    db.commit()
    db.expire_all()
    attempt = db.scalar(select(PaymentAttempt))
    assert attempt is not None
    return attempt


def first_call(attempt: PaymentAttempt) -> str:
    """The reference the provider gave the first, lost call for this attempt."""
    snapshot = OrderForPayment(
        "o", "n", 1, "RWF", attempt.method, "+250788123456", attempt.idempotency_key
    )
    return MockProvider().initiate(snapshot).reference


def test_a_fresh_claim_is_in_progress(client, db, delivery):  # noqa: F811
    order = momo_order(client, db)
    claim(db, stale=False)
    busy = initiate(client, order["order_number"])
    assert busy.status_code == 409 and code(busy) == "payment_initiation_in_progress"


def test_a_stale_claim_is_retried_with_the_same_key_when_the_provider_is_idempotent(
    client,
    db,
    delivery,  # noqa: F811
    monkeypatch,
):
    order = momo_order(client, db)
    attempt = claim(db, stale=True)
    accepted = first_call(attempt)  # the provider accepted it; the reference was never saved
    keys: list[str] = []
    original = MockProvider.initiate

    def recording(self, snapshot):
        keys.append(snapshot.idempotency_key)
        return original(self, snapshot)

    monkeypatch.setattr(MockProvider, "initiate", recording)
    retried = initiate(client, order["order_number"])
    assert retried.status_code == 200 and retried.json()["status"] == "pending"
    assert keys == [attempt.idempotency_key]  # same key: the same payment, not a second one
    assert retried.json()["reference"] == accepted
    assert db.scalar(select(func.count(PaymentAttempt.id))) == 1


def test_a_stale_claim_needs_recovery_when_the_provider_is_not_idempotent(
    client,
    db,
    delivery,  # noqa: F811
    monkeypatch,
    caplog,
):
    order = momo_order(client, db)
    monkeypatch.setattr(MockProvider, "idempotent_initiation", False)
    calls: list[str] = []
    monkeypatch.setattr(MockProvider, "initiate", lambda self, s: calls.append(s) or None)
    claim(db, stale=False)
    busy = initiate(client, order["order_number"])  # still fresh: in progress, as before
    assert busy.status_code == 409 and code(busy) == "payment_initiation_in_progress"
    attempt = claim(db, stale=True)  # the first call may have started a payment
    with caplog.at_level("ERROR", logger="app.payments"):
        stuck = initiate(client, order["order_number"])
    assert stuck.status_code == 409 and code(stuck) == "payment_initiation_needs_recovery"
    assert calls == []  # never repeated
    assert any(
        "needs reconciliation" in r.getMessage() and str(attempt.id) in r.getMessage()
        for r in caplog.records
    )
    db.expire_all()
    [kept] = db.scalars(select(PaymentAttempt)).all()
    assert (kept.status, kept.provider, kept.provider_reference) == ("created", "mock", None)
    again = initiate(client, order["order_number"])  # stays refused; nothing marked failed
    assert again.status_code == 409 and code(again) == "payment_initiation_needs_recovery"
    [record] = records(db)  # durable, linked, and written once for both refusals
    assert record.attempt_id == attempt.id
    assert record.payload_metadata["event_type"] == "initiation_needs_recovery"


def test_an_unconfigured_provider_releases_the_claim(client, db, delivery, monkeypatch):  # noqa: F811
    order = momo_order(client, db)
    monkeypatch.setenv("PAYMENT_MOCK_WEBHOOK_SECRET", "")
    get_settings.cache_clear()
    try:
        assert initiate(client, order["order_number"]).status_code == 503
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
    db.expire_all()
    assert db.scalar(select(PaymentAttempt.provider)) is None  # nothing left claimed
    assert initiate(client, order["order_number"]).status_code == 200  # no 409 afterwards


# ---- 2. webhook reasons are allow-listed codes ---------------------------------------------
@pytest.mark.parametrize(
    ("reason", "stored"),
    [
        ("insufficient_funds", "insufficient_funds"),
        ("declined", "declined"),
        ("Payer John Doe +250788123456 card 4111111111111111", "other"),
        ({"note": "free text"}, "other"),
        (12345, "other"),
    ],
)
def test_only_allow_listed_reason_codes_are_stored(client, db, delivery, reason, stored):  # noqa: F811
    order, body = started(client, db)
    res = webhook(client, event(body["reference"], "failed", order["total"], reason=reason))
    assert res.status_code == 200
    [saved] = events(db)
    assert saved.payload_metadata["reason"] == stored
    text_form = str(saved.payload_metadata)
    assert "John" not in text_form and "4111" not in text_form and "788123456" not in text_form


# ---- 3. malformed status types are 422, not 500 --------------------------------------------
@pytest.mark.parametrize("bad_status", [["succeeded"], {"value": "succeeded"}, 1, None, True])
def test_a_non_string_status_is_a_malformed_event(client, db, delivery, bad_status):  # noqa: F811
    order, body = started(client, db)
    res = webhook(
        client, {**event(body["reference"], "succeeded", order["total"]), "status": bad_status}
    )
    assert res.status_code == 422 and code(res) == "malformed_event"
    assert db.scalar(select(func.count(PaymentEvent.id))) == 0


# ---- 4. a reference returned after the hold expired is never lost ----------------------------
def expire_during_the_call(monkeypatch, pg_engine, returned: list[str]) -> None:
    """The expiry job runs (in its own session) while the provider call is in flight.

    The order keeps its normal hold, so initiation always finds it valid and reaches the
    provider. Inside the call the real expiry job runs at the instant the hold expires
    (tests.support.commerce.stock_clock_at, for the job only). The reservation row is never
    edited (it is immutable apart from its status), and nothing depends on how long checkout or
    initiation took."""
    original = MockProvider.initiate
    make = sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)

    def late(self, snapshot):
        with make() as other:
            expires = hold_expiry(other, uuid.UUID(snapshot.order_id))
        assert expires is not None  # still held: initiation saw a valid hold
        with stock_clock_at(monkeypatch, expires), make() as other:
            assert expire_due_reservations(other).orders == 1
        result = original(self, snapshot)
        returned.append(result.reference)
        return result

    monkeypatch.setattr(MockProvider, "initiate", late)


def test_a_reference_returned_after_expiry_is_kept_for_reconciliation(
    pg_engine,
    client,
    db,
    admin_auth,
    delivery,  # noqa: F811
    monkeypatch,
):
    order = momo_order(client, db)
    returned: list[str] = []
    expire_during_the_call(monkeypatch, pg_engine, returned)
    res = initiate(client, order["order_number"])
    assert res.status_code == 409 and code(res) == "payment_initiation_needs_recovery"
    [reference] = returned
    # The reference is kept on the attempt; nothing is revived or marked paid.
    db.expire_all()
    [attempt] = db.scalars(select(PaymentAttempt)).all()
    assert (attempt.status, attempt.provider, attempt.provider_reference) == (
        "expired",
        "mock",
        reference,
    )
    stored = db.get(Order, uuid.UUID(order["id"]))
    assert stored is not None and stored.status == "cancelled"
    assert holds(db, order["id"]) == {"expired"}
    # A durable, sanitised record linked to the attempt, audited, and found by staff.
    [record] = records(db)
    assert record.attempt_id == attempt.id and record.processing_status == "needs_reconciliation"
    assert record.payload_metadata == {
        "event_type": "late_reference",
        "provider": "mock",
        "reference": reference,
        "method": "mtn_momo",
        "amount": order["total"],
        "currency": "RWF",
        "attempt_status": "expired",
        "order_status": "cancelled",
    }
    assert record.payload_digest is None  # no provider payload exists or is kept
    assert record.verification_status == "received"  # not authenticated evidence
    audits = db.scalars(select(AuditRecord.action).where(AuditRecord.entity_id == order["id"]))
    assert "payment.reconciliation" in set(audits)
    assert str(attempt.id) in flagged(client, admin_auth["headers"])
    # A later webhook for that payment is linked and handled as a late payment.
    hook = webhook(client, event(reference, "succeeded", order["total"]))
    assert hook.status_code == 200 and hook.json()["status"] == "needs_reconciliation"
    received = [e for e in events(db) if e.provider == "mock"]
    assert [e.attempt_id for e in received] == [attempt.id]
    assert received[0].result_summary == "late success: the stock hold had lapsed"
    assert holds(db, order["id"]) == {"expired"}  # nothing recommitted
    db.expire_all()
    assert db.get(PaymentAttempt, attempt.id).status == "expired"  # never 'succeeded'
    assert db.get(Order, uuid.UUID(order["id"])).status == "cancelled"
    # The order stays closed.
    again = initiate(client, order["order_number"])
    assert again.status_code == 409 and code(again) == "order_not_payable"


def test_a_late_reference_is_recorded_once(pg_engine, client, db, delivery, monkeypatch):  # noqa: F811
    order = momo_order(client, db)
    returned: list[str] = []
    expire_during_the_call(monkeypatch, pg_engine, returned)
    res = initiate(client, order["order_number"])
    # Only the late-reference path is under test. Another 409 (order_not_payable, a hold that
    # lapsed before initiation) would mean the provider was never called.
    assert (res.status_code, code(res)) == (409, "payment_initiation_needs_recovery"), res.text
    [reference] = returned  # one provider call
    [first] = records(db)
    db.expire_all()
    [attempt] = db.scalars(select(PaymentAttempt)).all()
    for _ in range(2):  # the same late result processed again
        with atomic(db):
            lock_order(db, attempt.order_id)
            locked = db.get(PaymentAttempt, attempt.id, with_for_update=True)
            _record_late_reference(db, locked, "mock", reference, None, CTX)
    [record] = records(db)  # still exactly one
    assert record.id == first.id and record.payload_metadata["event_type"] == "late_reference"
    db.expire_all()
    assert db.get(PaymentAttempt, attempt.id).provider_reference == reference


def test_a_hold_that_lapsed_before_initiation_is_refused_without_a_provider_call(
    client,
    db,
    delivery,  # noqa: F811
    monkeypatch,
):
    order = momo_order(client, db)
    expires = hold_expiry(db, uuid.UUID(order["id"]))
    assert expires is not None
    # Initiation happens at (or after) the instant the hold expires; the expiry job has not run.
    database_clock = payment_service.database_now
    monkeypatch.setattr(payment_service, "database_now", lambda s: max(database_clock(s), expires))
    calls: list[OrderForPayment] = []
    original = MockProvider.initiate

    def recording(self, snapshot):
        calls.append(snapshot)
        return original(self, snapshot)

    monkeypatch.setattr(MockProvider, "initiate", recording)
    res = initiate(client, order["order_number"])
    assert (res.status_code, code(res)) == (409, "order_not_payable"), res.text
    assert calls == []  # refused before any provider call
    db.expire_all()
    [attempt] = db.scalars(select(PaymentAttempt)).all()
    assert (attempt.status, attempt.provider, attempt.provider_reference) == ("created", None, None)
    assert records(db) == []  # nothing to reconcile
    assert holds(db, order["id"]) == {"active"}  # the hold itself is untouched


def test_a_racing_second_reference_is_recorded_and_never_overwrites_the_first(
    pg_engine,
    client,
    db,
    admin_auth,
    delivery,  # noqa: F811
    customer_auth,
    lookup_limiter,
    monkeypatch,
):
    order = momo_order(client, db, customer_auth["headers"])
    user_id = uuid.UUID(customer_auth["user"]["id"])
    entered, release = threading.Event(), threading.Event()
    original = MockProvider.initiate
    calls: list[str] = []

    def racing(self, snapshot):
        calls.append(snapshot.idempotency_key)
        if len(calls) == 1:  # the first, slow call; this provider breaks its promise
            entered.set()
            assert release.wait(TIMEOUT)
            result = original(self, snapshot)
            return type(result)("MOCK-SECONDREFERENCE0001", result.status, result.instructions)
        return original(self, snapshot)

    monkeypatch.setattr(MockProvider, "initiate", racing)
    make = sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)
    results: dict[str, object] = {}

    def run(name: str) -> None:
        with make() as session:
            try:
                results[name] = PaymentService.initiate(
                    session,
                    order["order_number"],
                    session.get(User, user_id),
                    None,
                    lookup_limiter,
                    CTX,
                )
            except Conflict as exc:
                results[name] = exc

    slow = threading.Thread(target=run, args=("slow",))
    slow.start()
    assert entered.wait(TIMEOUT)
    claim(db, stale=True)  # the slow call outlived its claim; an idempotent retry takes over
    run("retry")
    first = getattr(results["retry"], "reference", None)
    assert first is not None and getattr(results["retry"], "status", None) == "pending"
    release.set()
    slow.join(TIMEOUT)
    assert not slow.is_alive()
    refused = results["slow"]
    assert isinstance(refused, Conflict) and refused.code == "payment_initiation_needs_recovery"
    db.expire_all()
    [attempt] = db.scalars(select(PaymentAttempt)).all()
    assert (attempt.status, attempt.provider_reference) == ("pending", first)  # kept
    [record] = records(db)
    assert record.attempt_id == attempt.id
    assert record.payload_metadata["event_type"] == "conflicting_reference"
    assert record.payload_metadata["reference"] == "MOCK-SECONDREFERENCE0001"
    assert str(attempt.id) in flagged(client, admin_auth["headers"])


def test_the_same_reference_from_a_racing_retry_is_not_a_conflict(
    pg_engine,
    client,
    db,
    delivery,  # noqa: F811
    customer_auth,
    lookup_limiter,
    monkeypatch,
):
    order = momo_order(client, db, customer_auth["headers"])
    user_id = uuid.UUID(customer_auth["user"]["id"])
    entered, release = threading.Event(), threading.Event()
    original = MockProvider.initiate
    calls: list[str] = []

    def racing(self, snapshot):
        calls.append(snapshot.idempotency_key)
        if len(calls) == 1:
            entered.set()
            assert release.wait(TIMEOUT)
        return original(self, snapshot)

    monkeypatch.setattr(MockProvider, "initiate", racing)
    make = sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)
    results: dict[str, object] = {}

    def run(name: str) -> None:
        with make() as session:
            results[name] = PaymentService.initiate(
                session,
                order["order_number"],
                session.get(User, user_id),
                None,
                lookup_limiter,
                CTX,
            )

    slow = threading.Thread(target=run, args=("slow",))
    slow.start()
    assert entered.wait(TIMEOUT)
    claim(db, stale=True)
    run("retry")
    release.set()
    slow.join(TIMEOUT)
    assert not slow.is_alive()
    references = {getattr(results.get(n), "reference", None) for n in ("slow", "retry")}
    assert len(references) == 1 and None not in references  # one payment, one reference
    assert records(db) == []
    assert calls[0] == calls[1]  # both calls carried the attempt's key


# ---- 5. an unknown provider outcome is never a failure -------------------------------------
def unknown_outcome(self, snapshot):
    raise ProviderOutcomeUnknown("timed out after sending")


def test_an_unknown_outcome_keeps_the_claim_and_needs_recovery_without_idempotency(
    client,
    db,
    admin_auth,
    delivery,  # noqa: F811
    monkeypatch,
):
    order = momo_order(client, db)
    monkeypatch.setattr(MockProvider, "idempotent_initiation", False)
    monkeypatch.setattr(MockProvider, "initiate", unknown_outcome)
    res = initiate(client, order["order_number"])
    assert res.status_code == 409 and code(res) == "payment_initiation_needs_recovery"
    db.expire_all()
    [attempt] = db.scalars(select(PaymentAttempt)).all()
    assert (attempt.status, attempt.provider, attempt.provider_reference) == (
        "created",
        "mock",
        None,
    )
    [record] = records(db)
    assert record.attempt_id == attempt.id
    assert record.payload_metadata["event_type"] == "initiation_outcome_unknown"
    assert str(attempt.id) in flagged(client, admin_auth["headers"])
    busy = initiate(client, order["order_number"])  # the claim stays: nothing repeats the call
    assert busy.status_code == 409 and code(busy) == "payment_initiation_in_progress"
    assert holds(db, order["id"]) == {"active"}  # the hold is untouched


def test_an_unknown_outcome_with_an_idempotent_provider_can_be_retried(
    client,
    db,
    delivery,  # noqa: F811
    monkeypatch,
):
    order = momo_order(client, db)
    with monkeypatch.context() as patched:
        patched.setattr(MockProvider, "initiate", unknown_outcome)
        res = initiate(client, order["order_number"])
    assert res.status_code == 502 and code(res) == "payment_provider_error"
    db.expire_all()
    [attempt] = db.scalars(select(PaymentAttempt)).all()
    assert (attempt.status, attempt.provider) == ("created", None)  # not failed; claim released
    assert records(db) == []
    retried = initiate(client, order["order_number"])  # the same attempt and key
    assert retried.status_code == 200 and retried.json()["status"] == "pending"
    assert db.scalar(select(func.count(PaymentAttempt.id))) == 1


def test_no_webhook_can_write_as_the_internal_source(client, db, delivery):  # noqa: F811
    order, body = started(client, db)
    payload = event(body["reference"], "succeeded", order["total"])
    res = webhook(client, payload, provider="internal")
    assert res.status_code == 404 and code(res) == "provider_not_found"
    assert records(db) == []


# ---- 6. reconciliation records are never labelled verified; unexpected adapter errors ------
def test_reconciliation_records_are_received_never_verified(client, db, delivery, monkeypatch):  # noqa: F811
    order = momo_order(client, db)
    monkeypatch.setattr(MockProvider, "idempotent_initiation", False)
    claim(db, stale=True)
    assert code(initiate(client, order["order_number"])) == "payment_initiation_needs_recovery"
    [record] = records(db)
    assert record.verification_status == "received"  # nothing in it was authenticated
    started_order, body = started(client, db)  # a signed webhook is still 'verified'
    webhook(client, event(body["reference"], "pending", started_order["total"]))
    [received] = [e for e in events(db) if e.provider == "mock"]
    assert received.verification_status == "verified"


def broken_adapter(self, snapshot):
    raise RuntimeError("socket closed; payer +250788123456")


def test_an_unexpected_adapter_error_is_an_unknown_outcome_not_a_failure(
    client,
    db,
    admin_auth,
    delivery,  # noqa: F811
    monkeypatch,
    caplog,
):
    order = momo_order(client, db)
    monkeypatch.setattr(MockProvider, "idempotent_initiation", False)
    monkeypatch.setattr(MockProvider, "initiate", broken_adapter)
    with caplog.at_level("ERROR", logger="app.payments"):
        res = initiate(client, order["order_number"])
    assert res.status_code == 409 and code(res) == "payment_initiation_needs_recovery"
    assert "788123456" not in res.text and "socket" not in res.text
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "RuntimeError" in logged and "788123456" not in logged and "socket" not in logged
    db.expire_all()
    [attempt] = db.scalars(select(PaymentAttempt)).all()
    assert (attempt.status, attempt.provider, attempt.provider_reference) == (
        "created",
        "mock",
        None,
    )  # never marked failed; the claim stays, so nothing repeats the call
    [record] = records(db)
    assert record.attempt_id == attempt.id
    assert record.payload_metadata["event_type"] == "initiation_outcome_unknown"
    assert "788123456" not in str(record.payload_metadata)
    assert str(attempt.id) in flagged(client, admin_auth["headers"])
    busy = initiate(client, order["order_number"])
    assert busy.status_code == 409 and code(busy) == "payment_initiation_in_progress"


def test_an_unexpected_adapter_error_with_an_idempotent_provider_can_be_retried(
    client,
    db,
    delivery,  # noqa: F811
    monkeypatch,
):
    order = momo_order(client, db)
    with monkeypatch.context() as patched:
        patched.setattr(MockProvider, "initiate", broken_adapter)
        res = initiate(client, order["order_number"])
    assert res.status_code == 502 and code(res) == "payment_provider_error"
    db.expire_all()
    [attempt] = db.scalars(select(PaymentAttempt)).all()
    assert (attempt.status, attempt.provider) == ("created", None)  # not failed; claim released
    assert records(db) == []
    retried = initiate(client, order["order_number"])
    assert retried.status_code == 200 and retried.json()["status"] == "pending"


# ---- 7. an event that arrives before the reference is saved is linked, not lost -------------
def test_an_event_before_the_reference_is_saved_is_linked_for_reconciliation(
    client,
    db,
    admin_auth,
    delivery,  # noqa: F811
):
    order = momo_order(client, db)
    db.expire_all()
    [attempt] = db.scalars(select(PaymentAttempt)).all()
    reference = first_call(attempt)  # the mock's reference is derived from the attempt's key
    early = webhook(client, event(reference, "succeeded", order["total"]))
    assert early.json()["status"] == "needs_reconciliation"  # unknown reference, unlinked
    [stored] = events(db)
    assert stored.attempt_id is None
    res = initiate(client, order["order_number"])
    assert res.status_code == 200 and res.json()["reference"] == reference
    assert res.json()["status"] == "pending"  # linked, not applied: a person decides
    db.expire_all()
    [stored] = events(db)
    assert stored.attempt_id == attempt.id and stored.processing_status == "needs_reconciliation"
    assert holds(db, order["id"]) == {"active"}  # nothing committed
    assert str(attempt.id) in flagged(client, admin_auth["headers"])
    audits = db.scalars(
        select(AuditRecord.change_summary).where(AuditRecord.entity_id == order["id"])
    )
    assert any(a.get("kind") == "early_event_linked" for a in audits if isinstance(a, dict))
