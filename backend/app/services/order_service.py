"""Orders (modules A4 and 14): status changes and assignment, customer history and detail,
guest lookup, and the staff list and detail.

Payment state on the order's payment attempts follows only the approved rules (§7 Q12-Q14):
- Confirming a cash-on-delivery order commits its stock (Q13); a hold that has already lapsed
  cannot be committed (409 inventory_conflict).
- Delivering a cash-on-delivery order marks its pending payment 'succeeded' (Q14) and issues
  its invoice in the same transaction (module 16, §7 Q19).
- Cancelling an order (before dispatch; the transitions allow nothing later) releases its stock
  and promotion use, and an unpaid attempt ('created' or 'pending') becomes 'cancelled'.
Mobile-money payments are settled by the payments module (15), not here.
A move to confirmed, dispatched, delivered or cancelled records the customer's notification in
the same transaction (module 17); it is sent only after the commit.
"""

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import (
    Conflict,
    NotFound,
    ServiceUnavailable,
    TooManyRequests,
    ValidationFailed,
    field_error,
)
from app.core.identifiers import validate_rwanda_phone
from app.core.rate_limit import LoginRateLimiter, RateLimitStoreUnavailable
from app.core.request_context import RequestContext
from app.db.transaction import atomic
from app.models import SellerOrder, StockReservation
from app.models.commerce import (
    NOTIFICATION_EVENTS,
    Order,
    OrderItem,
    OrderStatusHistory,
    PaymentAttempt,
)
from app.models.engagement import ProductReview
from app.models.identity import StaffRoleAssignment, User
from app.repositories.catalog import public_product_slugs
from app.repositories.order_repository import OrderRepository
from app.schemas.order import (
    OrderAssignee,
    OrderAssigneesResponse,
    OrderDetailResponse,
    OrderHistoryEntry,
    OrderLineResponse,
    OrderPaymentResponse,
    OrderSummaryResponse,
    StaffOrderDetailResponse,
    StaffOrderSummaryResponse,
    StaffPaymentResponse,
)
from app.schemas.pagination import Page, page_offset
from app.services.audit_service import AuditService, identifier_ref
from app.services.inventory import (
    InvalidReservationState,
    InventoryUnavailable,
    TransitionOutcome,
    commit_order_reservations,
    dispatch_order_inventory,
    lock_order,
    release_order_reservations,
)
from app.services.invoice_service import issue_for_order
from app.services.line_images import line_images
from app.services.notification_service import record_order_event
from app.services.promotion_service import release_for_order
from app.services.seller_order_service import staff_seller_orders
from app.services.seller_order_status import cancel_seller_orders

CASH_ON_DELIVERY = "cash_on_delivery"
UNPAID = ("created", "pending")
LOOKUP_LIMITED = "Too many failed order lookups; try again later."
LOOKUP_UNAVAILABLE = "Order lookup is temporarily unavailable; try again shortly."
logger = logging.getLogger("app.orders")


def _payments(db: Session, order_ids: list[UUID]) -> dict[UUID, list[PaymentAttempt]]:
    found: dict[UUID, list[PaymentAttempt]] = {order_id: [] for order_id in order_ids}
    if order_ids:
        query = (
            select(PaymentAttempt)
            .where(PaymentAttempt.order_id.in_(order_ids))
            .order_by(PaymentAttempt.created_at, PaymentAttempt.id)
        )
        for attempt in db.scalars(query):
            found[attempt.order_id].append(attempt)
    return found


def reservation_expiry(db: Session, order_id: UUID) -> datetime | None:
    """When the order's active stock holds lapse, or None when none is active."""
    return db.scalar(
        select(func.min(StockReservation.expires_at)).where(
            StockReservation.order_id == order_id, StockReservation.status == "active"
        )
    )


