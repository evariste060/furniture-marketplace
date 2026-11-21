"""Payments (module 15; TC-08-TC-12; §7 Q17, Q21). Rules are in app.services.payment_service.

- POST /payments/{order_number}/initiate and GET /payments/{order_number}/status: the signed-in
  customer who owns the order, or a guest with the order's phone (body `phone` to initiate; the
  `X-Order-Phone` header for status, so the phone never appears in a URL). Guest attempts count
  on the guest-lookup limits (ADR-008 S6). Every mismatch is the same 404.
- POST /webhooks/{provider}: provider callbacks, verified before anything is stored.
- GET /staff/payments and /staff/payments/events: payments:read (administrator, management,
  finance); read-only. POST /staff/payments/{attempt_id}/confirm-cod: payments:manage
  (administrator).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.api.v1.notifier import Notifier
from app.api.v1.pagination import PageNumber, PageSize
from app.api.v1.responses import ERR, FORBIDDEN_403, UNAUTHORIZED_401, VALIDATION_422, ResponseMap
from app.core.dependencies import (
    get_current_session,
    get_current_user,
    require_permission,
    security_scheme,
)
from app.core.errors import field_error
from app.core.identifiers import PHONE_INPUT_MAX_LENGTH, validate_rwanda_phone
from app.core.rate_limit import LoginRateLimiter, get_order_lookup_rate_limiter
from app.core.request_context import RequestContext, get_request_context
from app.core.roles import Permission
from app.db.session import get_db
from app.integrations.payments import WebhookRequest
from app.models.identity import User
from app.schemas.order import PaymentMethod, PaymentStatus
from app.schemas.pagination import DEFAULT_PAGE_SIZE, Page
from app.schemas.payments import (
    PaymentAccessRequest,
    PaymentMethodChangeRequest,
    PaymentStatusResponse,
    ProcessingStatus,
    StaffPaymentEventItem,
    StaffPaymentItem,
    StaffPaymentPage,
    WebhookAck,
)
from app.services.payment_service import PaymentService

router = APIRouter(prefix="/payments", tags=["Payments"])
webhook_router = APIRouter(prefix="/webhooks", tags=["Payments"])
staff_router = APIRouter(prefix="/staff/payments", tags=["Staff Payments"])

Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[RequestContext, Depends(get_request_context)]
Limiter = Annotated[LoginRateLimiter, Depends(get_order_lookup_rate_limiter)]
Reader = Annotated[User, Depends(require_permission(Permission.PAYMENTS_READ))]
Manager = Annotated[User, Depends(require_permission(Permission.PAYMENTS_MANAGE))]

ACCESS: ResponseMap = {
    401: {**ERR, "description": "A bearer token was sent but is not valid"},
    403: {**ERR, "description": "The signed-in account is inactive or disabled"},
    404: {**ERR, "description": "order_not_found: unknown, not yours, or the phone does not match"},
    **VALIDATION_422,
    429: {**ERR, "description": "rate_limited: too many failed guest lookups (ADR-008 S6)"},
    503: {
        **ERR,
        "description": "order_lookup_unavailable (rate-limit store) or "
        "payment_provider_unavailable (mobile money not configured)",
    },
}
GUARDED: ResponseMap = {**UNAUTHORIZED_401, **FORBIDDEN_403}


def optional_user(
    ctx: Ctx,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security_scheme)],
    db: Db,
) -> User | None:
    """The signed-in user when a bearer token is sent (it must be valid), else a guest."""
    if credentials is not None and credentials.credentials:
        return get_current_user(get_current_session(ctx, credentials, db))
    return None


Caller = Annotated[User | None, Depends(optional_user)]


@router.post(
    "/{order_number}/initiate",
    response_model=PaymentStatusResponse,
    summary="Start paying for an order",
    description=(
        "Mobile money uses the `mock` provider until ADR-003 (§7 Q21): a test stand-in that "
        "moves no money. Repeating the call while the payment is pending returns the same "
        "reference; after a failed or cancelled attempt a new attempt starts (while the stock "
        "hold lasts). Cash on delivery stays pending until delivery. 409 codes: "
        "payment_already_succeeded, order_not_payable, payment_method_unavailable, "
        "payment_initiation_in_progress (another request is starting this payment), "
        "payment_initiation_needs_recovery (the payment's start could not be confirmed: an "
        "earlier start has an unknown outcome and the provider does not guarantee idempotent "
        "initiation, or the provider answered after the order was cancelled or its hold "
        "expired; a reconciliation record is kept for staff and the payment is not marked "
        "failed). 502 payment_provider_error."
    ),
    responses={
        **ACCESS,
        409: {
            **ERR,
            "description": "payment_already_succeeded, order_not_payable, "
            "payment_method_unavailable, payment_initiation_in_progress, "
            "payment_initiation_needs_recovery",
        },
        502: {**ERR, "description": "payment_provider_error"},
    },
)
def initiate_payment(
    order_number: str,
    caller: Caller,
    db: Db,
    ctx: Ctx,
    limiter: Limiter,
    req: PaymentAccessRequest | None = None,
) -> PaymentStatusResponse:
    phone = req.phone if req is not None else None
    return PaymentService.initiate(db, order_number, caller, phone, limiter, ctx)


@router.get(
    "/{order_number}/status",
    response_model=PaymentStatusResponse,
    summary="Read an order's payment status",
    description="Guests send the order's phone in `X-Order-Phone`.",
    responses=ACCESS,
)
def payment_status(
    order_number: str,
    caller: Caller,
    db: Db,
    ctx: Ctx,
    limiter: Limiter,
    x_order_phone: Annotated[
        str | None, Header(alias="X-Order-Phone", max_length=PHONE_INPUT_MAX_LENGTH)
    ] = None,
) -> PaymentStatusResponse:
    phone = None
    if x_order_phone is not None:
        try:
            phone = validate_rwanda_phone(x_order_phone)
        except ValueError as exc:
            raise field_error(("header", "X-Order-Phone"), str(exc)) from None
    return PaymentService.status(db, order_number, caller, phone, limiter, ctx)


@router.post(
    "/{order_number}/method",
    response_model=PaymentStatusResponse,
    summary="Switch an unpaid order's payment method",
    description=(
        "For example after a failed mobile-money request, to pay cash on delivery. The current "
        "attempt is cancelled and a new one starts for the new method (mobile money: start it "
        "with /initiate; cash on delivery: pending until delivery). The stock hold then runs "
        "from the order's creation by the new method's rule (15 minutes mobile money, 24 hours "
        "cash on delivery). The same method changes nothing. 409 codes: "
        "payment_already_succeeded, order_not_payable (closed, or the stock is no longer "
        "held), payment_in_progress (a mobile-money request is open or being started), "
        "payment_method_change_too_late (the new method's time to pay has passed). 422 for "
        "card or cash on delivery where the delivery zone does not offer it."
    ),
    responses={
        **ACCESS,
        409: {
            **ERR,
            "description": "payment_already_succeeded, order_not_payable, payment_in_progress, "
            "payment_method_change_too_late",
        },
    },
)
def change_payment_method(
    order_number: str,
    req: PaymentMethodChangeRequest,
    caller: Caller,
    db: Db,
    ctx: Ctx,
    limiter: Limiter,
) -> PaymentStatusResponse:
    return PaymentService.change_method(
        db, order_number, caller, req.phone, req.payment_method, limiter, ctx
    )


@webhook_router.post(
    "/{provider}",
    response_model=WebhookAck,
    summary="Payment provider callback",
    description=(
        "Verified before anything is stored (the mock provider: HMAC-SHA256 over "
        "`<X-Mock-Timestamp>.<body>` in `X-Mock-Signature`). A duplicate event answers 200 "
        "without repeating anything. 401 invalid_signature; 422 malformed_event; 404 unknown "
        "provider; 503 when the provider is not configured."
    ),
    responses={
        422: {**ERR, "description": "malformed_event: the verified payload is not a valid event"},
        401: {**ERR, "description": "invalid_signature"},
        404: {**ERR, "description": "provider_not_found"},
        503: {**ERR, "description": "payment_provider_unavailable"},
    },
)
async def provider_webhook(
    provider: str, request: Request, db: Db, background: BackgroundTasks, notifier: Notifier
) -> WebhookAck:
    body = await request.body()
    headers = {name.lower(): value for name, value in request.headers.items()}
    ack = PaymentService.webhook(db, provider, WebhookRequest(headers=headers, body=body))
    notifier.schedule(background, db)  # a late success cancels the order (module 17 message)
    return ack


@staff_router.get(
    "",
    response_model=StaffPaymentPage,
    summary="Payment attempts (reconciliation list)",
    description=(
        "Requires 'payments:read' (administrator, management, finance). Read-only; newest first. "
        "`amount_total` sums `amount` over every attempt matching the filters, not just this page."
    ),
    responses={**GUARDED, **VALIDATION_422},
)
def list_payments(
    _: Reader,
    db: Db,
    page: PageNumber = 1,
    size: PageSize = DEFAULT_PAGE_SIZE,
    status: PaymentStatus | None = None,
    method: PaymentMethod | None = None,
    needs_reconciliation: bool | None = None,
) -> StaffPaymentPage:
    return PaymentService.staff_list(
        db,
        status=status,
        method=method,
        needs_reconciliation=needs_reconciliation,
        page=page,
        size=size,
    )


@staff_router.get(
    "/events",
    response_model=Page[StaffPaymentEventItem],
    summary="Payment provider events",
    description=(
        "Requires 'payments:read'. Sanitised metadata only (masked phone, no card data). "
        "Includes the service's own reconciliation records (provider `internal`, "
        "needs_reconciliation, linked to the attempt)."
    ),
    responses={**GUARDED, **VALIDATION_422},
)
def list_payment_events(
    _: Reader,
    db: Db,
    page: PageNumber = 1,
    size: PageSize = DEFAULT_PAGE_SIZE,
    processing_status: ProcessingStatus | None = None,
) -> Page[StaffPaymentEventItem]:
    return PaymentService.staff_events(
        db, processing_status=processing_status, page=page, size=size
    )


@staff_router.post(
    "/{attempt_id}/confirm-cod",
    response_model=StaffPaymentItem,
    summary="Record cash on delivery as collected",
    description=(
        "Requires 'payments:manage' (administrator). Only for a cash-on-delivery payment of a "
        "delivered order (409 order_not_delivered before that; TC-12). Delivery already marks it "
        "succeeded (§7 Q14); confirming a succeeded payment changes nothing. Audited as "
        "'payment.cod_confirm'."
    ),
    responses={
        **GUARDED,
        404: {**ERR, "description": "payment_not_found"},
        409: {**ERR, "description": "payment_not_cod or order_not_delivered"},
        **VALIDATION_422,
    },
)
def confirm_cod(
    attempt_id: uuid.UUID,
    current_user: Manager,
    db: Db,
    ctx: Ctx,
    background: BackgroundTasks,
    notifier: Notifier,
) -> StaffPaymentItem:
    item = PaymentService.confirm_cod(db, current_user, attempt_id, ctx)
    notifier.schedule(background, db)  # the payment received email
    return item
