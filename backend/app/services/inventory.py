"""Stock reservation lifecycle and physical stock changes (ADR-002, approved 2026-10-22).

Lifecycle, applied to all of an order's reservation lines together:

    active    -> committed  payment success before expiry          commit_order_reservations
    active    -> released   cancellation or payment failure        release_order_reservations
    active    -> expired    hold timeout                           expire_due_reservations
    committed -> fulfilled  dispatch (physical stock issued)       dispatch_order_inventory

Repeating a transition that already happened is a no-op. Committed (paid) stock is never
released here; that needs an approved compensating workflow. A payment success that arrives after
release or expiry returns NEEDS_RECONCILIATION: stock is not reserved again automatically.

Concurrency:
- Creating reservations, dispatching and lowering physical stock lock the SKUs'
  inventory_balances rows in variant-ID order, then check availability. No read-then-write.
- Every reservation transition of an order takes a per-order advisory lock; expiry workers use
  a try-lock and skip orders another transaction is handling.
- Time comes from the database clock (clock_timestamp()), never the application server.
- Database triggers reject invalid transitions and over-allocation as a last line of defence.

Transactions: each function joins the caller's transaction through a savepoint, or opens and
commits its own. Every change commits together with its audit record. Redis is not used here;
PostgreSQL is the only source of truth for stock.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.request_context import RequestContext
from app.models import (
    Brand,
    Category,
    InventoryBalance,
    Order,
    OrderStatusHistory,
    PaymentAttempt,
    Product,
    ProductVariant,
    StockMovement,
    StockReservation,
)
from app.models.identity import User
from app.repositories.category_tree import category_visible
from app.services.audit_service import AuditService
from app.services.notification_service import record_order_event
from app.services.promotion_service import release_for_order

ALLOCATING_STATES = ("active", "committed")
RELEASE_REASONS = frozenset({"cancelled", "payment_failed"})
ADJUSTMENT_REASONS = frozenset({"receipt", "adjustment", "inspected_return"})
INCREASE_ONLY_REASONS = frozenset({"receipt", "inspected_return"})
MAX_QUANTITY = 2_147_483_647  # PostgreSQL integer
ORDER_LOCK_NAMESPACE = 7302  # pg_advisory_xact_lock(namespace, hashtext(order_id))


# ---- errors and results ----------------------------------------------------------------------
class InventoryError(Exception):
    """Base class for inventory rule violations; messages are safe to show."""


class InventoryUnavailable(InventoryError):
    """Stock cannot be reserved or removed; nothing was changed."""


class UnknownSku(InventoryUnavailable):
    def __init__(self, variant_ids: Iterable[UUID]):
        self.variant_ids = sorted(variant_ids)
        super().__init__("One or more SKUs do not exist.")


class SkuNotSellable(InventoryUnavailable):
    def __init__(self, variant_ids: Iterable[UUID]):
        self.variant_ids = sorted(variant_ids)
        super().__init__("One or more SKUs are not currently sold.")


class InsufficientStock(InventoryUnavailable):
    def __init__(self, variant_id: UUID, requested: int, available: int):
        self.variant_id, self.requested, self.available = variant_id, requested, max(available, 0)
        super().__init__(
            f"Insufficient stock for SKU {variant_id}: requested {requested}, "
            f"available {self.available}."
        )


class InvalidReservationState(InventoryError):
    """The requested transition is not allowed from the reservations' current state."""


class ReservationNotFound(InvalidReservationState):
    def __init__(self) -> None:
        super().__init__("No stock reservations found for this order.")


class CommittedStockNotReleasable(InvalidReservationState):
    def __init__(self) -> None:
        super().__init__(
            "Committed (paid) stock cannot be released without an approved compensating workflow."
        )


class IdempotencyConflict(InventoryError):
    """An idempotency key was reused for a different request."""


class TransitionOutcome(StrEnum):
    COMMITTED = "committed"
    ALREADY_COMMITTED = "already_committed"
    RELEASED = "released"
    ALREADY_RELEASED = "already_released"
    NEEDS_RECONCILIATION = "needs_reconciliation"


@dataclass(frozen=True)
class ReservationResult:
    order: Order
    replayed: bool


