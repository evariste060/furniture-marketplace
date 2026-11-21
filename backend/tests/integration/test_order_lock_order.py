"""Expiry racing staff status changes (final-review H1). Real PostgreSQL locks, separate
sessions in threads, deterministic pause points; per-test schema of rwanda_ecommerce_test.

Every change to an existing order takes the order's advisory lock, then its row. The expiry
job takes both without waiting (try-lock, SKIP LOCKED) and skips a busy order; a status change
waits for the expiry job instead of holding the row while it does. Before the fix, a status
change that locked the row first and then waited for the advisory lock held by the expiry job
deadlocked with it (the job then waited for the row).
"""

import threading
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import Conflict
from app.core.request_context import RequestContext
from app.models import Discount, DiscountRedemption, Order, PaymentAttempt, StockReservation
from app.models.identity import User
from app.services import inventory, order_service, promotion_service
from app.services.inventory import create_order_with_reservations, expire_due_reservations
from app.services.order_service import OrderService
from tests.conftest import make_staff
from tests.support.commerce import new_order, seed_sku, soon, wait_until_due

CTX = RequestContext(ip_address="127.0.0.1", user_agent="lock-order-test")
TIMEOUT = 20


class Pause:
    """Wraps a function so its caller stops there (holding its locks) until released."""

    def __init__(self, monkeypatch, module, name: str) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        original = getattr(module, name)

        def paused(*args: Any, **kwargs: Any) -> Any:
            self.entered.set()
            assert self.release.wait(TIMEOUT), "pause was never released"
            return original(*args, **kwargs)

        monkeypatch.setattr(module, name, paused)


class Worker(threading.Thread):
    def __init__(self, engine: Engine, fn: Callable[[Session], Any]) -> None:
        super().__init__(daemon=True)
        self._make = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        self._fn = fn
        self.result: Any = None
        self.error: BaseException | None = None

    def run(self) -> None:
        session = self._make()
        try:
            self.result = self._fn(session)
        except BaseException as exc:  # noqa: BLE001 - reported to the test
            self.error = exc
        finally:
            session.rollback()
            session.close()


def wait_for_lock_waiter(db: Session) -> None:
    """Until another session of this database is blocked on a lock (deterministic, no sleep)."""
    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        waiting: int = db.execute(
            text(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                "AND wait_event_type = 'Lock' AND pid <> pg_backend_pid()"
            )
        ).scalar_one()
        db.rollback()
        if waiting:
            return
        time.sleep(0.02)
    raise AssertionError("no session started waiting on a lock")


def finish(*workers: Worker) -> None:
    for worker in workers:
        worker.join(TIMEOUT)
        assert not worker.is_alive(), "a worker never finished (deadlock or hang)"
        if worker.error is not None and not isinstance(worker.error, Conflict):
            raise worker.error  # e.g. psycopg DeadlockDetected before the fix


@pytest.fixture
def setup(pg_engine: Engine, db: Session):
    assert pg_engine.url.database == "rwanda_ecommerce_test"
    staff = make_staff(db, "administrator", "ops.lock@example.com", "+250788000777")["user"]
    discount = Discount(code="LOCKS", name="Locks", kind="fixed", amount_off=100, status="active")
    db.add(discount)
    db.commit()

    def place(method: str, status: str = "received") -> UUID:
        variant = seed_sku(db, on_hand=2)
        order = new_order({variant.id: 1})
        create_order_with_reservations(db, order, expires_at=soon(1))
        db.add(
            PaymentAttempt(
                order_id=order.id,
                method=method,
                amount=0,
                status="pending" if method == "cash_on_delivery" else "created",
                idempotency_key=f"checkout:{order.id}",
            )
        )
        promotion_service.redeem(
            db,
            discount_id=discount.id,
            order_id=order.id,
            user_id=None,
            customer_phone="0788123456",
            amount=100,
        )
        if status != "received":
            order.status = status
        db.commit()
        return order.id

    return staff.id, place


def change(staff_id: UUID, order_id: UUID, status: str) -> Callable[[Session], Any]:
    def run(session: Session) -> Any:
        actor = session.get(User, staff_id)
        assert actor is not None
        return OrderService.change_status(
            session, order_id=order_id, actor=actor, new_status=status, ctx=CTX
        )

    return run


def state(db: Session, order_id: UUID) -> tuple[str, set[str], str, str]:
    db.expire_all()
    order = db.get(Order, order_id)
    assert order is not None
    holds = set(
        db.scalars(select(StockReservation.status).where(StockReservation.order_id == order_id))
    )
    redemption = db.scalar(
        select(DiscountRedemption.status).where(DiscountRedemption.order_id == order_id)
    )
    payment = db.scalar(select(PaymentAttempt.status).where(PaymentAttempt.order_id == order_id))
    return order.status, holds, str(redemption), str(payment)


def expiry_holding_its_locks(pg_engine, monkeypatch) -> tuple[Worker, Pause]:
    """Start the expiry job and stop it while it holds the order's advisory lock and row."""
    pause = Pause(monkeypatch, inventory, "_cancel_unpaid_order")
    worker = Worker(pg_engine, lambda s: expire_due_reservations(s))
    worker.start()
    assert pause.entered.wait(TIMEOUT)
    return worker, pause


