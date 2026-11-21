"""Business quote requests (module 19, approved 2026-10-29; Contact page, PR-01). Rules are in
app.services.quotes.

POST /quote-requests is public and rate limited. The staff routes need 'quotes:manage'
(administrator, sales).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.v1.notifier import Notifier
from app.api.v1.pagination import PageNumber, PageSize
from app.api.v1.responses import ERR, FORBIDDEN_403, UNAUTHORIZED_401, VALIDATION_422, ResponseMap
from app.core.dependencies import require_permission
from app.core.rate_limit import LoginRateLimiter, get_quote_request_rate_limiter
from app.core.request_context import RequestContext, get_request_context
from app.core.roles import Permission
from app.db.session import get_db
from app.models.identity import User
from app.schemas.pagination import DEFAULT_PAGE_SIZE, Page
from app.schemas.quotes import (
    QuoteRequestCreate,
    QuoteRequestCreated,
    QuoteStatus,
    QuoteStatusRequest,
    StaffQuoteRequest,
)
from app.services.quotes import QuoteService

public_router = APIRouter(prefix="/quote-requests", tags=["Storefront Content"])
staff_router = APIRouter(prefix="/staff/quote-requests", tags=["Staff Content"])

Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[RequestContext, Depends(get_request_context)]
QuoteManager = Annotated[User, Depends(require_permission(Permission.QUOTES_MANAGE))]
GUARDED: ResponseMap = {**UNAUTHORIZED_401, **FORBIDDEN_403}


@public_router.post(
    "",
    response_model=QuoteRequestCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Send a business quote request",
    description=(
        "Public. Company, contact person and a Rwandan mobile number are required, with 1 to 20 "
        "product lines (name or model, quantity 1-100,000). Email, delivery location, needed-by "
        "date (today to one year ahead, Kigali time) and a message are optional. Every attempt "
        "counts against a limit per phone number and per network (429 with Retry-After); an "
        "unavailable limit store answers 503. Returns the request's reference."
    ),
    responses={
        **VALIDATION_422,
        429: {
            **ERR,
            "description": "rate_limited",
            "headers": {
                "Retry-After": {"description": "Seconds to wait", "schema": {"type": "integer"}}
            },
        },
        503: {**ERR, "description": "quote_unavailable"},
    },
)
def send_quote_request(
    req: QuoteRequestCreate,
    db: Db,
    ctx: Ctx,
    limiter: Annotated[LoginRateLimiter, Depends(get_quote_request_rate_limiter)],
    background: BackgroundTasks,
    notifier: Notifier,
) -> QuoteRequestCreated:
    quote = QuoteService.create(db, req, limiter, ctx)
    notifier.schedule(background, db)  # the acknowledgement, when an email was given
    return QuoteRequestCreated(reference=quote.reference)


@staff_router.get(
    "",
    response_model=Page[StaffQuoteRequest],
    summary="List quote requests",
    description="Requires 'quotes:manage' (administrator, sales). Newest first; `status` filters.",
    responses={**GUARDED, **VALIDATION_422},
)
def list_quote_requests(
    _: QuoteManager,
    db: Db,
    status_filter: Annotated[QuoteStatus | None, Query(alias="status")] = None,
    page: PageNumber = 1,
    size: PageSize = DEFAULT_PAGE_SIZE,
) -> Page[StaffQuoteRequest]:
    rows, total = QuoteService.staff_page(db, status_filter, page, size)
    return Page[StaffQuoteRequest](
        items=[StaffQuoteRequest.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


@staff_router.patch(
    "/{quote_id}",
    response_model=StaffQuoteRequest,
    summary="Change a quote request's status",
    description=(
        "Requires 'quotes:manage' (administrator, sales). new, contacted or closed; moving out "
        "of new records who handled it and when. Audited as 'quote.status_change'; setting the "
        "current status changes nothing and is not audited."
    ),
    responses={
        **GUARDED,
        404: {**ERR, "description": "quote_request_not_found"},
        **VALIDATION_422,
    },
)
def change_quote_status(
    quote_id: uuid.UUID, req: QuoteStatusRequest, actor: QuoteManager, db: Db, ctx: Ctx
) -> StaffQuoteRequest:
    quote = QuoteService.set_status(db, actor, quote_id, req.status, ctx)
    return StaffQuoteRequest.model_validate(quote)