@dataclass(frozen=True)
class TransitionResult:
    outcome: TransitionOutcome
    order_id: UUID
    lines_changed: int


@dataclass(frozen=True)
class ExpiryResult:
    orders: int
    lines: int
    skipped: int = 0  # due orders held by another transaction at the time


@dataclass(frozen=True)
class AdjustmentResult:
    movement: StockMovement
    balance: InventoryBalance
    replayed: bool


# ---- helpers ---------------------------------------------------------------------------------
def _atomic(session: Session) -> AbstractContextManager:
    """Own a transaction or isolate this operation in the caller's transaction."""
    return session.begin_nested() if session.in_transaction() else session.begin()


def _db_now(session: Session) -> datetime:
    """Current database time (advances within a transaction, unlike now())."""
    now: datetime = session.execute(select(func.clock_timestamp())).scalar_one()
    return now


def _lock_order(session: Session, order_id: UUID) -> None:
    """The order's transaction-scoped advisory lock (re-entrant within one transaction).

    Lock order for every change to an existing order: this advisory lock first, then the order
    row (FOR UPDATE), then its reservations, payment attempts and redemption. Status changes
    (order_service.change_status) take it before the row; the expiry job takes it with a
    try-lock and the row with SKIP LOCKED, so it never waits and busy orders are skipped. One
    order for all paths means no lock cycle (no deadlock) between them."""
    session.execute(
        text("SELECT pg_advisory_xact_lock(CAST(:ns AS integer), hashtext(:oid))"),
        {"ns": ORDER_LOCK_NAMESPACE, "oid": str(order_id)},
    )


lock_order = _lock_order  # for order_service.change_status (same lock, same order)


def _try_lock_order_row(session: Session, order_id: UUID) -> bool:
    """Lock the order row without waiting; False when another transaction holds it."""
    locked = session.scalar(
        select(Order.id).where(Order.id == order_id).with_for_update(skip_locked=True)
    )
    return locked is not None


def _try_lock_order(session: Session, order_id: UUID) -> bool:
    return bool(
        session.scalar(
            text("SELECT pg_try_advisory_xact_lock(CAST(:ns AS integer), hashtext(:oid))"),
            {"ns": ORDER_LOCK_NAMESPACE, "oid": str(order_id)},
        )
    )


def check_quantity(quantity: Any, what: str) -> int:
    """Return a whole quantity from 1 to MAX_QUANTITY, or raise ValueError naming `what`.

    Public so that pricing, cart and checkout apply exactly the stock service's quantity rule.
    """
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise ValueError(f"{what} must be an integer")
    if quantity <= 0 or quantity > MAX_QUANTITY:
        raise ValueError(f"{what} must be between 1 and {MAX_QUANTITY}")
    return quantity


def _requested_quantities(order: Order) -> dict[UUID, int]:
    requested: dict[UUID, int] = defaultdict(int)
    for item in order.items:
        if item.variant_id is None:
            raise ValueError("every reservable order item must reference a SKU")
        requested[item.variant_id] += check_quantity(item.quantity, "order quantities")
    if not requested:
        raise ValueError("an order must contain at least one reservable item")
    for quantity in requested.values():
        check_quantity(quantity, "total quantity per SKU")
    return dict(requested)


def _allocated(session: Session, variant_ids: Iterable[UUID]) -> dict[UUID, int]:
    rows = session.execute(
        select(StockReservation.variant_id, func.coalesce(func.sum(StockReservation.quantity), 0))
        .where(
            StockReservation.variant_id.in_(list(variant_ids)),
            StockReservation.status.in_(ALLOCATING_STATES),
        )
        .group_by(StockReservation.variant_id)
    ).all()
    return {variant_id: int(quantity) for variant_id, quantity in rows}


def _lock_balances(session: Session, variant_ids: Iterable[UUID]) -> dict[UUID, InventoryBalance]:
    balances = session.scalars(
        select(InventoryBalance)
        .where(InventoryBalance.variant_id.in_(sorted(set(variant_ids))))
        .order_by(InventoryBalance.variant_id)
        .with_for_update()
    )
    return {balance.variant_id: balance for balance in balances}


