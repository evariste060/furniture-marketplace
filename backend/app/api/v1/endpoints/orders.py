import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Query, Response, status
from sqlalchemy.orm import Session

from app.api.v1.notifier import Notifier
from app.api.v1.pagination import PageNumber, PageSize
from app.api.v1.responses import (
    ERR,
    FORBIDDEN_403,
    UNAUTHORIZED_401,
    VALIDATION_422,
    ResponseMap,
)
from app.core.dependencies import get_current_user, require_permission
from app.core.rate_limit import LoginRateLimiter, get_order_lookup_rate_limiter
from app.core.request_context import RequestContext, get_request_context
from app.core.roles import Permission
from app.db.session import get_db
from app.models.identity import User
from app.schemas.invoices import InvoiceIssueResponse
from app.schemas.order import (
    OrderAssigneesResponse,
    OrderAssignmentRequest,
    OrderDetailResponse,
    OrderFulfilmentResponse,
    OrderLookupRequest,
    OrderStatus,
    OrderStatusUpdateRequest,
    OrderSummaryResponse,
    PaymentMethod,
    PaymentStatus,
    StaffOrderDetailResponse,
    StaffOrderSummaryResponse,
)
from app.schemas.pagination import DEFAULT_PAGE_SIZE, Page
from app.services import invoice_service
from app.services.document_pdf import render_delivery_note, render_invoice
from app.services.order_service import OrderService, order_detail

customer_router = APIRouter(prefix="/customers/me/orders", tags=["Customer Orders"])
staff_router = APIRouter(prefix="/staff/orders", tags=["Staff Order Fulfilment"])
lookup_router = APIRouter(prefix="/orders", tags=["Customer Orders"])

Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[RequestContext, Depends(get_request_context)]
OrderFulfiller = Annotated[User, Depends(require_permission(Permission.ORDER_FULFIL))]
OrderReader = Annotated[User, Depends(require_permission(Permission.ORDER_READ))]
InvoiceRecoverer = Annotated[User, Depends(require_permission(Permission.INVOICES_RECOVER))]

AUTH_ERRORS: ResponseMap = {401: UNAUTHORIZED_401[401], 403: FORBIDDEN_403[403]}
ORDER_404: ResponseMap = {404: {**ERR, "description": "Order not found or not owned by the caller"}}
ORDER_409: ResponseMap = {
    409: {**ERR, "description": "Order status conflict or incompatible inventory state"}
}


@customer_router.get(
    "",
    response_model=Page[OrderSummaryResponse],
    summary="Order history",
    description="The signed-in customer's orders, newest first (TC-07).",
    responses={**AUTH_ERRORS, **VALIDATION_422},
)
def list_customer_orders(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Db,
    page: PageNumber = 1,
    size: PageSize = DEFAULT_PAGE_SIZE,
) -> Page[OrderSummaryResponse]:
    return OrderService.customer_history(db, current_user, page=page, size=size)