def _detail_fields(db: Session, order: Order) -> dict:
    db.refresh(order)
    items = list(
        db.scalars(
            select(OrderItem)
            .where(OrderItem.order_id == order.id)
            .order_by(OrderItem.created_at, OrderItem.id)
        )
    )
    history = list(
        db.scalars(
            select(OrderStatusHistory)
            .where(OrderStatusHistory.order_id == order.id)
            .order_by(OrderStatusHistory.created_at, OrderStatusHistory.id)
        )
    )
    payments = _payments(db, [order.id])[order.id]
    latest = payments[-1] if payments else None
    images = line_images(db, [item.variant_id for item in items])
    slugs = public_product_slugs(db, [item.product_id for item in items if item.product_id])
    reviewed = (
        set(
            db.scalars(
                select(ProductReview.order_item_id).where(
                    ProductReview.order_item_id.in_([item.id for item in items])
                )
            )
        )
        if items
        else set()
    )
    return {
        "id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "currency_code": order.currency_code,
        "subtotal": order.subtotal,
        "discount_total": order.discount_total,
        "delivery_fee": order.delivery_fee,
        "tax_total": order.tax_total,
        "total": order.total,
        "tax_treatment": order.tax_treatment,
        "discount_code": order.discount_code_snapshot,
        "delivery_zone": order.delivery_zone_snapshot,
        "recipient_name": order.recipient_name,
        "recipient_phone": order.recipient_phone,
        "delivery_address": order.delivery_address_snapshot,
        "lines": [
            OrderLineResponse(
                id=item.id,
                store_name=item.store_name_snapshot,
                sku=item.sku_snapshot,
                product_name=item.product_name_snapshot,
                variant_name=(item.variant_snapshot or {}).get("name"),
                quantity=item.quantity,
                unit_price=item.unit_price,
                line_subtotal=item.line_subtotal,
                discount_amount=item.discount_amount,
                line_total=item.line_total,
                image=images.get(item.variant_id) if item.variant_id else None,
                product_slug=slugs.get(item.product_id) if item.product_id else None,
                reviewed=item.id in reviewed,
            )
            for item in items
        ],
        "payment": (
            OrderPaymentResponse(
                method=latest.method,  # type: ignore[arg-type]
                status=latest.status,  # type: ignore[arg-type]
                amount=latest.amount,
                created_at=latest.created_at,
            )
            if latest is not None
            else None
        ),
        "status_history": [
            OrderHistoryEntry(
                status=h.status,  # type: ignore[arg-type]
                reason=h.reason,
                created_at=h.created_at,
            )
            for h in history
        ],
        "_payments": payments,
    }


def order_detail(db: Session, order: Order) -> OrderDetailResponse:
    fields = _detail_fields(db, order)
    fields.pop("_payments")
    return OrderDetailResponse(**fields)


def staff_order_detail(db: Session, order: Order) -> StaffOrderDetailResponse:
    fields = _detail_fields(db, order)
    payments = fields.pop("_payments")
    return StaffOrderDetailResponse(
        **fields,
        user_id=order.user_id,
        customer_email=order.customer_email_snapshot,
        customer_note=order.customer_note,
        fulfilment_assignee_user_id=order.fulfilment_assignee_user_id,
        fulfilment_assignee_name=(
            db.scalar(select(User.full_name).where(User.id == order.fulfilment_assignee_user_id))
            if order.fulfilment_assignee_user_id
            else None
        ),
        payments=[
            StaffPaymentResponse(
                method=p.method,  # type: ignore[arg-type]
                status=p.status,  # type: ignore[arg-type]
                amount=p.amount,
                created_at=p.created_at,
                provider=p.provider,
                succeeded_at=p.succeeded_at,
            )
            for p in payments
        ],
        seller_orders=staff_seller_orders(db, order.id),
    )