def _order_reservations(session: Session, order_id: UUID) -> list[StockReservation]:
    return list(
        session.scalars(
            select(StockReservation)
            .where(StockReservation.order_id == order_id)
            .order_by(StockReservation.variant_id)
            .with_for_update()
        )
    )


def _audit(
    session: Session,
    action: str,
    entity_type: str,
    entity_id: UUID,
    *,
    actor: User | None,
    ctx: RequestContext | None,
    details: dict[str, Any],
    status: str = "success",
) -> None:
    AuditService.log_event(
        db=session,
        action=action,
        status=status,
        entity_type=entity_type,
        entity_id=entity_id,
        actor=actor,
        context=ctx,
        details=details,
    )


def _line_details(rows: list[StockReservation]) -> dict[str, Any]:
    return {"lines": len(rows), "quantity": sum(row.quantity for row in rows)}


# ---- reservation -----------------------------------------------------------------------------
def sellable_variants(session: Session, variant_ids: set[UUID]) -> dict[UUID, bool]:
    """Sellability of each existing SKU (unknown IDs are absent from the result).

    Sellable means: the variant is active, its product is `active`, its category is visible
    (active, and so is its main category), and its brand (if any) is active. The cart
    (module 11) flags lines with this; check_sellable raises with it.
    """
    if not variant_ids:
        return {}
    rows = session.execute(
        select(
            ProductVariant.id,
            ProductVariant.is_active,
            Product.status,
            and_(Category.is_active, category_visible(Product.category_id)),
            Brand.is_active,
        )
        .join(Product, Product.id == ProductVariant.product_id)
        .join(Category, Category.id == Product.category_id)
        .outerjoin(Brand, Brand.id == Product.brand_id)
        .where(ProductVariant.id.in_(variant_ids))
    ).all()
    return {
        variant_id: bool(
            variant_active
            and product_status == "active"
            and category_active
            and brand_active is not False
        )
        for variant_id, variant_active, product_status, category_active, brand_active in rows
    }


def check_sellable(session: Session, variant_ids: set[UUID]) -> None:
    """Raise UnknownSku or SkuNotSellable unless every SKU can be sold right now.

    Uses the sellable_variants rule. Public so that pricing, cart and checkout share this rule.
    """
    sellable = sellable_variants(session, variant_ids)
    if set(sellable) != variant_ids:
        raise UnknownSku(variant_ids - set(sellable))
    not_sellable = {variant_id for variant_id, ok in sellable.items() if not ok}
    if not_sellable:
        raise SkuNotSellable(not_sellable)


def _replay_reservation(
    session: Session, existing: Order, requested: dict[UUID, int]
) -> ReservationResult:
    reserved = {
        variant_id: quantity
        for variant_id, quantity in session.execute(
            select(StockReservation.variant_id, StockReservation.quantity).where(
                StockReservation.order_id == existing.id
            )
        ).all()
    }
    if reserved != requested:
        raise IdempotencyConflict("This checkout key was already used for a different order.")
    return ReservationResult(order=existing, replayed=True)


def _order_by_checkout_key(session: Session, key: str) -> Order | None:
    return session.scalar(select(Order).where(Order.checkout_idempotency_key == key))


