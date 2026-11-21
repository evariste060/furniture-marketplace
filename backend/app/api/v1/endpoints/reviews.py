"""Product reviews, part 2 (module 20, scope change SC-01 approved by the project owner 2026-10-27).

Review links for verified buyers (customer and guest), the review page's link check and
submission, the public list of approved reviews, and staff moderation (`reviews:moderate`).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.api.v1.notifier import Notifier
from app.api.v1.pagination import PageNumber, PageSize
from app.api.v1.responses import (
    AUTHENTICATED,
    ERR,
    FORBIDDEN_403,
    UNAUTHORIZED_401,
    VALIDATION_422,
    ResponseMap,
)
from app.core.dependencies import get_current_user, require_permission
from app.core.rate_limit import (
    LoginRateLimiter,
    get_order_lookup_rate_limiter,
    get_review_submit_rate_limiter,
)
from app.core.request_context import RequestContext, get_request_context
from app.core.roles import Permission
from app.db.session import get_db
from app.models import Product
from app.models.commerce import Order
from app.models.engagement import ProductReview
from app.models.identity import User
from app.schemas.pagination import DEFAULT_PAGE_SIZE, Page
from app.schemas.reviews import (
    ApproveReviewRequest,
    GuestReviewLinkRequest,
    PublicReview,
    RejectReviewRequest,
    ReviewLinkInfo,
    ReviewLinkResponse,
    ReviewStatus,
    ReviewSubmitRequest,
    ReviewSubmitResponse,
    StaffReview,
)
from app.services.review_service import ReviewService

customer_router = APIRouter(prefix="/customers/me/orders", tags=["Reviews"])
guest_router = APIRouter(prefix="/orders", tags=["Reviews"])
link_router = APIRouter(prefix="/reviews", tags=["Reviews"])
public_router = APIRouter(prefix="/catalog", tags=["catalog"])
staff_router = APIRouter(prefix="/staff/reviews", tags=["Reviews"])

Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[RequestContext, Depends(get_request_context)]
Moderator = Annotated[User, Depends(require_permission(Permission.REVIEWS_MODERATE))]
# Review links are 256-bit URL-safe tokens (43 characters); anything else is refused early.
Token = Annotated[str, Path(min_length=20, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")]

LINK_409: ResponseMap = {
    409: {
        **ERR,
        "description": "not_delivered, already_reviewed, review_link_expired or "
        "product_unavailable",
    }
}
LIMITED_429: ResponseMap = {
    429: {
        **ERR,
        "description": "rate_limited",
        "headers": {
            "Retry-After": {"description": "Seconds to wait", "schema": {"type": "integer"}}
        },
    }
}
STAFF_ERRORS: ResponseMap = {**UNAUTHORIZED_401, **FORBIDDEN_403}
LINK_DESCRIPTION = (
    "Returns a single-use link token for one delivered item, valid until 90 days after "
    "delivery; the storefront page is /review/{token}. Asking again replaces the token while the "
    "link is unused (the earlier link stops working). Only a hash of the token is stored."
)


def _link(token_and_expiry: tuple[str, object]) -> ReviewLinkResponse:
    token, expires_at = token_and_expiry
    return ReviewLinkResponse.model_validate({"token": token, "expires_at": expires_at})


@customer_router.post(
    "/{order_id}/items/{order_item_id}/review-link",
    response_model=ReviewLinkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Get a review link for an item of an own order",
    description=LINK_DESCRIPTION + " Orders owned by someone else answer 404.",
    responses={
        **AUTHENTICATED,
        404: {**ERR, "description": "order_not_found or order_item_not_found"},
        **LINK_409,
        **VALIDATION_422,
    },
)
def customer_review_link(
    order_id: uuid.UUID,
    order_item_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Db,
) -> ReviewLinkResponse:
    return _link(ReviewService.issue_for_customer(db, user, order_id, order_item_id))


@guest_router.post(
    "/review-link",
    response_model=ReviewLinkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Get a review link as a guest",
    description=LINK_DESCRIPTION
    + " The order is found as in POST /orders/lookup (order number and phone), with the same "
    "limits: failed lookups count towards that endpoint's 429.",
    responses={
        404: {**ERR, "description": "order_not_found or order_item_not_found"},
        **LINK_409,
        **VALIDATION_422,
        **LIMITED_429,
        503: {**ERR, "description": "order_lookup_unavailable"},
    },
)
def guest_review_link(
    req: GuestReviewLinkRequest,
    db: Db,
    ctx: Ctx,
    limiter: Annotated[LoginRateLimiter, Depends(get_order_lookup_rate_limiter)],
) -> ReviewLinkResponse:
    return _link(ReviewService.issue_for_guest(db, req, limiter, ctx))


@link_router.get(
    "/{token}",
    response_model=ReviewLinkInfo,
    summary="Check a review link",
    description="The product being reviewed and whether the link is open, expired or used.",
    responses={404: {**ERR, "description": "review_link_not_found"}, **VALIDATION_422},
)
def review_link_info(token: Token, db: Db) -> ReviewLinkInfo:
    return ReviewLinkInfo.model_validate(ReviewService.link_info(db, token))


@link_router.post(
    "/{token}",
    response_model=ReviewSubmitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a review",
    description=(
        "Rating 1-5 and an optional title (80) and text (2,000), plain text. The review waits "
        "for moderation and cannot be edited. The link is spent. Every attempt counts: at most "
        "5 per link and 20 per network an hour (429 with Retry-After); while the limit store is "
        "unreachable every request answers 503."
    ),
    responses={
        404: {**ERR, "description": "review_link_not_found"},
        409: {**ERR, "description": "already_reviewed, review_link_expired or product_unavailable"},
        **VALIDATION_422,
        **LIMITED_429,
        503: {**ERR, "description": "review_unavailable"},
    },
)
def submit_review(
    token: Token,
    req: ReviewSubmitRequest,
    db: Db,
    ctx: Ctx,
    limiter: Annotated[LoginRateLimiter, Depends(get_review_submit_rate_limiter)],
    background: BackgroundTasks,
    notifier: Notifier,
) -> ReviewSubmitResponse:
    review = ReviewService.submit(db, token, req, limiter, ctx)
    notifier.schedule(background, db)  # the thank-you email
    return ReviewSubmitResponse(id=review.id, status="pending")


@public_router.get(
    "/products/{slug}/reviews",
    response_model=Page[PublicReview],
    summary="Approved reviews of a product",
    description="Newest first. Every review is from a buyer of a delivered item.",
    responses={404: {**ERR, "description": "product_not_found"}, **VALIDATION_422},
)
def product_reviews(
    slug: str, db: Db, page: PageNumber = 1, size: PageSize = DEFAULT_PAGE_SIZE
) -> Page[PublicReview]:
    items, total = ReviewService.public_page(db, slug, page, size)
    return Page[PublicReview](
        items=[PublicReview.model_validate(r, from_attributes=True) for r in items],
        total=total,
        page=page,
        size=size,
    )


def _staff(review: ProductReview, product: Product, order: Order) -> StaffReview:
    return StaffReview(
        id=review.id,
        status=review.status,  # type: ignore[arg-type]
        rating=review.rating,
        title=review.title,
        body=review.body,
        author_name=review.author_name,
        product_id=product.id,
        product_name=product.name,
        product_slug=product.slug,
        order_number=order.order_number,
        moderation_reason=review.moderation_reason,
        moderated_at=review.moderated_at,
        created_at=review.created_at,
    )


@staff_router.get(
    "",
    response_model=Page[StaffReview],
    summary="List reviews",
    description="Requires 'reviews:moderate' (administrator, sales). Newest first; `status` "
    "filters (e.g. pending for the moderation queue).",
    responses={**STAFF_ERRORS, **VALIDATION_422},
)
def list_reviews(
    _: Moderator,
    db: Db,
    status_filter: Annotated[ReviewStatus | None, Query(alias="status")] = None,
    page: PageNumber = 1,
    size: PageSize = DEFAULT_PAGE_SIZE,
) -> Page[StaffReview]:
    rows, total = ReviewService.staff_page(db, status_filter, page, size)
    return Page[StaffReview](
        items=[_staff(*row) for row in rows], total=total, page=page, size=size
    )


MODERATE_RESPONSES: ResponseMap = {
    **STAFF_ERRORS,
    404: {**ERR, "description": "review_not_found"},
    409: {**ERR, "description": "review_already_approved or review_already_rejected"},
    **VALIDATION_422,
}


def _moderated(db: Session, review: ProductReview) -> StaffReview:
    return _staff(*ReviewService.staff_row(db, review.id))


@staff_router.post(
    "/{review_id}/approve",
    response_model=StaffReview,
    summary="Approve a review",
    description="Publishes the review and recalculates the product's rating in the same "
    "transaction. A rejected review can be approved later. Audited as catalog.review_approve.",
    responses=MODERATE_RESPONSES,
)
def approve_review(
    review_id: uuid.UUID,
    actor: Moderator,
    db: Db,
    ctx: Ctx,
    req: ApproveReviewRequest | None = None,
) -> StaffReview:
    review = ReviewService.moderate(
        db, review_id, "approved", req.reason if req else None, actor, ctx
    )
    return _moderated(db, review)


@staff_router.post(
    "/{review_id}/reject",
    response_model=StaffReview,
    summary="Reject a review",
    description="Hides the review (also an approved one) and recalculates the product's rating "
    "in the same transaction. The optional reason is for staff only. Audited as "
    "catalog.review_reject.",
    responses=MODERATE_RESPONSES,
)
def reject_review(
    review_id: uuid.UUID,
    actor: Moderator,
    db: Db,
    ctx: Ctx,
    req: RejectReviewRequest | None = None,
) -> StaffReview:
    review = ReviewService.moderate(
        db, review_id, "rejected", req.reason if req else None, actor, ctx
    )
    return _moderated(db, review)
