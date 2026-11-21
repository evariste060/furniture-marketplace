"""Module 16 invoice numbering on real PostgreSQL (§7 Q19: INV-YYYY-NNNNNN, gapless per year).

Each worker uses its own session and transaction, exactly as the issuing services do: the
order's locks (lock_order, then the order row), then issue_for_order. Workers start together at
a barrier; a blocked worker is detected through pg_stat_activity, never by sleeping.
Disposable per-test schema of rwanda_ecommerce_test."""

import threading
import time
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.kigali_time import KIGALI
from app.models import Invoice, InvoiceCounter, Order
from app.models.commerce import MAX_INVOICE_SEQUENCE
from app.services import invoice_service
from app.services.inventory import lock_order
from app.services.promotion_service import database_now
from tests.integration.test_checkout_api import checkout, guest_cart
from tests.integration.test_invoices_api import SELLER, SETTINGS
from tests.integration.test_payments_api import delivery  # noqa: F401

TIMEOUT = 30


@pytest.fixture
def seller(client, admin_auth) -> None:
    assert client.patch(SETTINGS, json=SELLER, headers=admin_auth["headers"]).status_code == 200


@pytest.fixture
def make_orders(client, db, clock):
    """n checked-out guest orders; the fake clock moves on between carts so the guest-cart
    creation limit (module 11) does not apply."""

    def make(n: int) -> list[uuid.UUID]:
        ids = []
        for _ in range(n):
            ids.append(uuid.UUID(checkout(client, guest_cart(client, db)).json()["order"]["id"]))
            clock.advance(24 * 3600)
        return ids

    return make


def issue(session: Session, order_id: uuid.UUID) -> invoice_service.IssueResult:
    """One issuing transaction (the caller commits or rolls back)."""
    lock_order(session, order_id)
    order = session.scalar(select(Order).where(Order.id == order_id).with_for_update())
    assert order is not None
    return invoice_service.issue_for_order(session, order, payment_method="cash_on_delivery")


def run_together(engine: Engine, order_ids: list[uuid.UUID]) -> list[tuple[str, str | None]]:
    make = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    barrier = threading.Barrier(len(order_ids))
    results: list[tuple[str, str | None]] = []
    errors: list[BaseException] = []
    guard = threading.Lock()

    def worker(order_id: uuid.UUID) -> None:
        try:
            with make() as session:
                barrier.wait(TIMEOUT)
                with session.begin():
                    result = issue(session, order_id)
                number = result.invoice.invoice_number if result.invoice else None
                with guard:
                    results.append((result.outcome, number))
        except BaseException as exc:  # reported below
            with guard:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(o,)) for o in order_ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(TIMEOUT)
    assert not any(t.is_alive() for t in threads) and errors == [], errors
    return results


def year(db) -> int:
    return database_now(db).astimezone(KIGALI).year


def committed(db) -> list[str]:
    db.expire_all()
    return list(db.scalars(select(Invoice.invoice_number).order_by(Invoice.invoice_number)))


def last_number(db, for_year: int) -> int | None:
    db.expire_all()
    return db.scalar(select(InvoiceCounter.last_number).where(InvoiceCounter.year == for_year))


def wait_until_blocked(engine: Engine, application_marker: str) -> None:
    """Return once a session tagged with application_marker is waiting on a lock."""
    deadline = time.monotonic() + TIMEOUT
    with engine.connect() as conn:
        while time.monotonic() < deadline:
            waiting: int = conn.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE application_name = :m "
                    "AND wait_event_type = 'Lock'"
                ),
                {"m": application_marker},
            ).scalar_one()
            if waiting:
                return
            conn.rollback()
            time.sleep(0.05)
    raise AssertionError("the second transaction never waited on the counter lock")


def test_concurrent_issuance_for_different_orders_is_gapless(
    pg_engine,
    client,
    db,
    delivery,  # noqa: F811
    seller,
    make_orders,
):
    assert pg_engine.url.database == "rwanda_ecommerce_test"
    ids = make_orders(12)
    assert last_number(db, year(db)) is None  # the year's counter row does not exist yet
    results = run_together(pg_engine, ids)  # twelve first-time counter upserts race
    assert sorted(outcome for outcome, _ in results) == ["issued"] * 12
    expected = [f"INV-{year(db)}-{n:06d}" for n in range(1, 13)]
    assert sorted(number for _, number in results if number) == expected
    assert committed(db) == expected and last_number(db, year(db)) == 12


def test_concurrent_issuance_for_one_order_issues_once(
    pg_engine,
    client,
    db,
    delivery,  # noqa: F811
    seller,
    make_orders,
):
    [order_id] = make_orders(1)
    results = run_together(pg_engine, [order_id] * 8)
    assert sorted(outcome for outcome, _ in results) == ["already_issued"] * 7 + ["issued"]
    assert {number for _, number in results} == {f"INV-{year(db)}-000001"}
    assert committed(db) == [f"INV-{year(db)}-000001"] and last_number(db, year(db)) == 1