def create_order_with_reservations(
    session: Session,
    order: Order,
    *,
    expires_at: datetime,
    actor: User | None = None,
    ctx: RequestContext | None = None,
) -> ReservationResult:
    """Persist an order and reserve every line, or reserve nothing (all-or-nothing).

    The caller (the future checkout service) supplies server-priced order snapshots and the hold
    expiry; no default hold duration is approved. Retrying with the same
    order.checkout_idempotency_key returns the original order (replayed=True) without reserving
    again; reusing the key for different lines raises IdempotencyConflict.
    """
    if expires_at.tzinfo is None:
        raise ValueError("expires_at must be timezone-aware")
    if not order.checkout_idempotency_key:
        raise ValueError("order.checkout_idempotency_key is required")
    requested = _requested_quantities(order)
    key = order.checkout_idempotency_key
    try:
        with _atomic(session):
            existing = _order_by_checkout_key(session, key)
            if existing is not None:
                return _replay_reservation(session, existing, requested)
            if expires_at <= _db_now(session):
                raise ValueError("expires_at must be in the future (database time)")
            check_sellable(session, set(requested))
            # A concurrent duplicate checkout waits on the unique key here, before any stock lock.
            session.add(order)
            session.flush()
            session.add(OrderStatusHistory(order_id=order.id, status=order.status))
            balances = _lock_balances(session, requested)
            allocated = _allocated(session, requested)
            for variant_id in sorted(requested):
                balance = balances.get(variant_id)  # no inventory record means zero stock
                physical = balance.on_hand - balance.unavailable_quantity if balance else 0
                available = physical - allocated.get(variant_id, 0)
                if available < requested[variant_id]:
                    raise InsufficientStock(variant_id, requested[variant_id], available)
            rows = [
                StockReservation(
                    order_id=order.id,
                    variant_id=variant_id,
                    quantity=quantity,
                    status="active",
                    expires_at=expires_at,
                    idempotency_key=f"order:{order.id}:sku:{variant_id}",
                )
                for variant_id, quantity in sorted(requested.items())
            ]
            session.add_all(rows)
            session.flush()
            _audit(
                session,
                "inventory.reserve",
                "order",
                order.id,
                actor=actor,
                ctx=ctx,
                details={**_line_details(rows), "expires_at": expires_at.isoformat()},
            )
    except IntegrityError as exc:
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", "") or ""
        if "checkout_idempotency_key" not in constraint:
            raise
        with _atomic(session):
            existing = _order_by_checkout_key(session, key)
            if existing is None:
                raise
            return _replay_reservation(session, existing, requested)
    return ReservationResult(order=order, replayed=False)


# ---- transitions -----------------------------------------------------------------------------
def _expire_rows(
    session: Session, order_id: UUID, rows: list[StockReservation], now: datetime
) -> int:
    for row in rows:
        row.status = "expired"
        row.released_at = now
        row.release_reason = "expired"
    session.flush()
    _audit(
        session,
        "inventory.reservation_expire",
        "order",
        order_id,
        actor=None,
        ctx=None,
        details=_line_details(rows),
    )
    return len(rows)


def commit_order_reservations(
    session: Session,
    order_id: UUID,
    *,
    actor: User | None = None,
    ctx: RequestContext | None = None,
) -> TransitionResult:
    """Payment succeeded: move the order's active holds to committed, exactly once.

    Internal operation for the future payment service; never exposed over HTTP. A repeat is a
    no-op (ALREADY_COMMITTED). If the holds were released or have expired, nothing is committed
    and the result is NEEDS_RECONCILIATION (an audited late payment); due holds are expired.
    """
    with _atomic(session):
        _lock_order(session, order_id)
        rows = _order_reservations(session, order_id)
        if not rows:
            raise ReservationNotFound()
        statuses = {row.status for row in rows}
        if statuses <= {"committed", "fulfilled"}:
            return TransitionResult(TransitionOutcome.ALREADY_COMMITTED, order_id, 0)
        if statuses != {"active"} and not statuses <= {"released", "expired"}:
            raise InvalidReservationState(f"Inconsistent reservation states: {sorted(statuses)}.")
        now = _db_now(session)
        if statuses == {"active"} and all(row.expires_at > now for row in rows):
            for row in rows:
                row.status = "committed"
                row.committed_at = now
            session.flush()
            _audit(
                session,
                "inventory.reservation_commit",
                "order",
                order_id,
                actor=actor,
                ctx=ctx,
                details=_line_details(rows),
            )
            return TransitionResult(TransitionOutcome.COMMITTED, order_id, len(rows))
        if statuses == {"active"}:
            _expire_rows(session, order_id, rows, now)
        _audit(
            session,
            "inventory.reservation_late_payment",
            "order",
            order_id,
            actor=actor,
            ctx=ctx,
            status="needs_reconciliation",
            details={**_line_details(rows), "previous_states": sorted(statuses)},
        )
        return TransitionResult(TransitionOutcome.NEEDS_RECONCILIATION, order_id, 0)