@customer_router.get(
    "/number/{order_number}",
    response_model=OrderDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Read an owned order by its number",
    description=(
        "The same as reading by ID, for the account's order page (/account/orders/{number}). "
        "Unknown numbers and orders owned by someone else return 404."
    ),
    responses={**AUTH_ERRORS, **ORDER_404, **VALIDATION_422},
)
def get_customer_order_by_number(
    order_number: Annotated[str, Path(min_length=1, max_length=40)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Db,
) -> OrderDetailResponse:
    return order_detail(db, OrderService.get_owned_by_number(db, order_number, current_user))


@customer_router.get(
    "/{order_id}",
    response_model=OrderDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Read an owned order",
    description=(
        "The order's status, lines, totals (VAT-inclusive, with the extracted VAT), delivery "
        "address, payment and status history. Orders owned by another customer return 404."
    ),
    responses={**AUTH_ERRORS, **ORDER_404, **VALIDATION_422},
)
def get_customer_order(
    order_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Db,
) -> OrderDetailResponse:
    return order_detail(db, OrderService.get_owned(db, order_id, current_user))


@lookup_router.post(
    "/lookup",
    response_model=OrderDetailResponse,
    summary="Look up an order as a guest",
    description=(
        "The order number and the order's phone number (any accepted format; RE-026 B7). An "
        "unknown number and a wrong phone answer the same 404. No authentication. Failed "
        "lookups are limited to 5 per order number and 20 per IP per 15 minutes (429 with "
        "Retry-After; ADR-008 S6); successful lookups are not counted. While the rate-limit "
        "store is unreachable every lookup answers 503."
    ),
    responses={
        404: {**ERR, "description": "order_not_found"},
        **VALIDATION_422,
        429: {
            **ERR,
            "description": "rate_limited: too many failed lookups for this order number or "
            "from this IP",
            "headers": {
                "Retry-After": {"description": "Seconds to wait", "schema": {"type": "integer"}}
            },
        },
        503: {
            **ERR,
            "description": "order_lookup_unavailable: the rate-limit store is unreachable",
        },
    },
)
def lookup_order(
    req: OrderLookupRequest,
    db: Db,
    ctx: Ctx,
    limiter: Annotated[LoginRateLimiter, Depends(get_order_lookup_rate_limiter)],
) -> OrderDetailResponse:
    return OrderService.lookup(db, req.order_number, req.phone, limiter, ctx)


@staff_router.get(
    "",
    response_model=Page[StaffOrderSummaryResponse],
    summary="List orders",
    description=(
        "Requires 'orders:read' (every staff role). Newest first, with the customer's name and "
        "phone. `from` and `to` bound the creation time (inclusive); `payment_status` and "
        "`payment_method` are the latest payment attempt's. `q` is a Rwandan mobile number "
        "(any accepted format; matches the order's phone) or part of an order number."
    ),
    responses={**AUTH_ERRORS, **VALIDATION_422},
)
def list_staff_orders(
    _: OrderReader,
    db: Db,
    page: PageNumber = 1,
    size: PageSize = DEFAULT_PAGE_SIZE,
    status_filter: Annotated[OrderStatus | None, Query(alias="status")] = None,
    created_from: Annotated[datetime | None, Query(alias="from")] = None,
    created_to: Annotated[datetime | None, Query(alias="to")] = None,
    payment_status: PaymentStatus | None = None,
    payment_method: PaymentMethod | None = None,
    q: Annotated[str | None, Query(min_length=1, max_length=40)] = None,
) -> Page[StaffOrderSummaryResponse]:
    return OrderService.staff_list(
        db,
        status=status_filter,
        created_from=created_from,
        created_to=created_to,
        payment_status=payment_status,
        payment_method=payment_method,
        q=q,
        page=page,
        size=size,
    )


@staff_router.get(
    "/assignees",
    response_model=OrderAssigneesResponse,
    summary="Staff an order can be assigned to",
    description=(
        "Requires 'orders:fulfil' (administrator, operations). Every active staff account "
        "(name and role only), by name: the choices for PATCH /staff/orders/{id}/assignment."
    ),
    responses={**AUTH_ERRORS},
)
def list_assignees(_: OrderFulfiller, db: Db) -> OrderAssigneesResponse:
    return OrderService.assignees(db)


@staff_router.get(
    "/{order_id}",
    response_model=StaffOrderDetailResponse,
    summary="Read an order (staff)",
    description=(
        "Requires 'orders:read'. The order with lines, totals, address, every payment attempt "
        "(method, status, amount; no provider references) and the status history."
    ),
    responses={**AUTH_ERRORS, **ORDER_404, **VALIDATION_422},
)
def get_staff_order(order_id: uuid.UUID, _: OrderReader, db: Db) -> StaffOrderDetailResponse:
    return OrderService.staff_get(db, order_id)


@staff_router.patch(
    "/{order_id}/status",
    response_model=OrderFulfilmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Advance an order status",
    description=(
        "Requires 'orders:fulfil' (administrator, operations). A valid transition, status "
        "history row and audit event commit atomically; the optional `reason` is kept in both. "
        "Dispatch consumes committed inventory; cancellation (allowed only before dispatch) "
        "releases active holds and the promotion use and cancels an unpaid payment. Confirming "
        "a cash-on-delivery order commits its stock (§7 Q13); delivering it marks the payment "
        "succeeded (Q14). Committed stock is never released by cancellation (ADR-002), so "
        "cancelling a paid or confirmed cash-on-delivery order returns 409. A move to confirmed, "
        "dispatched, delivered or cancelled records the customer's SMS or email notification "
        "with the change and sends it after the response (module 17); a notification failure "
        "never fails the change."
    ),
    responses={**AUTH_ERRORS, **ORDER_404, **ORDER_409, **VALIDATION_422},
)
def change_order_status(
    order_id: uuid.UUID,
    req: OrderStatusUpdateRequest,
    current_user: OrderFulfiller,
    db: Db,
    ctx: Ctx,
    background: BackgroundTasks,
    notifier: Notifier,
) -> OrderFulfilmentResponse:
    order = OrderService.change_status(
        db, order_id=order_id, actor=current_user, new_status=req.status, ctx=ctx, reason=req.reason
    )
    notifier.schedule(background, db)
    return OrderFulfilmentResponse.model_validate(order)


@staff_router.patch(
    "/{order_id}/assignment",
    response_model=OrderFulfilmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Assign fulfilment responsibility for an order",
    description=(
        "Requires 'orders:fulfil' (administrator, operations). The target must be an active "
        "staff account with one of the repository's assigned staff roles. The assignment and "
        "audit event commit atomically."
    ),
    responses={
        **AUTH_ERRORS,
        **ORDER_404,
        422: {**ERR, "description": "Invalid target staff account or malformed request"},
    },
)
def assign_order_fulfilment(
    order_id: uuid.UUID,
    req: OrderAssignmentRequest,
    current_user: OrderFulfiller,
    db: Db,
    ctx: Ctx,
) -> OrderFulfilmentResponse:
    order = OrderService.assign_fulfilment(
        db,
        order_id=order_id,
        staff_user_id=req.staff_user_id,
        actor=current_user,
        ctx=ctx,
    )
    return OrderFulfilmentResponse.model_validate(order)


# ---- documents (module 16) ---------------------------------------------------------------------
PDF_200: ResponseMap = {
    200: {
        "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
        "description": "The PDF document",
    }
}
INVOICE_409: ResponseMap = {
    409: {
        **ERR,
        "description": "invoice_not_available: no invoice has been issued for this order. "
        "Invoices are issued when the payment succeeds, or when a cash-on-delivery order is "
        "delivered (§7 Q19), and only once the seller's legal name, TIN and address are set.",
    }
}
INVOICE_DESCRIPTION = (
    "The invoice as issued (INV-YYYY-NNNNNN, §7 Q19), rendered from its stored snapshot: later "
    "changes to the order, catalogue, address or seller settings do not alter it, and "
    "downloading never issues an invoice. Totals are VAT-inclusive with 18% VAT shown as the "
    "extracted component (ADR-007). No EBM claim is made (PR-14)."
)


def _pdf(content: bytes, filename: str) -> Response:
    """filename is built from an invoice or order number only (letters, digits and hyphens)."""
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@customer_router.get(
    "/{order_id}/invoice",
    response_class=Response,
    summary="Download an owned order's invoice",
    description=f"{INVOICE_DESCRIPTION} Orders owned by another customer return 404.",
    responses={**PDF_200, **AUTH_ERRORS, **ORDER_404, **INVOICE_409, **VALIDATION_422},
)
def download_customer_invoice(
    order_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Db,
) -> Response:
    invoice = invoice_service.customer_invoice(db, order_id, current_user)
    return _pdf(render_invoice(invoice.snapshot), f"{invoice.invoice_number}.pdf")


@staff_router.get(
    "/{order_id}/invoice",
    response_class=Response,
    summary="Download an order's invoice (staff)",
    description=f"Requires 'orders:read'. {INVOICE_DESCRIPTION}",
    responses={**PDF_200, **AUTH_ERRORS, **ORDER_404, **INVOICE_409, **VALIDATION_422},
)
def download_staff_invoice(order_id: uuid.UUID, _: OrderReader, db: Db) -> Response:
    invoice = invoice_service.staff_invoice(db, order_id)
    return _pdf(render_invoice(invoice.snapshot), f"{invoice.invoice_number}.pdf")


@staff_router.post(
    "/{order_id}/invoice",
    response_model=InvoiceIssueResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a paid order's missing invoice (recovery)",
    description=(
        "Requires 'invoices:recover' (administrator). For a paid order whose invoice was refused "
        "when the payment succeeded (for example while the seller details were unset): issues it "
        "now, with the same checks, numbering and locks as issuance at payment, and the current "
        "date as its issue date. The order and its payments are not changed. Idempotent: an "
        "order that already has an invoice returns it with 200 and uses no number. Audited as "
        "'invoice.issue' with recovery=true."
    ),
    responses={
        200: {"model": InvoiceIssueResponse, "description": "The invoice already existed"},
        **AUTH_ERRORS,
        **ORDER_404,
        409: {
            **ERR,
            "description": "invoice_not_issuable (no confirmed payment, or cancelled), "
            "seller_details_missing, order_amounts_inconsistent or invoice_numbers_exhausted; "
            "no number is used",
        },
        **VALIDATION_422,
    },
)
def recover_order_invoice(
    order_id: uuid.UUID, current_user: InvoiceRecoverer, db: Db, ctx: Ctx, response: Response
) -> InvoiceIssueResponse:
    invoice, issued = invoice_service.recover_invoice(db, order_id, current_user, ctx)
    if not issued:
        response.status_code = status.HTTP_200_OK
    return InvoiceIssueResponse(
        order_id=invoice.order_id,
        invoice_number=invoice.invoice_number,
        issued_at=invoice.issued_at,
        total=invoice.total,
        vat_amount=invoice.vat_amount,
        issued=issued,
    )


@staff_router.get(
    "/{order_id}/delivery-note",
    response_class=Response,
    summary="Download an order's delivery note",
    description=(
        "Requires 'orders:fulfil'. Order number, recipient, delivery address and items; no "
        "prices or payment details. Eligibility is a proposed default pending Product/Operations "
        "approval (no requirement names the states): available once all of the order's stock is "
        "committed for delivery (a paid mobile-money order from 'received', or a cash-on-delivery "
        "order from 'confirmed') or dispatched, and the order is not cancelled."
    ),
    responses={
        **PDF_200,
        **AUTH_ERRORS,
        **ORDER_404,
        409: {
            **ERR,
            "description": "delivery_note_unavailable: the order's stock is not committed for "
            "delivery, or the order is cancelled",
        },
        **VALIDATION_422,
    },
)
def download_delivery_note(order_id: uuid.UUID, _: OrderFulfiller, db: Db) -> Response:
    note = invoice_service.delivery_note(db, order_id)
    return _pdf(render_delivery_note(note), f"delivery-note-{note.order_number}.pdf")