def _summaries(db: Session, orders: list[Order]) -> list[OrderSummaryResponse]:
    ids = [o.id for o in orders]
    units = (
        dict(
            db.execute(
                select(OrderItem.order_id, func.sum(OrderItem.quantity))
                .where(OrderItem.order_id.in_(ids))
                .group_by(OrderItem.order_id)
            ).all()
        )
        if ids
        else {}
    )
    payments = _payments(db, ids)
    out = []
    for order in orders:
        latest = payments[order.id][-1] if payments[order.id] else None
        out.append(
            OrderSummaryResponse(
                id=order.id,
                order_number=order.order_number,
                status=order.status,  # type: ignore[arg-type]
                total=order.total,
                item_count=int(units.get(order.id, 0) or 0),
                payment_method=latest.method if latest else None,  # type: ignore[arg-type]
                payment_status=latest.status if latest else None,  # type: ignore[arg-type]
                created_at=order.created_at,
            )
        )
    return out


def _latest_payment(column: Any = PaymentAttempt.status):
    """The latest payment attempt's column, per order, for filters."""
    return (
        select(column)
        .where(PaymentAttempt.order_id == Order.id)
        .order_by(PaymentAttempt.created_at.desc(), PaymentAttempt.id.desc())
        .limit(1)
        .scalar_subquery()
    )


def _search_condition(q: str) -> Any:
    """A Rwandan mobile number matches the order's phone exactly; anything else is part of an
    order number (case-insensitive)."""
    try:
        return Order.recipient_phone == validate_rwanda_phone(q)
    except ValueError:
        return Order.order_number.contains(q.strip().upper(), autoescape=True)


def _apply_payment_rules(
    db: Session, order: Order, new_status: str, actor: User, ctx: RequestContext
) -> None:
    """The approved payment and stock consequences of a status change (§7 Q13, Q14)."""
    attempts = _payments(db, [order.id])[order.id]
    latest = attempts[-1] if attempts else None
    cod = latest is not None and latest.method == CASH_ON_DELIVERY
    if new_status == "confirmed" and cod:
        result = commit_order_reservations(db, order.id, actor=actor, ctx=ctx)
        if result.outcome == TransitionOutcome.NEEDS_RECONCILIATION:
            raise InvalidReservationState("the cash-on-delivery hold has lapsed")
    elif new_status == "delivered" and cod and latest is not None and latest.status == "pending":
        latest.status = "succeeded"
        latest.succeeded_at = func.now()  # type: ignore[assignment]
        # §7 Q19: a cash-on-delivery order's invoice is issued on delivery, in this transaction.
        issue_for_order(db, order, payment_method=latest.method, actor=actor, ctx=ctx)
        record_order_event(db, order, "payment_succeeded")
    elif new_status == "cancelled":
        for attempt in attempts:
            if attempt.status in UNPAID:
                attempt.status = "cancelled"


# PR-07 names the lifecycle statuses but does not define edge rules. The ordered forward path
# below is an implementation policy, isolated here for owner review (see API inventory).
ORDER_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "received": frozenset({"confirmed", "cancelled"}),
    "confirmed": frozenset({"processing", "cancelled"}),
    "processing": frozenset({"dispatched", "cancelled"}),
    "dispatched": frozenset({"delivered"}),
    "delivered": frozenset(),
    "cancelled": frozenset(),
}

# ADR-014 phase 3: the only whole-order change staff make; the rest follows the seller orders.
STAFF_ORDER_MOVES = frozenset({"cancelled"})
FOLLOWS_SELLER_ORDERS = (
    "Sellers move their own orders; this order's status follows its stores' orders. Staff can "
    "only cancel an order."
)
ORDER_NOT_FOUND = "Order not found."
INVALID_TRANSITION = "The requested order status transition is not allowed."
INVALID_ASSIGNMENT = "Assignment target must be an active staff account."


class InvalidOrderTransition(Exception):
    def __init__(self, current_status: str, requested_status: str) -> None:
        self.current_status = current_status
        self.requested_status = requested_status


class InvalidAssignmentTarget(Exception):
    pass