def release_order_reservations(
    session: Session,
    order_id: UUID,
    *,
    reason: str,
    owner_user_id: UUID | None = None,
    actor: User | None = None,
    ctx: RequestContext | None = None,
) -> TransitionResult:
    """Cancellation or payment failure: release the order's active holds, exactly once.

    reason is 'cancelled' or 'payment_failed'. A repeat, or holds that already expired, is a
    no-op (ALREADY_RELEASED). Committed stock raises CommittedStockNotReleasable. When
    owner_user_id is given (a customer cancelling), another customer's order is reported as
    not found.
    """
    if reason not in RELEASE_REASONS:
        raise ValueError(f"reason must be one of {sorted(RELEASE_REASONS)}")
    with _atomic(session):
        if owner_user_id is not None:
            owner = session.scalar(select(Order.user_id).where(Order.id == order_id))
            if owner != owner_user_id:
                raise ReservationNotFound()
        _lock_order(session, order_id)
        rows = _order_reservations(session, order_id)
        if not rows:
            raise ReservationNotFound()
        statuses = {row.status for row in rows}
        if statuses & {"committed", "fulfilled"}:
            raise CommittedStockNotReleasable()
        if statuses <= {"released", "expired"}:
            return TransitionResult(TransitionOutcome.ALREADY_RELEASED, order_id, 0)
        if statuses != {"active"}:
            raise InvalidReservationState(f"Inconsistent reservation states: {sorted(statuses)}.")
        now = _db_now(session)
        for row in rows:
            row.status = "released"
            row.released_at = now
            row.release_reason = reason
        session.flush()
        _audit(
            session,
            "inventory.reservation_release",
            "order",
            order_id,
            actor=actor,
            ctx=ctx,
            details={**_line_details(rows), "reason": reason},
        )
        return TransitionResult(TransitionOutcome.RELEASED, order_id, len(rows))


class HoldNotActive(InvalidReservationState):
    """The order has no active, unexpired holds to move."""


def change_hold_expiry(
    session: Session,
    order_id: UUID,
    expires_at: datetime,
    *,
    actor: User | None = None,
    ctx: RequestContext | None = None,
) -> datetime:
    """Move the expiry of the order's active holds (a payment-method switch, frontend phase 4,
    2026-10-27). Every hold must still be active and unexpired, and the new expiry must be in
    the future; the database trigger refuses one beyond 24 hours after a hold was created.
    Returns the previous expiry. Audited."""
    if expires_at.tzinfo is None:
        raise ValueError("expires_at must be timezone-aware")
    with _atomic(session):
        _lock_order(session, order_id)
        rows = _order_reservations(session, order_id)
        now = _db_now(session)
        if not rows or any(row.status != "active" or row.expires_at <= now for row in rows):
            raise HoldNotActive("The order's stock is no longer held.")
        if expires_at <= now:
            raise ValueError("expires_at must be in the future (database time)")
        previous = min(row.expires_at for row in rows)
        for row in rows:
            row.expires_at = expires_at
        session.flush()
        _audit(
            session,
            "inventory.reservation_hold_change",
            "order",
            order_id,
            actor=actor,
            ctx=ctx,
            details={
                **_line_details(rows),
                "previous_expires_at": previous.isoformat(),
                "expires_at": expires_at.isoformat(),
            },
        )
        return previous


