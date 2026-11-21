"""Stock reservation lifecycle on PostgreSQL (PR-09, TC-13, TC-14; ADR-002 approved 2026-10-22).

Every test gets its own migrated schema. Concurrency tests use separate database connections in
threads, released together by a barrier, so the races are real PostgreSQL transaction races.
Real-HTTP and multi-process races are in tests/postgres/test_pg_inventory.py.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models import Order, StockMovement, StockReservation
from app.services import inventory as inv
from app.services.audit_service import AuditService
from app.services.inventory import TransitionOutcome as Outcome
from tests.support.commerce import (
    allocated,
    audit_count,
    new_order,
    on_hand,
    seed_sku,
    soon,
    statuses,
    wait_until_due,
)


@pytest.fixture
def sf(pg_engine):
    return sessionmaker(bind=pg_engine, expire_on_commit=False)


def make_sku(sf, on_hand=1, **overrides):
    with sf() as s, s.begin():
        return seed_sku(s, on_hand=on_hand, **overrides).id


def reserve(sf, lines, *, key=None, expires=None, user_id=None):
    with sf() as s:
        return inv.create_order_with_reservations(
            s, new_order(lines, key=key, user_id=user_id), expires_at=expires or soon()
        )


def run_together(n, fn):
    barrier = Barrier(n)

    def wrapped(i):
        barrier.wait(timeout=20)
        return fn(i)

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(wrapped, range(n)))


def fail_audit(monkeypatch, action_prefix="inventory."):
    real = AuditService.log_event

    def broken(*args, **kwargs):
        if kwargs.get("action", "").startswith(action_prefix):
            raise RuntimeError("audit store unavailable")
        return real(*args, **kwargs)

    monkeypatch.setattr(AuditService, "log_event", staticmethod(broken))


# ---- reservation -----------------------------------------------------------------------------
def test_reserve_available_stock_and_audit(sf):
    sku = make_sku(sf, on_hand=3)
    result = reserve(sf, {sku: 2})
    assert result.replayed is False
    with sf() as s:
        assert statuses(s, result.order.id) == ["active"]
        assert inv.availability(s, sku) == {
            "on_hand": 3,
            "unavailable_quantity": 0,
            "reserved_quantity": 2,
            "committed_quantity": 0,
            "available_quantity": 1,
        }
        assert audit_count(s, "inventory.reserve", result.order.id) == 1
        assert s.scalar(select(StockMovement.id)) is None  # reservations are not movements


def test_insufficient_stock_rejected_and_nothing_persisted(sf):
    sku = make_sku(sf, on_hand=1)
    order = new_order({sku: 2})
    with sf() as s, pytest.raises(inv.InsufficientStock) as err:
        inv.create_order_with_reservations(s, order, expires_at=soon())
    assert (err.value.requested, err.value.available) == (2, 1)
    with sf() as s:
        assert s.scalar(select(Order.id)) is None
        assert s.scalar(select(StockReservation.id)) is None
        assert on_hand(s, sku) == 1


@pytest.mark.parametrize("quantity", [0, -1, 1.5, True, 2**31])
def test_invalid_quantities_rejected(sf, quantity):
    sku = make_sku(sf, on_hand=5)
    with sf() as s, pytest.raises(ValueError):
        inv.create_order_with_reservations(s, new_order({sku: quantity}), expires_at=soon())
    with sf() as s:
        assert s.scalar(select(Order.id)) is None


def test_unknown_unsellable_and_unstocked_skus_rejected(sf):
    import uuid

    with sf() as s, pytest.raises(inv.UnknownSku):
        inv.create_order_with_reservations(s, new_order({uuid.uuid4(): 1}), expires_at=soon())
    inactive = make_sku(sf, on_hand=5, is_active=False)
    with sf() as s, pytest.raises(inv.SkuNotSellable):
        inv.create_order_with_reservations(s, new_order({inactive: 1}), expires_at=soon())
    with sf() as s, s.begin():
        hidden = seed_sku(s, on_hand=5)
        hidden.product.status = "hidden"
        hidden_id = hidden.id
    with sf() as s, pytest.raises(inv.SkuNotSellable):
        inv.create_order_with_reservations(s, new_order({hidden_id: 1}), expires_at=soon())
    no_record = make_sku(sf, on_hand=None)
    with sf() as s, pytest.raises(inv.InsufficientStock):
        inv.create_order_with_reservations(s, new_order({no_record: 1}), expires_at=soon())
    with sf() as s:
        assert s.scalar(select(StockReservation.id)) is None


def test_expiry_must_be_future_database_time_and_timezone_aware(sf):
    from datetime import datetime

    sku = make_sku(sf, on_hand=5)
    with sf() as s, pytest.raises(ValueError, match="future"):
        inv.create_order_with_reservations(s, new_order({sku: 1}), expires_at=soon(-1))
    with sf() as s, pytest.raises(ValueError, match="timezone"):
        inv.create_order_with_reservations(s, new_order({sku: 1}), expires_at=datetime.now())


def test_multiline_shortage_reserves_nothing(sf):
    a, b = make_sku(sf, on_hand=5), make_sku(sf, on_hand=0)
    with sf() as s, pytest.raises(inv.InsufficientStock):
        inv.create_order_with_reservations(s, new_order({a: 1, b: 1}), expires_at=soon())
    with sf() as s:
        assert allocated(s, a) == 0 and s.scalar(select(Order.id)) is None


def test_retry_with_same_checkout_key_is_idempotent(sf):
    sku = make_sku(sf, on_hand=5)
    first = reserve(sf, {sku: 2}, key="checkout-retry-1")
    again = reserve(sf, {sku: 2}, key="checkout-retry-1")
    assert again.replayed and again.order.id == first.order.id
    with sf() as s:
        assert allocated(s, sku) == 2
        assert audit_count(s, "inventory.reserve") == 1
    with pytest.raises(inv.IdempotencyConflict):
        reserve(sf, {sku: 3}, key="checkout-retry-1")


def test_concurrent_duplicate_checkout_requests_reserve_once(sf):
    sku = make_sku(sf, on_hand=10)
    results = run_together(6, lambda _: reserve(sf, {sku: 2}, key="checkout-dup"))
    assert len({r.order.id for r in results}) == 1
    assert sorted(r.replayed for r in results) == [False] + [True] * 5
    with sf() as s:
        assert allocated(s, sku) == 2


def test_audit_failure_rolls_back_the_reservation(sf, monkeypatch):
    sku = make_sku(sf, on_hand=5)
    fail_audit(monkeypatch)
    with pytest.raises(RuntimeError):
        reserve(sf, {sku: 1})
    with sf() as s:
        assert s.scalar(select(Order.id)) is None and allocated(s, sku) == 0


# ---- concurrency -----------------------------------------------------------------------------
def test_many_customers_racing_for_the_last_unit(sf):
    sku = make_sku(sf, on_hand=1)

    def attempt(_):
        try:
            reserve(sf, {sku: 1})
            return "reserved"
        except inv.InsufficientStock:
            return "sold out"

    assert sorted(run_together(8, attempt)) == ["reserved"] + ["sold out"] * 7
    with sf() as s:
        assert allocated(s, sku) == 1


def test_concurrent_multi_sku_orders_never_partially_reserve(sf):
    a, b = make_sku(sf, on_hand=1), make_sku(sf, on_hand=1)
    # Opposite line order in each request: locks are taken in SKU order, so no deadlock.
    lines = [{a: 1, b: 1}, {b: 1, a: 1}] * 3

    def attempt(i):
        try:
            return reserve(sf, lines[i]).order.id
        except inv.InsufficientStock:
            return None

    winners = [r for r in run_together(6, attempt) if r]
    assert len(winners) == 1
    with sf() as s:
        assert allocated(s, a) == 1 and allocated(s, b) == 1
        assert statuses(s, winners[0]) == ["active", "active"]


def test_concurrent_reservation_and_staff_stock_removal(sf):
    sku = make_sku(sf, on_hand=2)

    def act(i):
        try:
            with sf() as s:
                if i == 0:
                    inv.create_order_with_reservations(s, new_order({sku: 2}), expires_at=soon())
                else:
                    inv.adjust_stock(
                        s,
                        variant_id=sku,
                        quantity_delta=-2,
                        reason="adjustment",
                        idempotency_key="race-removal",
                        actor=None,
                    )
            return "ok"
        except inv.InsufficientStock:
            return "refused"

    assert sorted(run_together(2, act)) == ["ok", "refused"]
    with sf() as s:
        assert allocated(s, sku) <= on_hand(s, sku)
        assert (on_hand(s, sku), allocated(s, sku)) in {(2, 2), (0, 0)}


def test_concurrent_release_and_commit_have_one_outcome(sf):
    for _ in range(5):
        sku = make_sku(sf, on_hand=1)
        order_id = reserve(sf, {sku: 1}).order.id

        def act(i, order_id=order_id):
            with sf() as s:
                try:
                    if i == 0:
                        return inv.commit_order_reservations(s, order_id).outcome
                    return inv.release_order_reservations(s, order_id, reason="cancelled").outcome
                except inv.CommittedStockNotReleasable:
                    return "release refused"

        outcomes = sorted(run_together(2, act))
        with sf() as s:
            final = statuses(s, order_id)
        assert outcomes in (
            sorted([Outcome.COMMITTED, "release refused"]),
            sorted([Outcome.RELEASED, Outcome.NEEDS_RECONCILIATION]),
        )
        assert final == (["committed"] if Outcome.COMMITTED in outcomes else ["released"])


def test_parallel_expiry_workers_expire_each_order_once(sf):
    sku = make_sku(sf, on_hand=20)
    orders = [reserve(sf, {sku: 1}, expires=soon(1)).order.id for _ in range(10)]
    wait_until_due()

    def work(_):
        with sf() as s:
            return inv.expire_due_reservations(s, limit=3)

    results = run_together(4, work)
    with sf() as s:
        while (extra := inv.expire_due_reservations(s, limit=100)).orders:
            results.append(extra)
        assert sum(r.orders for r in results) == 10 and sum(r.lines for r in results) == 10
        assert all(statuses(s, o) == ["expired"] for o in orders)
        assert audit_count(s, "inventory.reservation_expire") == 10
        assert allocated(s, sku) == 0
        assert inv.expire_due_reservations(s).orders == 0  # retry changes nothing


def test_expiry_skips_an_order_being_committed(sf):
    sku = make_sku(sf, on_hand=1)
    order_id = reserve(sf, {sku: 1}, expires=soon(1)).order.id
    wait_until_due()
    with sf() as holder:
        holder.begin()
        inv._lock_order(holder, order_id)  # e.g. a payment commit in progress
        with sf() as s:
            assert inv.expire_due_reservations(s).orders == 0
        holder.rollback()
    with sf() as s:
        assert inv.expire_due_reservations(s).orders == 1


# ---- finalization ----------------------------------------------------------------------------
def test_commit_once_and_repeat_is_a_no_op(sf):
    a, b = make_sku(sf, on_hand=2), make_sku(sf, on_hand=2)
    order_id = reserve(sf, {a: 1, b: 2}).order.id
    with sf() as s:
        first = inv.commit_order_reservations(s, order_id)
    with sf() as s:
        again = inv.commit_order_reservations(s, order_id)
        assert (first.outcome, first.lines_changed) == (Outcome.COMMITTED, 2)
        assert (again.outcome, again.lines_changed) == (Outcome.ALREADY_COMMITTED, 0)
        assert statuses(s, order_id) == ["committed", "committed"]
        assert inv.availability(s, b)["committed_quantity"] == 2
        assert on_hand(s, a) == 2  # commit does not deduct physical stock
        assert audit_count(s, "inventory.reservation_commit", order_id) == 1


def test_released_reservation_cannot_be_committed(sf):
    sku = make_sku(sf, on_hand=1)
    order_id = reserve(sf, {sku: 1}).order.id
    with sf() as s:
        inv.release_order_reservations(s, order_id, reason="payment_failed")
    with sf() as s:
        late = inv.commit_order_reservations(s, order_id)
        assert late.outcome == Outcome.NEEDS_RECONCILIATION
        assert statuses(s, order_id) == ["released"] and allocated(s, sku) == 0
        assert audit_count(s, "inventory.reservation_late_payment", order_id) == 1


def test_expired_reservation_cannot_be_committed(sf):
    sku = make_sku(sf, on_hand=1)
    order_id = reserve(sf, {sku: 1}, expires=soon(1)).order.id
    wait_until_due()
    with sf() as s:  # due but not yet processed by the worker
        assert inv.commit_order_reservations(s, order_id).outcome == Outcome.NEEDS_RECONCILIATION
        assert statuses(s, order_id) == ["expired"]
    with sf() as s:  # already expired by the worker
        assert inv.commit_order_reservations(s, order_id).outcome == Outcome.NEEDS_RECONCILIATION
        assert allocated(s, sku) == 0


def test_dispatch_issues_committed_stock_once(sf):
    sku = make_sku(sf, on_hand=3)
    order_id = reserve(sf, {sku: 2}).order.id
    with sf() as s:
        inv.commit_order_reservations(s, order_id)
    for _ in range(2):
        with sf() as s:
            assert inv.dispatch_order_inventory(s, order_id) == 1
    with sf() as s:
        assert on_hand(s, sku) == 1 and allocated(s, sku) == 0
        assert statuses(s, order_id) == ["fulfilled"]
        assert audit_count(s, "inventory.dispatch", order_id) == 1


# ---- release ---------------------------------------------------------------------------------
@pytest.mark.parametrize("reason", ["payment_failed", "cancelled"])
def test_release_restores_stock_exactly_once(sf, reason):
    sku = make_sku(sf, on_hand=2)
    order_id = reserve(sf, {sku: 2}).order.id
    with sf() as s:
        assert (
            inv.release_order_reservations(s, order_id, reason=reason).outcome == Outcome.RELEASED
        )
    with sf() as s:
        again = inv.release_order_reservations(s, order_id, reason=reason)
        assert again.outcome == Outcome.ALREADY_RELEASED
        assert inv.availability(s, sku)["available_quantity"] == 2
        assert audit_count(s, "inventory.reservation_release", order_id) == 1
    reserve(sf, {sku: 2})  # the released units can be sold again


def test_expiration_restores_stock(sf):
    sku = make_sku(sf, on_hand=1)
    order_id = reserve(sf, {sku: 1}, expires=soon(1)).order.id
    wait_until_due()
    with sf() as s:
        assert inv.expire_due_reservations(s).orders == 1
    with sf() as s:
        assert inv.release_order_reservations(s, order_id, reason="cancelled").outcome == (
            Outcome.ALREADY_RELEASED
        )
        assert inv.availability(s, sku)["available_quantity"] == 1


def test_committed_stock_is_not_silently_restored(sf):
    sku = make_sku(sf, on_hand=1)
    order_id = reserve(sf, {sku: 1}).order.id
    with sf() as s:
        inv.commit_order_reservations(s, order_id)
    with sf() as s, pytest.raises(inv.CommittedStockNotReleasable):
        inv.release_order_reservations(s, order_id, reason="cancelled")
    with sf() as s:
        assert statuses(s, order_id) == ["committed"] and allocated(s, sku) == 1
        assert inv.expire_due_reservations(s).orders == 0


def test_release_rejects_unknown_reason_and_other_customers_orders(sf, customer_auth):
    import uuid

    sku = make_sku(sf, on_hand=1)
    owner = uuid.UUID(customer_auth["user"]["id"])
    order_id = reserve(sf, {sku: 1}, user_id=owner).order.id
    with sf() as s, pytest.raises(ValueError):
        inv.release_order_reservations(s, order_id, reason="refund")
    with sf() as s, pytest.raises(inv.ReservationNotFound):
        inv.release_order_reservations(s, order_id, reason="cancelled", owner_user_id=uuid.uuid4())
    with sf() as s:
        assert statuses(s, order_id) == ["active"]
        result = inv.release_order_reservations(
            s, order_id, reason="cancelled", owner_user_id=owner
        )
        assert result.outcome == Outcome.RELEASED
    with sf() as s, pytest.raises(inv.ReservationNotFound):
        inv.commit_order_reservations(s, uuid.uuid4())


def test_audit_failure_rolls_back_transitions(sf, monkeypatch):
    sku = make_sku(sf, on_hand=1)
    order_id = reserve(sf, {sku: 1}).order.id
    fail_audit(monkeypatch, "inventory.reservation_")
    for call in (
        lambda s: inv.commit_order_reservations(s, order_id),
        lambda s: inv.release_order_reservations(s, order_id, reason="cancelled"),
    ):
        with sf() as s, pytest.raises(RuntimeError):
            call(s)
    with sf() as s:
        assert statuses(s, order_id) == ["active"] and allocated(s, sku) == 1


# ---- stock adjustments -----------------------------------------------------------------------
def adjust(sf, sku, delta, key, reason="adjustment"):
    with sf() as s:
        return inv.adjust_stock(
            s, variant_id=sku, quantity_delta=delta, reason=reason, idempotency_key=key, actor=None
        )


def test_receipt_creates_record_and_retries_are_idempotent(sf):
    sku = make_sku(sf, on_hand=None)
    first = adjust(sf, sku, 5, "receipt-0001", reason="receipt")
    again = adjust(sf, sku, 5, "receipt-0001", reason="receipt")
    assert not first.replayed and again.replayed and again.movement.id == first.movement.id
    with sf() as s:
        assert on_hand(s, sku) == 5
        assert audit_count(s, "inventory.adjust", sku) == 1
    with pytest.raises(inv.IdempotencyConflict):
        adjust(sf, sku, 6, "receipt-0001", reason="receipt")


def test_adjustment_cannot_remove_reserved_or_committed_stock(sf):
    sku = make_sku(sf, on_hand=3)
    order_id = reserve(sf, {sku: 2}).order.id
    with pytest.raises(inv.InsufficientStock) as err:
        adjust(sf, sku, -2, "remove-too-much")
    assert err.value.available == 1
    with sf() as s:
        inv.commit_order_reservations(s, order_id)
    adjust(sf, sku, -1, "remove-free-unit")
    with pytest.raises(inv.InsufficientStock):
        adjust(sf, sku, -1, "remove-committed")
    with sf() as s:
        assert on_hand(s, sku) == 2 and allocated(s, sku) == 2


@pytest.mark.parametrize(
    ("delta", "reason"), [(0, "adjustment"), (-1, "receipt"), (-1, "inspected_return"), (1, "x")]
)
def test_invalid_adjustments_rejected(sf, delta, reason):
    sku = make_sku(sf, on_hand=3)
    with pytest.raises(ValueError):
        adjust(sf, sku, delta, "bad-adjustment", reason=reason)
    with sf() as s:
        assert on_hand(s, sku) == 3


def test_adjustment_audit_failure_rolls_back_stock(sf, monkeypatch):
    sku = make_sku(sf, on_hand=3)
    fail_audit(monkeypatch)
    with pytest.raises(RuntimeError):
        adjust(sf, sku, 4, "receipt-audit-fails", reason="receipt")
    with sf() as s:
        assert on_hand(s, sku) == 3 and s.scalar(select(StockMovement.id)) is None


# ---- database guards (last line of defence, bypassing the services) --------------------------
def test_database_rejects_invalid_transitions_and_deletes(sf):
    sku = make_sku(sf, on_hand=2)
    order_id = reserve(sf, {sku: 1}).order.id
    with sf() as s:
        inv.commit_order_reservations(s, order_id)
    for sql in (
        "UPDATE stock_reservations SET status='released', released_at=now() WHERE order_id=:o",
        "UPDATE stock_reservations SET status='active' WHERE order_id=:o",
        "UPDATE stock_reservations SET quantity=2 WHERE order_id=:o",
        "DELETE FROM stock_reservations WHERE order_id=:o",
    ):
        with sf() as s, pytest.raises(DBAPIError):
            s.execute(text(sql), {"o": order_id})
            s.commit()


def _reservations(sf, order_id) -> int:
    with sf() as s:
        return s.execute(
            text("SELECT count(*) FROM stock_reservations WHERE order_id=:o"), {"o": order_id}
        ).scalar_one()


def test_the_dev_cleanup_setting_allows_deletes_only_inside_its_own_transaction(sf):
    """Migration b4e7d1a9c3f2: the development seed cleanup sets app.dev_seed_cleanup with
    SET LOCAL; the guard then lets the owner delete reservations in that transaction only."""
    order_id = reserve(sf, {make_sku(sf, on_hand=2): 1}).order.id
    delete = text("DELETE FROM stock_reservations WHERE order_id=:o")

    # A plain session setting is not enough once the transaction that set it locally ends.
    with sf() as s:
        s.execute(text("SET LOCAL app.dev_seed_cleanup = 'on'"))
        s.rollback()
        with pytest.raises(DBAPIError, match="never deleted"):
            s.execute(delete, {"o": order_id})
    # Any other value is refused.
    with sf() as s, pytest.raises(DBAPIError, match="never deleted"):
        s.execute(text("SET LOCAL app.dev_seed_cleanup = 'true'"))
        s.execute(delete, {"o": order_id})
    assert _reservations(sf, order_id) == 1

    # Inside the transaction that set it, the owner may delete.
    with sf() as s, s.begin():
        s.execute(text("SET LOCAL app.dev_seed_cleanup = 'on'"))
        s.execute(delete, {"o": order_id})
    assert _reservations(sf, order_id) == 0


def test_database_rejects_over_allocation_and_stock_below_allocation(sf):
    sku = make_sku(sf, on_hand=1)
    order_id = reserve(sf, {sku: 1}).order.id
    with sf() as s, pytest.raises((IntegrityError, DBAPIError)):
        s.execute(
            text(
                "INSERT INTO stock_reservations (id, order_id, variant_id, quantity, status, "
                "expires_at, idempotency_key) VALUES (gen_random_uuid(), :o, :v, 1, 'active', "
                "now() + interval '1 hour', 'raw-insert')"
            ),
            {"o": reserve(sf, {make_sku(sf, on_hand=1): 1}).order.id, "v": sku},
        )
        s.commit()
    with sf() as s, pytest.raises(DBAPIError):
        s.execute(
            text("UPDATE inventory_balances SET on_hand = 0 WHERE variant_id = :v"), {"v": sku}
        )
        s.commit()
    with sf() as s:
        assert on_hand(s, sku) == 1 and allocated(s, sku) == 1
        assert statuses(s, order_id) == ["active"]


def test_expiry_worker_moves_past_busy_orders_to_fill_its_batch(sf):
    sku = make_sku(sf, on_hand=2)
    busy = reserve(sf, {sku: 1}, expires=soon(1)).order.id
    free = reserve(sf, {sku: 1}, expires=soon(1.1)).order.id
    wait_until_due(1.4)
    with sf() as holder:
        holder.begin()
        inv._lock_order(holder, busy)  # the oldest due order is held by another worker
        with sf() as s:
            result = inv.expire_due_reservations(s, limit=1)
        assert (result.orders, result.skipped) == (1, 1)
        holder.rollback()
    with sf() as s:
        assert statuses(s, free) == ["expired"] and statuses(s, busy) == ["active"]
