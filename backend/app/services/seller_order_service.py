"""Seller orders: each store's part of a parent order (ADR-014 phase 3).

Owner decisions of 2026-11-21:

1. Stock leaves inventory when each store dispatches its own seller order (its SKUs only); the
   other stores' stock stays held or committed until they dispatch or the order is cancelled.
2. Sellers run their own fulfilment. A seller moves only their own seller order, one step at a
   time: pending -> confirmed -> processing -> dispatched -> delivered. The parent order's status
   is derived from its seller orders, in the same transaction, under the order's locks; staff
   cannot confirm, process, dispatch or deliver (OrderService.change_status allows them only
   whole-order cancellation, which stays with the platform).
3. Cash on delivery is allowed for several stores: one payment on the parent order, marked
   succeeded and invoiced when the last seller order is delivered (the existing rule).
4. Commission is charged on each store's merchandise after its share of the order discount,
   at the rate snapshotted at checkout, rounded half up to whole RWF.

The rollup keeps every existing parent rule: the parent becomes confirmed when every seller
order is confirmed (for cash on delivery this commits the whole order's stock, as an
administrator's confirmation did; a hold that lapsed first cancels the whole order as before),
processing when the first store starts processing, dispatched when every store has dispatched,
delivered when every store has delivered. A failed parent step rolls the seller's change back.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.dependencies import SellerContext
from app.core.errors import Conflict, NotFound
from app.core.request_context import RequestContext
from app.db.transaction import atomic
from app.models import (
    Order,
    OrderItem,
    PaymentAttempt,
    SellerOrder,
    SellerOrderStatusHistory,
    Store,
)
from app.models.identity import User
from app.schemas.order import StaffSellerOrderResponse
from app.schemas.pagination import Page, page_offset
from app.schemas.seller_orders import (
    EarningsBucket,
    SellerDeliveryAddress,
    SellerEarningsResponse,
    SellerOrderDetail,
    SellerOrderHistoryEntry,
    SellerOrderLine,
    SellerOrderSummary,
)
from app.services.audit_service import AuditService
from app.services.inventory import (
    InvalidReservationState,
    InventoryUnavailable,
    dispatch_order_inventory,
    lock_order,
)
from app.services.seller_order_status import SELLER_ORDER_RANK, SELLER_ORDER_TRANSITIONS
from app.services.settings_service import default_commission_bps

CASH_ON_DELIVERY = "cash_on_delivery"
BPS = 10_000

SELLER_ORDER_NOT_FOUND = "Order not found."
INVALID_SELLER_TRANSITION = "Your order cannot move to that status from its current one."
AWAITING_PAYMENT = "This order is not paid yet; it can be confirmed once its payment succeeds."
AWAITING_OTHER_STORES = (
    "The order is waiting for every store to confirm it; you can start processing once it is "
    "confirmed."
)
INVENTORY_CONFLICT = "Inventory state does not permit this order transition."


# ---- money ---------------------------------------------------------------------------------
def commission_amount(base: int, rate_bps: int) -> int:
    """`base` x `rate_bps` / 10000, rounded half up to whole RWF (owner decision 4)."""
    if base < 0 or not 0 <= rate_bps <= BPS:
        raise ValueError("commission needs a non-negative base and a rate of 0 to 10000 bps")
    return (base * rate_bps + BPS // 2) // BPS


def build_seller_orders(db: Session, order: Order) -> list[SellerOrder]:
    """At checkout: one seller order per store of the order's lines, with the money snapshots.

    The discount was already split across lines by promotion_service.allocate (whole RWF, the
    shares sum exactly to the order discount), so a store's discount is the sum of its lines'
    shares and the stores' discounts sum exactly to the order's. Delivery is the platform's and
    is never part of a seller order. The rate is the store's override, else the platform
    default, read now and never re-read."""
    lines: dict[UUID, list[OrderItem]] = defaultdict(list)
    for item in order.items:
        lines[item.store_id].append(item)
    stores = {s.id: s for s in db.scalars(select(Store).where(Store.id.in_(list(lines))))}
    default_rate: int | None = None
    created: list[SellerOrder] = []
    for store_id in sorted(lines, key=str):
        store = stores[store_id]
        if store.commission_rate_bps is not None:
            rate = store.commission_rate_bps
        else:
            if default_rate is None:
                default_rate = default_commission_bps(db)
            rate = default_rate
        subtotal = sum(item.line_subtotal for item in lines[store_id])
        discount = sum(item.discount_amount or 0 for item in lines[store_id])
        merchandise = subtotal - discount
        commission = commission_amount(merchandise, rate)
        seller_order = SellerOrder(
            store_id=store_id,
            store_name_snapshot=store.name,
            status="pending",
            subtotal=subtotal,
            discount_total=discount,
            merchandise_total=merchandise,
            commission_rate_bps=rate,
            commission_amount=commission,
            seller_net_amount=merchandise - commission,
        )
        seller_order.history.append(SellerOrderStatusHistory(status="pending"))
        order.seller_orders.append(seller_order)
        created.append(seller_order)
    if sum(s.discount_total for s in created) != (order.discount_total or 0):
        raise RuntimeError("the stores' discounts do not add up to the order discount")
    return created


# ---- reads ---------------------------------------------------------------------------------
def _latest_payment(column: Any) -> Any:
    return (
        select(column)
        .where(PaymentAttempt.order_id == SellerOrder.order_id)
        .order_by(PaymentAttempt.created_at.desc(), PaymentAttempt.id.desc())
        .limit(1)
        .scalar_subquery()
    )


def _visible() -> Any:
    """A seller sees a seller order once it can act on it or has acted on it: cash on delivery
    from placement (it is the store's to confirm), mobile money once paid. An unpaid mobile-money
    order, and one that lapsed unpaid, is never shown."""
    return or_(
        SellerOrder.status.not_in(("pending", "cancelled")),
        _latest_payment(PaymentAttempt.method) == CASH_ON_DELIVERY,
        _latest_payment(PaymentAttempt.status) == "succeeded",
    )


def _own(db: Session, store_id: UUID, seller_order_id: UUID) -> SellerOrder:
    row = db.scalar(
        select(SellerOrder).where(
            SellerOrder.id == seller_order_id, SellerOrder.store_id == store_id, _visible()
        )
    )
    if row is None:
        raise NotFound(SELLER_ORDER_NOT_FOUND, code="seller_order_not_found")
    return row


def _latest_attempt(db: Session, order_id: UUID) -> PaymentAttempt | None:
    return db.scalar(
        select(PaymentAttempt)
        .where(PaymentAttempt.order_id == order_id)
        .order_by(PaymentAttempt.created_at.desc(), PaymentAttempt.id.desc())
        .limit(1)
    )


def _units(db: Session, rows: list[SellerOrder]) -> dict[tuple[UUID, UUID], int]:
    if not rows:
        return {}
    result = db.execute(
        select(OrderItem.order_id, OrderItem.store_id, func.sum(OrderItem.quantity))
        .where(OrderItem.order_id.in_({r.order_id for r in rows}))
        .group_by(OrderItem.order_id, OrderItem.store_id)
    ).all()
    return {(o, s): int(n) for o, s, n in result}


def _money(row: SellerOrder) -> dict[str, int]:
    return {
        "subtotal": row.subtotal,
        "discount_total": row.discount_total,
        "merchandise_total": row.merchandise_total,
        "commission_rate_bps": row.commission_rate_bps,
        "commission_amount": row.commission_amount,
        "seller_net_amount": row.seller_net_amount,
    }


def _summary(row: SellerOrder, attempt: PaymentAttempt | None, units: int) -> dict[str, Any]:
    return {
        **_money(row),
        "id": row.id,
        "order_number": row.order.order_number,
        "status": row.status,
        "order_status": row.order.status,
        "payment_method": attempt.method if attempt else None,
        "payment_status": attempt.status if attempt else None,
        "units": units,
        "recipient_name": row.order.recipient_name,
        "created_at": row.created_at,
    }


def _audit_read(
    db: Session, seller: SellerContext, ctx: RequestContext, entity_id: UUID | None, **details: Any
) -> None:
    AuditService.record_standalone(
        db,
        action="seller_order.read",
        status="success",
        actor=seller.user,
        entity_type="seller_order",
        entity_id=entity_id,
        context=ctx,
        details={"store_id": str(seller.store.id), **details},
    )


ADDRESS_FIELDS = tuple(SellerDeliveryAddress.model_fields)


def seller_detail(db: Session, row: SellerOrder) -> SellerOrderDetail:
    db.refresh(row)
    items = list(
        db.scalars(
            select(OrderItem)
            .where(OrderItem.order_id == row.order_id, OrderItem.store_id == row.store_id)
            .order_by(OrderItem.created_at, OrderItem.id)
        )
    )
    history = list(
        db.scalars(
            select(SellerOrderStatusHistory)
            .where(SellerOrderStatusHistory.seller_order_id == row.id)
            .order_by(SellerOrderStatusHistory.created_at, SellerOrderStatusHistory.id)
        )
    )
    attempt = _latest_attempt(db, row.order_id)
    address = row.order.delivery_address_snapshot or {}
    return SellerOrderDetail(
        **_summary(row, attempt, sum(i.quantity for i in items)),
        updated_at=row.updated_at,
        recipient_phone=row.order.recipient_phone,
        delivery_zone=row.order.delivery_zone_snapshot,
        delivery_address=SellerDeliveryAddress(**{k: address.get(k) for k in ADDRESS_FIELDS}),
        lines=[
            SellerOrderLine(
                sku=i.sku_snapshot,
                product_name=i.product_name_snapshot,
                variant_name=(i.variant_snapshot or {}).get("name"),
                quantity=i.quantity,
                unit_price=i.unit_price,
                line_subtotal=i.line_subtotal,
                discount_amount=i.discount_amount,
                line_total=i.line_total,
            )
            for i in items
        ],
        status_history=[
            SellerOrderHistoryEntry(status=h.status, reason=h.reason, created_at=h.created_at)  # type: ignore[arg-type]
            for h in history
        ],
    )


def staff_seller_orders(db: Session, order_id: UUID) -> list[StaffSellerOrderResponse]:
    rows = db.scalars(
        select(SellerOrder)
        .where(SellerOrder.order_id == order_id)
        .order_by(SellerOrder.store_name_snapshot, SellerOrder.id)
    )
    return [
        StaffSellerOrderResponse(
            **_money(r),
            id=r.id,
            store_id=r.store_id,
            store_name=r.store_name_snapshot,
            status=r.status,  # type: ignore[arg-type]
            confirmed_at=r.confirmed_at,
            dispatched_at=r.dispatched_at,
            delivered_at=r.delivered_at,
            cancelled_at=r.cancelled_at,
        )
        for r in rows
    ]


def earnings(db: Session, store_id: UUID) -> SellerEarningsResponse:
    """Pending: confirmed, processing, dispatched, and delivered while the order payment has not
    yet succeeded (cash on delivery until the last store delivers). Earned: delivered and the
    order's payment succeeded. Pending (unconfirmed) and cancelled seller orders are neither."""
    paid = (
        select(PaymentAttempt.id)
        .where(
            PaymentAttempt.order_id == SellerOrder.order_id, PaymentAttempt.status == "succeeded"
        )
        .exists()
    )
    earned = (SellerOrder.status == "delivered") & paid
    rows = db.execute(
        select(
            earned.label("earned"),
            func.count(SellerOrder.id),
            func.coalesce(func.sum(SellerOrder.merchandise_total), 0),
            func.coalesce(func.sum(SellerOrder.commission_amount), 0),
            func.coalesce(func.sum(SellerOrder.seller_net_amount), 0),
        )
        .where(
            SellerOrder.store_id == store_id,
            SellerOrder.status.not_in(("pending", "cancelled")),
        )
        .group_by(earned)
    ).all()
    buckets = {
        bool(e): EarningsBucket(
            orders=int(n),
            merchandise_total=int(m),
            commission_amount=int(c),
            seller_net_amount=int(s),
        )
        for e, n, m, c, s in rows
    }
    empty = EarningsBucket(orders=0, merchandise_total=0, commission_amount=0, seller_net_amount=0)
    return SellerEarningsResponse(
        store_id=store_id, pending=buckets.get(False, empty), earned=buckets.get(True, empty)
    )


# ---- moves ---------------------------------------------------------------------------------
class _Refused(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any]) -> None:
        self.code = code
        self.message = message
        self.details = details


