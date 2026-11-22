"""Seller order statuses and the one change other order code makes to them (ADR-014 phase 3).

Kept apart from seller_order_service so inventory and order code can cancel an order's seller
orders without importing the seller service (which imports them). Only model imports here.
"""

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import SellerOrder, SellerOrderStatusHistory

# The seller's own moves, one step at a time (owner decision 2, 2026-11-21). Cancellation is
# never a seller move: a seller order is cancelled only with its whole parent order.
SELLER_ORDER_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "pending": frozenset({"confirmed"}),
    "confirmed": frozenset({"processing"}),
    "processing": frozenset({"dispatched"}),
    "dispatched": frozenset({"delivered"}),
    "delivered": frozenset(),
    "cancelled": frozenset(),
}
SELLER_ORDER_RANK: Mapping[str, int] = {
    "pending": 0,
    "confirmed": 1,
    "processing": 2,
    "dispatched": 3,
    "delivered": 4,
}


def cancel_seller_orders(
    session: Session, order_id: UUID, *, actor_user_id: UUID | None, reason: str | None
) -> int:
    """Cancel every open seller order of a parent order being cancelled, in the caller's
    transaction (the caller holds the order's locks). The parent may be cancelled only before
    its stock is committed, so no seller order has started processing; one that has is never
    cancelled here and is a broken invariant."""
    rows = list(
        session.scalars(
            select(SellerOrder)
            .where(SellerOrder.order_id == order_id, SellerOrder.status != "cancelled")
            .order_by(SellerOrder.id)
            .with_for_update()
        )
    )
    for row in rows:
        if row.status not in ("pending", "confirmed"):
            raise RuntimeError(f"seller order {row.id} is {row.status}; it cannot be cancelled")
        row.status = "cancelled"
        row.cancelled_at = func.now()  # type: ignore[assignment]
        session.add(
            SellerOrderStatusHistory(
                seller_order_id=row.id,
                status="cancelled",
                actor_user_id=actor_user_id,
                reason=reason,
            )
        )
    session.flush()
    return len(rows)