def test_a_rolled_back_issuance_returns_its_number_to_the_waiting_transaction(
    pg_engine,
    client,
    db,
    delivery,  # noqa: F811
    seller,
    make_orders,
):
    first, second = make_orders(2)
    marker = f"invoice-wait-{uuid.uuid4().hex[:8]}"
    make = sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)
    outcome: dict[str, str | None] = {}

    def waiting_issuer() -> None:
        with make() as session:
            with session.begin():
                session.execute(
                    text("SELECT set_config('application_name', :m, true)"), {"m": marker}
                )
                result = issue(session, second)
            outcome["number"] = result.invoice.invoice_number if result.invoice else None

    with make() as holder:
        holder.begin()
        taken = issue(holder, first)
        assert taken.invoice is not None and taken.invoice.invoice_number.endswith("-000001")
        thread = threading.Thread(target=waiting_issuer)
        thread.start()
        wait_until_blocked(pg_engine, marker)  # serialised on the year's counter row
        holder.rollback()  # e.g. the payment transaction failed after taking the number
    thread.join(TIMEOUT)
    assert not thread.is_alive()
    assert outcome["number"] == f"INV-{year(db)}-000001"  # the rolled-back number is reused
    assert committed(db) == [f"INV-{year(db)}-000001"] and last_number(db, year(db)) == 1
    with make() as again, again.begin():
        retried = issue(again, first)
    assert retried.invoice is not None and retried.invoice.invoice_number.endswith("-000002")


def test_committed_numbers_are_never_reused_or_duplicated(
    pg_engine,
    client,
    db,
    delivery,  # noqa: F811
    seller,
    make_orders,
):
    ids = make_orders(3)
    make = sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)
    for order_id in ids[:2]:
        with make() as session, session.begin():
            issue(session, order_id)
    # Cancelling or otherwise changing an invoiced order frees nothing.
    db.execute(text("UPDATE orders SET status = 'cancelled' WHERE id = :id"), {"id": ids[0]})
    db.commit()
    with make() as session, session.begin():
        result = issue(session, ids[2])
    assert result.invoice is not None and result.invoice.invoice_number.endswith("-000003")
    numbers = committed(db)
    assert numbers == [f"INV-{year(db)}-{n:06d}" for n in (1, 2, 3)]
    with pytest.raises(IntegrityError):  # the database refuses a duplicate number
        with make() as session, session.begin():
            session.execute(
                text(
                    "INSERT INTO invoices (id, order_id, invoice_number, issued_at, total, "
                    "vat_amount, snapshot) VALUES (:id, :o, :n, now(), 0, 0, '{}')"
                ),
                {"id": uuid.uuid4(), "o": ids[1], "n": numbers[0]},
            )
    with pytest.raises(IntegrityError):  # and a second invoice for an order
        with make() as session, session.begin():
            session.execute(
                text(
                    "INSERT INTO invoices (id, order_id, invoice_number, issued_at, total, "
                    "vat_amount, snapshot) VALUES (:id, :o, 'INV-2000-000001', now(), 0, 0, '{}')"
                ),
                {"id": uuid.uuid4(), "o": ids[0]},
            )


def test_each_kigali_year_has_its_own_sequence(
    pg_engine,
    client,
    db,
    delivery,  # noqa: F811
    seller,
    monkeypatch,
    make_orders,
):
    ids = make_orders(3)
    make = sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)
    # 31 December 22:30 UTC is already 1 January in Kigali (UTC+02:00).
    new_year = datetime(2030, 12, 31, 22, 30, tzinfo=UTC)  # the database clock is UTC-aware
    with make() as session, session.begin():
        assert issue(session, ids[0]).invoice is not None
    monkeypatch.setattr(invoice_service, "database_now", lambda _db: new_year)
    numbers = []
    for order_id in ids[1:]:
        with make() as session, session.begin():
            result = issue(session, order_id)
            assert result.invoice is not None
            numbers.append(result.invoice.invoice_number)
    assert numbers == ["INV-2031-000001", "INV-2031-000002"]
    assert last_number(db, 2031) == 2 and last_number(db, year(db)) == 1


def test_an_exhausted_year_refuses_without_changing_the_counter(
    pg_engine,
    client,
    db,
    delivery,  # noqa: F811
    seller,
    make_orders,
):
    [order_id] = make_orders(1)
    db.execute(
        text("INSERT INTO invoice_counters (year, last_number) VALUES (:y, :n)"),
        {"y": year(db), "n": MAX_INVOICE_SEQUENCE},
    )
    db.commit()
    make = sessionmaker(bind=pg_engine, autoflush=False, expire_on_commit=False)
    with make() as session, session.begin():
        result = issue(session, order_id)
    assert result.outcome == "refused" and result.reason == "invoice_numbers_exhausted"
    assert committed(db) == [] and last_number(db, year(db)) == MAX_INVOICE_SEQUENCE
    db.expire_all()
    assert db.scalar(select(func.count(Invoice.id))) == 0