def _parent_target(parent: str, groups: list[str]) -> str | None:
    """The parent's next status from its seller orders' statuses, or None (decision 2)."""
    live = [SELLER_ORDER_RANK[g] for g in groups if g != "cancelled"]
    if not live:
        return None
    if parent == "received" and min(live) >= SELLER_ORDER_RANK["confirmed"]:
        return "confirmed"
    if parent == "confirmed" and max(live) >= SELLER_ORDER_RANK["processing"]:
        return "processing"
    if parent == "processing" and min(live) >= SELLER_ORDER_RANK["dispatched"]:
        return "dispatched"
    if parent == "dispatched" and min(live) >= SELLER_ORDER_RANK["delivered"]:
        return "delivered"
    return None


class SellerOrderService:
    @staticmethod
    def list(
        db: Session,
        seller: SellerContext,
        ctx: RequestContext,
        *,
        status: str | None,
        q: str | None,
        page: int,
        size: int,
    ) -> Page[SellerOrderSummary]:
        conditions = [SellerOrder.store_id == seller.store.id, _visible()]
        if status is not None:
            conditions.append(SellerOrder.status == status)
        query = select(SellerOrder).join(Order, Order.id == SellerOrder.order_id)
        if q:
            conditions.append(Order.order_number.contains(q.strip().upper(), autoescape=True))
        total = (
            db.scalar(
                select(func.count(SellerOrder.id))
                .join(Order, Order.id == SellerOrder.order_id)
                .where(*conditions)
            )
            or 0
        )
        rows = list(
            db.scalars(
                query.where(*conditions)
                .order_by(SellerOrder.created_at.desc(), SellerOrder.id)
                .offset(page_offset(page, size))
                .limit(size)
            )
        )
        units = _units(db, rows)
        items = [
            SellerOrderSummary(
                **_summary(
                    r, _latest_attempt(db, r.order_id), units.get((r.order_id, r.store_id), 0)
                )
            )
            for r in rows
        ]
        _audit_read(db, seller, ctx, None, listed=len(items), page=page)
        return Page(items=items, total=total, page=page, size=size)

    @staticmethod
    def get(
        db: Session, seller: SellerContext, seller_order_id: UUID, ctx: RequestContext
    ) -> SellerOrderDetail:
        row = _own(db, seller.store.id, seller_order_id)
        detail = seller_detail(db, row)
        _audit_read(db, seller, ctx, row.id, order_id=str(row.order_id))
        return detail

    @staticmethod
    def change_status(
        db: Session,
        seller: SellerContext,
        seller_order_id: UUID,
        new_status: str,
        ctx: RequestContext,
        reason: str | None = None,
    ) -> SellerOrderDetail:
        # The store comes only from require_approved_seller; another store's seller order is
        # the same 404 as a missing one, decided before any lock is taken.
        order_id = _own(db, seller.store.id, seller_order_id).order_id
        try:
            with atomic(db):
                # The common lock order: the order's advisory lock, its row, then its rows.
                lock_order(db, order_id)
                order = db.scalar(
                    select(Order)
                    .where(Order.id == order_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                row = db.scalar(
                    select(SellerOrder)
                    .where(
                        SellerOrder.id == seller_order_id, SellerOrder.store_id == seller.store.id
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                assert order is not None and row is not None
                previous = row.status
                if new_status not in SELLER_ORDER_TRANSITIONS.get(previous, frozenset()):
                    raise _Refused(
                        "invalid_transition",
                        INVALID_SELLER_TRANSITION,
                        {"from_status": previous, "requested_status": new_status},
                    )
                SellerOrderService._check(db, order, row, new_status)
                if new_status == "dispatched":
                    variants = set(
                        db.scalars(
                            select(OrderItem.variant_id).where(
                                OrderItem.order_id == order.id,
                                OrderItem.store_id == row.store_id,
                                OrderItem.variant_id.is_not(None),
                            )
                        )
                    )
                    dispatch_order_inventory(
                        db,
                        order.id,
                        actor=seller.user,
                        ctx=ctx,
                        variant_ids=cast(set[UUID], variants),
                    )
                row.status = new_status
                stamp = f"{new_status}_at"
                if hasattr(row, stamp):
                    setattr(row, stamp, func.now())
                db.add(
                    SellerOrderStatusHistory(
                        seller_order_id=row.id,
                        status=new_status,
                        actor_user_id=seller.user.id,
                        reason=reason,
                    )
                )
                db.flush()
                AuditService.log_event(
                    db,
                    action="seller_order.status_change",
                    status="success",
                    actor=seller.user,
                    entity_type="seller_order",
                    entity_id=row.id,
                    context=ctx,
                    details={
                        "store_id": str(row.store_id),
                        "order_id": str(order.id),
                        "from_status": previous,
                        "to_status": new_status,
                        "reason": reason,
                    },
                )
                SellerOrderService._roll_up(db, order, seller.user, ctx)
        except _Refused as exc:
            SellerOrderService._refused(db, seller, seller_order_id, ctx, exc.details)
            raise Conflict(exc.message, code=exc.code) from None
        except (InventoryUnavailable, InvalidReservationState):
            SellerOrderService._refused(
                db,
                seller,
                seller_order_id,
                ctx,
                {"requested_status": new_status, "reason": "inventory_state"},
            )
            raise Conflict(INVENTORY_CONFLICT, code="inventory_conflict") from None
        return seller_detail(db, row)

    @staticmethod
    def _check(db: Session, order: Order, row: SellerOrder, new_status: str) -> None:
        if order.status == "cancelled":
            raise _Refused(
                "invalid_transition",
                INVALID_SELLER_TRANSITION,
                {"from_status": row.status, "requested_status": new_status, "order": "cancelled"},
            )
        if new_status == "confirmed":
            attempt = _latest_attempt(db, order.id)
            cod_open = (
                attempt is not None
                and attempt.method == CASH_ON_DELIVERY
                and attempt.status == "pending"
            )
            paid = attempt is not None and attempt.status == "succeeded"
            if order.status != "received" or not (cod_open or paid):
                raise _Refused(
                    "seller_order_awaiting_payment",
                    AWAITING_PAYMENT,
                    {"requested_status": new_status, "order_status": order.status},
                )
        elif new_status == "processing" and order.status not in ("confirmed", "processing"):
            raise _Refused(
                "seller_order_awaiting_other_stores",
                AWAITING_OTHER_STORES,
                {"requested_status": new_status, "order_status": order.status},
            )

    @staticmethod
    def _roll_up(db: Session, order: Order, actor: User, ctx: RequestContext) -> None:
        # Imported here: order_service imports this module's read helpers for the staff detail.
        from app.services.order_service import move_order

        while True:
            groups = list(
                db.scalars(select(SellerOrder.status).where(SellerOrder.order_id == order.id))
            )
            target = _parent_target(order.status, groups)
            if target is None:
                return
            move_order(
                db, order, target, actor=actor, ctx=ctx, reason=None, trigger="seller_orders"
            )

    @staticmethod
    def _refused(
        db: Session,
        seller: SellerContext,
        seller_order_id: UUID,
        ctx: RequestContext,
        details: dict[str, Any],
    ) -> None:
        AuditService.record_standalone(
            db,
            action="seller_order.status_change",
            status="conflict",
            actor=seller.user,
            entity_type="seller_order",
            entity_id=seller_order_id,
            context=ctx,
            details={"store_id": str(seller.store.id), **details},
        )