# ---- the expiry job holds the order; a status change arrives -------------------------------
@pytest.mark.parametrize(
    ("method", "start", "target"),
    [
        ("mtn_momo", "received", "cancelled"),
        ("cash_on_delivery", "received", "confirmed"),
        ("mtn_momo", "processing", "dispatched"),
    ],
)
def test_a_status_change_waits_for_the_expiry_job_without_deadlock(
    pg_engine, db, setup, monkeypatch, method, start, target
):
    staff_id, place = setup
    order_id = place(method, start)
    wait_until_due()
    expiry, pause = expiry_holding_its_locks(pg_engine, monkeypatch)
    staff = Worker(pg_engine, change(staff_id, order_id, target))
    staff.start()
    wait_for_lock_waiter(db)  # the status change waits (on the advisory lock, not the row)
    pause.release.set()
    finish(expiry, staff)
    assert expiry.error is None and expiry.result.orders == 1
    # The expiry job won: the order is cancelled for payment timeout, so the transition is
    # refused (cancelled -> anything is invalid) and nothing it would have done happened.
    assert isinstance(staff.error, Conflict) and staff.error.code == "invalid_transition"
    assert state(db, order_id) == ("cancelled", {"expired"}, "released", "expired")
    released = db.scalar(
        select(DiscountRedemption.release_reason).where(DiscountRedemption.order_id == order_id)
    )
    assert released == "expired"


# ---- a status change holds the order; the expiry job runs ----------------------------------
def test_the_expiry_job_skips_an_order_being_cancelled(pg_engine, db, setup, monkeypatch):
    staff_id, place = setup
    order_id = place("mtn_momo")
    wait_until_due()
    pause = Pause(monkeypatch, order_service, "release_order_reservations")
    staff = Worker(pg_engine, change(staff_id, order_id, "cancelled"))
    staff.start()
    assert pause.entered.wait(TIMEOUT)  # holds the advisory lock and the row
    expiry = Worker(pg_engine, lambda s: expire_due_reservations(s))
    expiry.start()
    expiry.join(TIMEOUT)
    assert not expiry.is_alive() and expiry.error is None  # it did not wait
    assert (expiry.result.orders, expiry.result.skipped) == (0, 1)
    pause.release.set()
    finish(staff)
    assert staff.error is None
    assert state(db, order_id) == ("cancelled", {"released"}, "released", "cancelled")
    reason = db.scalar(
        select(DiscountRedemption.release_reason).where(DiscountRedemption.order_id == order_id)
    )
    assert reason == "cancelled"  # released once, by the cancellation
    assert expire_due_reservations(db).orders == 0  # nothing left to expire


def test_the_expiry_job_skips_a_cod_order_being_confirmed(pg_engine, db, setup, monkeypatch):
    staff_id, place = setup
    order_id = place("cash_on_delivery")
    wait_until_due()
    pause = Pause(monkeypatch, order_service, "commit_order_reservations")
    staff = Worker(pg_engine, change(staff_id, order_id, "confirmed"))
    staff.start()
    assert pause.entered.wait(TIMEOUT)
    expiry = Worker(pg_engine, lambda s: expire_due_reservations(s))
    expiry.start()
    expiry.join(TIMEOUT)
    assert not expiry.is_alive() and expiry.error is None
    assert (expiry.result.orders, expiry.result.skipped) == (0, 1)
    pause.release.set()
    finish(staff)
    # The hold was already due when staff confirmed: commit refuses a lapsed hold (409), the
    # whole change rolls back, and the order stays as it was until the job's next run.
    assert isinstance(staff.error, Conflict) and staff.error.code == "inventory_conflict"
    assert state(db, order_id) == ("received", {"active"}, "active", "pending")
    assert expire_due_reservations(db).orders == 1
    assert state(db, order_id) == ("cancelled", {"expired"}, "released", "expired")


def test_a_cod_order_confirmed_in_time_is_committed_and_keeps_its_code(
    pg_engine, db, setup, monkeypatch
):
    staff_id, place = setup
    order_id = place("cash_on_delivery")  # hold not yet due
    pause = Pause(monkeypatch, order_service, "commit_order_reservations")
    staff = Worker(pg_engine, change(staff_id, order_id, "confirmed"))
    staff.start()
    assert pause.entered.wait(TIMEOUT)
    expiry = Worker(pg_engine, lambda s: expire_due_reservations(s))
    expiry.start()
    expiry.join(TIMEOUT)
    assert not expiry.is_alive() and expiry.error is None
    pause.release.set()
    finish(staff)
    assert staff.error is None
    assert state(db, order_id) == ("confirmed", {"committed"}, "active", "pending")
    wait_until_due()
    assert expire_due_reservations(db).orders == 0  # committed stock never expires


def test_the_expiry_job_skips_an_order_being_dispatched(pg_engine, db, setup, monkeypatch):
    staff_id, place = setup
    order_id = place("mtn_momo", "processing")
    wait_until_due()
    pause = Pause(monkeypatch, order_service, "dispatch_order_inventory")
    staff = Worker(pg_engine, change(staff_id, order_id, "dispatched"))
    staff.start()
    assert pause.entered.wait(TIMEOUT)
    expiry = Worker(pg_engine, lambda s: expire_due_reservations(s))
    expiry.start()
    expiry.join(TIMEOUT)
    assert not expiry.is_alive() and expiry.error is None
    assert (expiry.result.orders, expiry.result.skipped) == (0, 1)
    pause.release.set()
    finish(staff)
    # An unpaid mobile-money order has no committed stock: dispatch is refused and rolled back.
    assert isinstance(staff.error, Conflict) and staff.error.code == "inventory_conflict"
    assert state(db, order_id) == ("processing", {"active"}, "active", "created")
    assert expire_due_reservations(db).orders == 1
    assert state(db, order_id) == ("cancelled", {"expired"}, "released", "expired")