def move_order(
    db: Session,
    order: Order,
    new_status: str,
    *,
    actor: User,
    ctx: RequestContext,
    reason: str | None,
    trigger: str | None = None,
) -> None:
    """Apply one parent transition with its stock, payment, notification and audit rules. The
    caller holds the order's advisory lock and row lock. Used for a staff cancellation and for
    the seller-order rollup (trigger="seller_orders"); raises InvalidOrderTransition."""
    previous = order.status
    if new_status not in ORDER_TRANSITIONS.get(previous, frozenset()):
        raise InvalidOrderTransition(previous, new_status)
    if new_status == "cancelled":
        release_order_reservations(db, order.id, reason="cancelled", actor=actor, ctx=ctx)
        # RE-026 B3: a cancellation before dispatch releases the promotion use, in the same
        # transaction as the stock release.
        release_for_order(db, order.id, reason="cancelled", actor=actor, ctx=ctx)
        cancel_seller_orders(db, order.id, actor_user_id=actor.id, reason=reason)
    elif new_status == "dispatched":
        # Each store issued its own SKUs when it dispatched (owner decision 1); this is the
        # idempotent check that every SKU of the order has been issued exactly once.
        dispatch_order_inventory(db, order.id, actor=actor, ctx=ctx)
    _apply_payment_rules(db, order, new_status, actor, ctx)

    order.status = new_status
    db.add(
        OrderStatusHistory(
            order_id=order.id, status=new_status, actor_user_id=actor.id, reason=reason
        )
    )
    if new_status in NOTIFICATION_EVENTS:
        record_order_event(db, order, new_status)  # type: ignore[arg-type]
    details: dict[str, Any] = {"from_status": previous, "to_status": new_status, "reason": reason}
    if trigger is not None:
        details["trigger"] = trigger
    AuditService.log_event(
        db,
        action="order.status_change",
        status="success",
        actor=actor,
        entity_type="order",
        entity_id=order.id,
        context=ctx,
        details=details,
    )


