"""The approved seller's own orders and earnings (ADR-014 phase 3).

Every route requires require_approved_seller; the store is the caller's own, read from the
database on every request, and no route takes a store id. Another store's seller order answers
404, exactly like one that does not exist. A seller moves only their own seller order, one step
at a time; the whole order's status follows its stores' orders.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.notifier import Notifier
from app.api.v1.pagination import PageNumber, PageSize
from app.api.v1.responses import ERR, UNAUTHORIZED_401, VALIDATION_422, ResponseMap
from app.core.dependencies import SellerContext, require_approved_seller
from app.core.request_context import RequestContext, get_request_context
from app.db.session import get_db
from app.schemas.order import SellerOrderStatus
from app.schemas.pagination import DEFAULT_PAGE_SIZE, Page
from app.schemas.seller_orders import (
    SellerEarningsResponse,
    SellerOrderDetail,
    SellerOrderStatusRequest,
    SellerOrderSummary,
)
from app.services.seller_order_service import SellerOrderService, earnings

router = APIRouter(prefix="/seller", tags=["Seller Orders"])

Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[RequestContext, Depends(get_request_context)]
Seller = Annotated[SellerContext, Depends(require_approved_seller)]

GUARDED: ResponseMap = {
    **UNAUTHORIZED_401,
    403: {**ERR, "description": "account_inactive, or seller_not_approved (no approved store)"},
}
OWN_ORDER_404: ResponseMap = {
    404: {**ERR, "description": "seller_order_not_found: no such order for your store"}
}
MOVE_409: ResponseMap = {
    409: {
        **ERR,
        "description": (
            "invalid_transition (not the next step, or the order was cancelled); "
            "seller_order_awaiting_payment (mobile money not paid yet); "
            "seller_order_awaiting_other_stores (processing before every store confirmed); "
            "inventory_conflict (the stock cannot be issued, or a cash-on-delivery hold lapsed)"
        ),
    }
}
NOTE = "Approved sellers only; your own store's part of each order."


@router.get(
    "/orders",
    response_model=Page[SellerOrderSummary],
    summary="My store's orders",
    description=(
        f"{NOTE} Newest first. Cash-on-delivery orders appear when placed (yours to confirm); "
        "mobile-money orders once paid. `status` filters your order's status; `q` is part of "
        "an order number. Each read is audited (seller_order.read)."
    ),
    responses={**GUARDED, **VALIDATION_422},
)
def list_my_orders(
    seller: Seller,
    db: Db,
    ctx: Ctx,
    page: PageNumber = 1,
    size: PageSize = DEFAULT_PAGE_SIZE,
    status: Annotated[SellerOrderStatus | None, Query()] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
) -> Page[SellerOrderSummary]:
    return SellerOrderService.list(db, seller, ctx, status=status, q=q, page=page, size=size)


@router.get(
    "/orders/{seller_order_id}",
    response_model=SellerOrderDetail,
    summary="One of my store's orders",
    description=(
        f"{NOTE} Your lines and amounts, the recipient's name and phone, the delivery address, "
        "the payment method and status, and your order's history. Never the customer's email "
        "or account, other stores' lines, the order total, delivery fee or discount code."
    ),
    responses={**GUARDED, **OWN_ORDER_404, **VALIDATION_422},
)
def get_my_order(seller_order_id: uuid.UUID, seller: Seller, db: Db, ctx: Ctx) -> SellerOrderDetail:
    return SellerOrderService.get(db, seller, seller_order_id, ctx)


@router.patch(
    "/orders/{seller_order_id}/status",
    response_model=SellerOrderDetail,
    summary="Move my order to its next status",
    description=(
        f"{NOTE} One step at a time: confirmed, processing, dispatched, delivered. Confirming "
        "needs a pending cash-on-delivery payment or a succeeded one; when every store has "
        "confirmed, the order is confirmed (for cash on delivery this commits its stock). "
        "Processing starts once the order is confirmed. Dispatching issues your SKUs' stock. "
        "The order is dispatched when every store has dispatched and delivered when every "
        "store has delivered (cash on delivery: the payment is then recorded and the invoice "
        "issued). Sellers cannot cancel; the body refuses any other field (422)."
    ),
    responses={**GUARDED, **OWN_ORDER_404, **MOVE_409, **VALIDATION_422},
)
def change_my_order_status(
    seller_order_id: uuid.UUID,
    req: SellerOrderStatusRequest,
    seller: Seller,
    db: Db,
    ctx: Ctx,
    background: BackgroundTasks,
    notifier: Notifier,
) -> SellerOrderDetail:
    detail = SellerOrderService.change_status(
        db, seller, seller_order_id, req.status, ctx, reason=req.reason
    )
    notifier.schedule(background, db)
    return detail


@router.get(
    "/earnings",
    response_model=SellerEarningsResponse,
    summary="My store's earnings",
    description=(
        f"{NOTE} Totals of your confirmed orders: pending (not yet delivered and paid) and "
        "earned (delivered, order paid), each with merchandise, commission and net amounts. "
        "Payouts are not built: earned is owed by the platform, not paid."
    ),
    responses={**GUARDED},
)
def get_my_earnings(seller: Seller, db: Db) -> SellerEarningsResponse:
    return earnings(db, seller.store.id)