def expire_due_reservations(session: Session, *, limit: int = 100) -> ExpiryResult:
    """Expire holds whose expiry has passed (database time), whole orders at a time.

    Safe to run repeatedly and from several workers at once: each order is taken with a
    try-lock and re-checked after locking, so no hold is expired twice and expiry cannot race a
    commit. Orders another transaction holds are skipped (counted in `skipped`) and the worker
    keeps looking for free due orders until the batch is full or none remain. Committed stock
    never expires. Pending expirations live in the database, so restarts lose nothing.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    orders = lines = skipped = 0
    seen: set[UUID] = set()
    with _atomic(session):
        while orders < limit:
            now = _db_now(session)
            query = (
                select(StockReservation.order_id)
                .where(StockReservation.status == "active", StockReservation.expires_at <= now)
                .group_by(StockReservation.order_id)
                .order_by(func.min(StockReservation.expires_at), StockReservation.order_id)
                .limit(limit - orders)
            )
            if seen:
                query = query.where(StockReservation.order_id.not_in(seen))
            candidates = session.scalars(query).all()
            if not candidates:
                break
            for order_id in candidates:
                seen.add(order_id)
                # Advisory lock, then the order row (the common lock order), both without
                # waiting: an order another transaction is changing is skipped, never waited on.
                if not _try_lock_order(session, order_id) or not _try_lock_order_row(
                    session, order_id
                ):
                    skipped += 1
                    continue
                active = [
                    row for row in _order_reservations(session, order_id) if row.status == "active"
                ]
                now = _db_now(session)
                if not active or any(row.expires_at > now for row in active):
                    continue
                lines += _expire_rows(session, order_id, active, now)
                # RE-026 B3: an expired reservation releases the order's promotion use too, in
                # the same transaction.
                release_for_order(session, order_id, reason="expired")
                _cancel_unpaid_order(session, order_id)
                orders += 1
    return ExpiryResult(orders=orders, lines=lines, skipped=skipped)


def cancel_unpaid_order(session: Session, order_id: UUID) -> None:
    """Public name for payments (module 15): a late payment found the hold lapsed."""
    _cancel_unpaid_order(session, order_id)


def _cancel_unpaid_order(session: Session, order_id: UUID) -> None:
    """§7 Q12/Q13: an order whose stock hold expired is cancelled by the system (reason
    payment_timeout), and its unpaid payment attempts expire. Only active holds expire, so the
    order was neither paid nor confirmed (cash on delivery); dispatched, delivered and already
    cancelled orders are left alone. The caller already holds the order's advisory lock and
    row lock (expire_due_reservations), so nothing here waits."""
    order = session.get(Order, order_id, with_for_update=True)
    if order is None or order.status in ("dispatched", "delivered", "cancelled"):
        return
    previous = order.status
    order.status = "cancelled"
    session.add(OrderStatusHistory(order_id=order_id, status="cancelled", reason="payment_timeout"))
    # Module 17: the customer's notification, recorded in this transaction, sent after commit.
    record_order_event(session, order, "cancelled")
    session.execute(
        update(PaymentAttempt)
        .where(
            PaymentAttempt.order_id == order_id, PaymentAttempt.status.in_(("created", "pending"))
        )
        .values(status="expired")
    )
    session.flush()
    _audit(
        session,
        "order.status_change",
        "order",
        order_id,
        actor=None,
        ctx=None,
        details={"from_status": previous, "to_status": "cancelled", "reason": "payment_timeout"},
    )


def dispatch_order_inventory(
    session: Session,
    order_id: UUID,
    *,
    actor: User | None = None,
    ctx: RequestContext | None = None,
) -> int:
    """Issue committed stock: ledger movement, lower on_hand and fulfil holds, atomically."""
    with _atomic(session):
        _lock_order(session, order_id)
        reservations = _order_reservations(session, order_id)
        if reservations and all(row.status == "fulfilled" for row in reservations):
            source_keys = [f"dispatch:{order_id}:{row.variant_id}" for row in reservations]
            movement_count = session.scalar(
                select(func.count(StockMovement.id)).where(
                    StockMovement.source_key.in_(source_keys)
                )
            )
            if movement_count == len(reservations):
                return len(reservations)
            raise InvalidReservationState("fulfilled reservations are missing stock movements")
        if not reservations or any(row.status != "committed" for row in reservations):
            raise InvalidReservationState(
                "dispatch requires committed reservations for every order SKU"
            )
        balances = _lock_balances(session, [row.variant_id for row in reservations])
        allocated = _allocated(session, balances)
        for reservation in reservations:
            balance = balances.get(reservation.variant_id)
            if balance is None:
                raise InvalidReservationState("inventory is missing for a committed reservation")
            others = allocated.get(reservation.variant_id, 0) - reservation.quantity
            if balance.on_hand - balance.unavailable_quantity - others < reservation.quantity:
                raise InventoryUnavailable("physical stock no longer covers committed reservation")
            balance.on_hand -= reservation.quantity
        now = _db_now(session)
        for reservation in reservations:
            reservation.status = "fulfilled"
            reservation.fulfilled_at = now
            session.add(
                StockMovement(
                    variant_id=reservation.variant_id,
                    quantity_delta=-reservation.quantity,
                    reason="dispatch",
                    actor_user_id=actor.id if actor else None,
                    source_key=f"dispatch:{order_id}:{reservation.variant_id}",
                )
            )
        session.flush()
        _audit(
            session,
            "inventory.dispatch",
            "order",
            order_id,
            actor=actor,
            ctx=ctx,
            details=_line_details(reservations),
        )
    return len(reservations)


# ---- physical stock adjustments ------------------------------------------------------------
def adjustment_source_key(actor: User | None, idempotency_key: str) -> str:
    return f"adjust:{actor.id if actor else 'system'}:{idempotency_key}"


def _replay_adjustment(
    existing: StockMovement,
    balance: InventoryBalance | None,
    variant_id: UUID,
    quantity_delta: int,
    reason: str,
) -> AdjustmentResult:
    if (existing.variant_id, existing.quantity_delta, existing.reason) != (
        variant_id,
        quantity_delta,
        reason,
    ):
        raise IdempotencyConflict("This idempotency key was already used for a different change.")
    assert balance is not None
    return AdjustmentResult(movement=existing, balance=balance, replayed=True)


def adjust_stock(
    session: Session,
    *,
    variant_id: UUID,
    quantity_delta: int,
    reason: str,
    idempotency_key: str,
    actor: User | None,
    ctx: RequestContext | None = None,
    note: str | None = None,
) -> AdjustmentResult:
    """Apply a physical receipt, adjustment or inspected return with its ledger entry and audit.

    Never lowers stock below what is reserved, committed or unavailable (InsufficientStock).
    Retrying with the same idempotency key replays the original result; reusing the key for a
    different change raises IdempotencyConflict. Keys are scoped to the actor.
    """
    if reason not in ADJUSTMENT_REASONS:
        raise ValueError(f"reason must be one of {sorted(ADJUSTMENT_REASONS)}")
    if isinstance(quantity_delta, bool) or not isinstance(quantity_delta, int):
        raise ValueError("quantity_delta must be an integer")
    if quantity_delta == 0 or abs(quantity_delta) > MAX_QUANTITY:
        raise ValueError(f"quantity_delta must be nonzero and at most {MAX_QUANTITY} in size")
    if reason in INCREASE_ONLY_REASONS and quantity_delta < 0:
        raise ValueError(f"{reason} must increase stock")
    if not idempotency_key:
        raise ValueError("idempotency_key is required")
    source_key = adjustment_source_key(actor, idempotency_key)

    def lookup() -> StockMovement | None:
        return session.scalar(select(StockMovement).where(StockMovement.source_key == source_key))

    try:
        with _atomic(session):
            variant = session.get(ProductVariant, variant_id)
            if variant is None:
                raise UnknownSku([variant_id])
            session.execute(
                pg_insert(InventoryBalance)
                .values(id=uuid4(), variant_id=variant_id, on_hand=0, unavailable_quantity=0)
                .on_conflict_do_nothing(index_elements=["variant_id"])
            )
            balance = _lock_balances(session, [variant_id])[variant_id]
            # Checked after the lock, so a concurrent duplicate sees the first one's movement.
            existing = lookup()
            if existing is not None:
                return _replay_adjustment(existing, balance, variant_id, quantity_delta, reason)
            allocated = _allocated(session, [variant_id]).get(variant_id, 0)
            on_hand_before = balance.on_hand
            next_on_hand = on_hand_before + quantity_delta
            if next_on_hand > MAX_QUANTITY:
                raise ValueError("resulting on_hand is too large")
            if next_on_hand < balance.unavailable_quantity + allocated:
                raise InsufficientStock(
                    variant_id,
                    -quantity_delta,
                    on_hand_before - balance.unavailable_quantity - allocated,
                )
            balance.on_hand = next_on_hand
            movement = StockMovement(
                variant_id=variant_id,
                quantity_delta=quantity_delta,
                reason=reason,
                actor_user_id=actor.id if actor else None,
                source_key=source_key,
                note=note,
            )
            session.add(movement)
            session.flush()
            _audit(
                session,
                "inventory.adjust",
                "inventory",
                variant_id,
                actor=actor,
                ctx=ctx,
                details={
                    "sku": variant.sku,
                    "reason": reason,
                    "quantity_delta": quantity_delta,
                    "on_hand_before": on_hand_before,
                    "on_hand_after": next_on_hand,
                    "movement_id": str(movement.id),
                },
            )
    except IntegrityError as exc:
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", "") or ""
        if "source_key" not in constraint:
            raise
        with _atomic(session):
            existing = lookup()
            if existing is None:
                raise
            replay_balance = session.scalar(
                select(InventoryBalance).where(InventoryBalance.variant_id == existing.variant_id)
            )
            return _replay_adjustment(existing, replay_balance, variant_id, quantity_delta, reason)
    return AdjustmentResult(movement=movement, balance=balance, replayed=False)


# ---- stock figures (one calculation for a single SKU and for the staff list) ----------------
STOCK_FIGURES = (
    "on_hand",
    "unavailable_quantity",
    "reserved_quantity",
    "committed_quantity",
    "available_quantity",
)


@dataclass(frozen=True)
class StockFigureColumns:
    """SQL expressions of one stock-figures query, for filtering and ordering on them."""

    on_hand: Any
    unavailable_quantity: Any
    reserved_quantity: Any
    committed_quantity: Any
    available_quantity: Any
    has_inventory_record: Any
    is_low_stock: Any


def stock_figures(variant_ids: Iterable[UUID] | None = None) -> tuple[Any, StockFigureColumns]:
    """SELECT of one row per variant (SKU) with its stock figures, and those columns.

    - reserved: units in 'active' reservations; committed: units in 'committed' ones. Released,
      expired and fulfilled reservations hold nothing (dispatch lowers on_hand instead). An
      active hold past its expiry still holds stock until the expiry job marks it expired.
    - available = on_hand - unavailable - reserved - committed, never below 0. A SKU without an
      inventory record has zeros.
    - low stock = available <= low_stock_threshold and low_stock_threshold > 0.

    `variant_ids` limits the reservation totals to those SKUs (the single-SKU read); the caller
    adds its own WHERE clauses for the rows.
    """
    holds = select(
        StockReservation.variant_id.label("variant_id"),
        func.sum(StockReservation.quantity)
        .filter(StockReservation.status == "active")
        .label("reserved"),
        func.sum(StockReservation.quantity)
        .filter(StockReservation.status == "committed")
        .label("committed"),
    ).where(StockReservation.status.in_(ALLOCATING_STATES))
    if variant_ids is not None:
        holds = holds.where(StockReservation.variant_id.in_(list(variant_ids)))
    held = holds.group_by(StockReservation.variant_id).subquery("held")
    on_hand = func.coalesce(InventoryBalance.on_hand, 0)
    unavailable = func.coalesce(InventoryBalance.unavailable_quantity, 0)
    reserved = func.coalesce(held.c.reserved, 0)
    committed = func.coalesce(held.c.committed, 0)
    available = func.greatest(on_hand - unavailable - reserved - committed, 0)
    columns = StockFigureColumns(
        on_hand=on_hand,
        unavailable_quantity=unavailable,
        reserved_quantity=reserved,
        committed_quantity=committed,
        available_quantity=available,
        has_inventory_record=InventoryBalance.id.is_not(None),
        is_low_stock=(ProductVariant.low_stock_threshold > 0)
        & (available <= ProductVariant.low_stock_threshold),
    )
    query = (
        select(
            ProductVariant.id.label("variant_id"),
            on_hand.label("on_hand"),
            unavailable.label("unavailable_quantity"),
            reserved.label("reserved_quantity"),
            committed.label("committed_quantity"),
            available.label("available_quantity"),
            columns.has_inventory_record.label("has_inventory_record"),
            columns.is_low_stock.label("is_low_stock"),
        )
        .outerjoin(InventoryBalance, InventoryBalance.variant_id == ProductVariant.id)
        .outerjoin(held, held.c.variant_id == ProductVariant.id)
    )
    return query, columns


def availability(session: Session, variant_id: UUID) -> dict[str, int]:
    """Current stock figures for one SKU (zeros when no inventory record exists)."""
    query, _ = stock_figures([variant_id])
    row = session.execute(query.where(ProductVariant.id == variant_id)).mappings().one_or_none()
    return {name: int(row[name]) if row else 0 for name in STOCK_FIGURES}