class OrderService:
    @staticmethod
    def get_owned(db: Session, order_id: UUID, user: User) -> Order:
        order = OrderRepository.get_owned(db, order_id, user.id)
        if order is None:
            raise NotFound(ORDER_NOT_FOUND, code="order_not_found")
        return order

    @staticmethod
    def get_owned_by_number(db: Session, order_number: str, user: User) -> Order:
        order = OrderRepository.get_owned_by_number(db, order_number, user.id)
        if order is None:
            raise NotFound(ORDER_NOT_FOUND, code="order_not_found")
        return order

    @staticmethod
    def customer_history(
        db: Session, user: User, *, page: int, size: int
    ) -> Page[OrderSummaryResponse]:
        query = select(Order).where(Order.user_id == user.id)
        total = db.scalar(select(func.count(Order.id)).where(Order.user_id == user.id)) or 0
        orders = list(
            db.scalars(
                query.order_by(Order.created_at.desc(), Order.id)
                .offset(page_offset(page, size))
                .limit(size)
            )
        )
        return Page(items=_summaries(db, orders), total=total, page=page, size=size)

    @staticmethod
    def lookup(
        db: Session,
        order_number: str,
        phone: str,
        limiter: LoginRateLimiter,
        ctx: RequestContext,
    ) -> OrderDetailResponse:
        return order_detail(
            db, OrderService.find_guest_order(db, order_number, phone, limiter, ctx)
        )

    @staticmethod
    def find_guest_order(
        db: Session,
        order_number: str,
        phone: str,
        limiter: LoginRateLimiter,
        ctx: RequestContext,
    ) -> Order:
        """Guest lookup (RE-026 B7): the order number and the order's phone (canonical). Any
        mismatch, including an unknown number, is the same 404. Also used to issue a guest's
        review link (module 20), so both share the same counters.

        ADR-008 S6 (approved 2026-10-25): failed lookups are counted per order number (keyed by
        its HMAC pseudonym) and per IP; beyond 5 per number or 20 per IP in 15 minutes the
        request answers 429 with Retry-After before the database is read. Successful lookups
        are not counted. The limit is checked before anything else, so an unreachable store
        answers 503 for every request alike (fail closed) and reveals nothing about the order.
        If the store fails only while a refusal is being counted, the request still answers its
        404 (never a 503 that would tell a miss from a hit) and the error is logged."""
        ref = identifier_ref(order_number)
        try:
            decision = limiter.check(ref, ctx.ip_address)
        except RateLimitStoreUnavailable:
            logger.error("Order lookup refused: the rate-limit store is unavailable")
            raise ServiceUnavailable(LOOKUP_UNAVAILABLE, code="order_lookup_unavailable") from None
        if not decision.allowed:
            logger.warning("Order lookup limit reached (%s)", decision.scope)
            raise TooManyRequests(
                LOOKUP_LIMITED,
                code="rate_limited",
                headers={"Retry-After": str(decision.retry_after)},
            )
        order = db.scalar(
            select(Order).where(Order.order_number == order_number, Order.recipient_phone == phone)
        )
        if order is None:
            try:
                limiter.record_failure(ref, ctx.ip_address)
            except RateLimitStoreUnavailable:
                logger.error("Failed order lookup not counted: the rate-limit store is unavailable")
            raise NotFound(ORDER_NOT_FOUND, code="order_not_found")
        return order

    @staticmethod
    def staff_list(
        db: Session,
        *,
        status: str | None,
        created_from: datetime | None,
        created_to: datetime | None,
        payment_status: str | None,
        page: int,
        size: int,
        payment_method: str | None = None,
        q: str | None = None,
        store_id: UUID | None = None,
    ) -> Page[StaffOrderSummaryResponse]:
        if created_from and created_to and created_from > created_to:
            raise field_error(("query", "from"), "`from` must not be after `to`.")
        conditions = []
        if status is not None:
            conditions.append(Order.status == status)
        if created_from is not None:
            conditions.append(Order.created_at >= created_from)
        if created_to is not None:
            conditions.append(Order.created_at <= created_to)
        if payment_status is not None:
            conditions.append(_latest_payment() == payment_status)
        if payment_method is not None:
            conditions.append(_latest_payment(PaymentAttempt.method) == payment_method)
        if q:
            conditions.append(_search_condition(q))
        if store_id is not None:
            conditions.append(
                select(SellerOrder.id)
                .where(SellerOrder.order_id == Order.id, SellerOrder.store_id == store_id)
                .exists()
            )
        total = db.scalar(select(func.count(Order.id)).where(*conditions)) or 0
        orders = list(
            db.scalars(
                select(Order)
                .where(*conditions)
                .order_by(Order.created_at.desc(), Order.id)
                .offset(page_offset(page, size))
                .limit(size)
            )
        )
        rows = [
            StaffOrderSummaryResponse(
                **summary.model_dump(),
                customer_name=order.recipient_name,
                customer_phone=order.recipient_phone,
            )
            for summary, order in zip(_summaries(db, orders), orders, strict=True)
        ]
        return Page(items=rows, total=total, page=page, size=size)

    @staticmethod
    def assignees(db: Session) -> OrderAssigneesResponse:
        """Every active staff account an order can be assigned to (the same rule as
        assign_fulfilment)."""
        rows = db.execute(
            select(User.id, User.full_name, StaffRoleAssignment.role)
            .join(StaffRoleAssignment, StaffRoleAssignment.user_id == User.id)
            .where(User.is_staff.is_(True), User.is_active.is_(True))
            .order_by(User.full_name, User.id)
        ).tuples()
        return OrderAssigneesResponse(
            items=[OrderAssignee(id=i, full_name=name, role=role) for i, name, role in rows]
        )

    @staticmethod
    def staff_get(db: Session, order_id: UUID) -> StaffOrderDetailResponse:
        order = OrderRepository.get(db, order_id)
        if order is None:
            raise NotFound(ORDER_NOT_FOUND, code="order_not_found")
        return staff_order_detail(db, order)

    @staticmethod
    def change_status(
        db: Session,
        *,
        order_id: UUID,
        actor: User,
        new_status: str,
        ctx: RequestContext,
        reason: str | None = None,
    ) -> Order:
        """Staff change of a whole order. ADR-014 phase 3 (owner decision 2, 2026-11-21): sellers
        run fulfilment and the parent's confirmed, processing, dispatched and delivered follow
        the seller orders (seller_order_service); staff may only cancel, which stays with the
        platform. Any other status answers 409 order_status_follows_seller_orders."""
        if new_status not in STAFF_ORDER_MOVES:
            if OrderRepository.get(db, order_id) is None:
                raise NotFound(ORDER_NOT_FOUND, code="order_not_found")
            AuditService.record_standalone(
                db,
                action="order.status_change",
                status="conflict",
                actor=actor,
                entity_type="order",
                entity_id=order_id,
                context=ctx,
                details={"requested_status": new_status, "reason": "follows_seller_orders"},
            )
            raise Conflict(FOLLOWS_SELLER_ORDERS, code="order_status_follows_seller_orders")
        try:
            with atomic(db):
                # The common lock order (inventory.lock_order): the order's advisory lock, then
                # its row. Release takes the same advisory lock again (re-entrant), so nothing
                # here can wait on the expiry job while holding the row.
                lock_order(db, order_id)
                order = OrderRepository.get(db, order_id, for_update=True)
                if order is None:
                    raise NotFound(ORDER_NOT_FOUND, code="order_not_found")
                move_order(db, order, new_status, actor=actor, ctx=ctx, reason=reason)
        except InvalidOrderTransition as exc:
            AuditService.record_standalone(
                db,
                action="order.status_change",
                status="conflict",
                actor=actor,
                entity_type="order",
                entity_id=order_id,
                context=ctx,
                details={
                    "from_status": exc.current_status,
                    "requested_status": exc.requested_status,
                },
            )
            raise Conflict(INVALID_TRANSITION, code="invalid_transition") from exc
        except (InventoryUnavailable, InvalidReservationState) as exc:
            AuditService.record_standalone(
                db,
                action="order.status_change",
                status="conflict",
                actor=actor,
                entity_type="order",
                entity_id=order_id,
                context=ctx,
                details={"requested_status": new_status, "reason": "inventory_state"},
            )
            raise Conflict(
                "Inventory state does not permit this order transition.", code="inventory_conflict"
            ) from exc
        return order

    @staticmethod
    def assign_fulfilment(
        db: Session,
        *,
        order_id: UUID,
        staff_user_id: UUID,
        actor: User,
        ctx: RequestContext,
    ) -> Order:
        try:
            with atomic(db):
                order = OrderRepository.get(db, order_id, for_update=True)
                if order is None:
                    raise NotFound(ORDER_NOT_FOUND, code="order_not_found")
                assignee = OrderRepository.get_active_staff_for_update(db, staff_user_id)
                if assignee is None:
                    raise InvalidAssignmentTarget
                previous = order.fulfilment_assignee_user_id
                order.fulfilment_assignee_user_id = assignee.id
                AuditService.log_event(
                    db,
                    action="order.fulfilment_assignment",
                    status="success",
                    actor=actor,
                    entity_type="order",
                    entity_id=order.id,
                    context=ctx,
                    details={
                        "previous_staff_user_id": str(previous) if previous else None,
                        "staff_user_id": str(assignee.id),
                    },
                )
        except InvalidAssignmentTarget as exc:
            AuditService.record_standalone(
                db,
                action="order.fulfilment_assignment",
                status="failure",
                actor=actor,
                entity_type="order",
                entity_id=order_id,
                context=ctx,
                details={"requested_staff_user_id": str(staff_user_id)},
            )
            raise ValidationFailed(INVALID_ASSIGNMENT, code="invalid_assignment") from exc
        return order
