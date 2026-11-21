"""Product reviews, part 2 (module 20, scope change SC-01 approved by the project owner 2026-10-27).

- **Links.** A verified buyer gets a single-use link per delivered order item: the signed-in
  customer for their own order, a guest after the order lookup (same counters as the lookup).
  Only a SHA-256 hash of the 256-bit token is stored. Issuing again replaces the hash while the
  link is unused, so an earlier link stops working. Links expire 90 days after delivery.
  Sending them by SMS or email waits for module 17.
- **Submitting.** Rating 1-5, optional title and body, plain text, no editing afterwards. The
  review starts `pending`; the link is spent in the same transaction. Every attempt counts
  towards the per-link and per-network limits; an unreachable limit store refuses (503).
- **Moderation.** Approve or reject (optional reason; a decision can be changed later). The
  product's rating totals are recalculated from its approved reviews under the product's row lock
  in the same transaction, and the change is audited (catalog.review_approve / _reject).
- **Public list.** Approved reviews of a public product, newest first.
"""

import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, ServiceUnavailable, TooManyRequests
from app.core.rate_limit import LoginRateLimiter, RateLimitStoreUnavailable
from app.core.request_context import RequestContext
from app.core.security import hash_session_token
from app.db.transaction import atomic
from app.models import Product, User
from app.models.commerce import Order, OrderItem
from app.models.engagement import REVIEW_AUTHOR_MAX_LENGTH, ProductReview
from app.repositories import catalog as catalog_repository
from app.repositories.order_repository import OrderRepository
from app.repositories.review_repository import ReviewRepository
from app.schemas.reviews import GuestReviewLinkRequest, ReviewSubmitRequest
from app.services import catalog as catalog_service
from app.services.audit_service import AuditService
from app.services.notification_service import record_email_event
from app.services.order_service import OrderService

logger = logging.getLogger("app.reviews")

LINK_LIFETIME = timedelta(days=90)
ORDER_NOT_FOUND = "Order not found."
ITEM_NOT_FOUND = "This item is not part of the order."
NOT_DELIVERED = "Only delivered items can be reviewed."
ALREADY_REVIEWED = "This item has already been reviewed."
LINK_EXPIRED = "This review link has expired."
LINK_NOT_FOUND = "This review link is not valid."
PRODUCT_GONE = "This product can no longer be reviewed."
REVIEW_NOT_FOUND = "Review not found."
SUBMIT_LIMITED = "Too many attempts. Please try again later."
SUBMIT_UNAVAILABLE = "Reviews cannot be sent right now. Please try again later."


def hash_review_token(token: str) -> str:
    """SHA-256 of the link token (the same digest as session tokens); only this is stored."""
    return hash_session_token(token)


def author_name(recipient_name: str) -> str:
    """'Aline Uwase' -> 'Aline U.'; a single name stays as it is."""
    parts = recipient_name.split()
    if not parts:
        return "Customer"
    name = parts[0] if len(parts) == 1 else f"{parts[0]} {parts[-1][0].upper()}."
    return name[:REVIEW_AUTHOR_MAX_LENGTH]


def _now() -> datetime:
    return datetime.now(UTC)


def _audit(
    db: Session,
    action: str,
    review: ProductReview,
    actor: User,
    ctx: RequestContext,
    **details: Any,
) -> None:
    AuditService.log_event(
        db=db,
        action=action,
        status="success",
        actor=actor,
        entity_type="product_review",
        entity_id=review.id,
        context=ctx,
        details={"product_id": str(review.product_id), **details},
    )


def recalculate_rating(db: Session, product_id: uuid.UUID) -> None:
    """Store the approved reviews' totals on the product. Call inside the caller's transaction;
    the product row is locked so concurrent decisions on one product apply one after another."""
    product = ReviewRepository.lock_product(db, product_id)
    distribution = ReviewRepository.approved_distribution(db, product_id)
    count = sum(distribution.values())
    for stars in range(1, 6):
        setattr(product, f"rating_{stars}_count", distribution.get(stars, 0))
    product.rating_count = count
    product.rating_average = (
        (Decimal(sum(s * n for s, n in distribution.items())) / count).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
        if count
        else None
    )


class ReviewService:
    # ---- links -------------------------------------------------------------------------------

    @staticmethod
    def issue_for_customer(
        db: Session, user: User, order_id: uuid.UUID, order_item_id: uuid.UUID
    ) -> tuple[str, datetime]:
        with atomic(db):
            order = OrderRepository.get_owned(db, order_id, user.id)
            if order is None:
                raise NotFound(ORDER_NOT_FOUND, code="order_not_found")
            return ReviewService._issue(db, order, order_item_id)

    @staticmethod
    def issue_for_guest(
        db: Session, req: GuestReviewLinkRequest, limiter: LoginRateLimiter, ctx: RequestContext
    ) -> tuple[str, datetime]:
        order = OrderService.find_guest_order(db, req.order_number, req.phone, limiter, ctx)
        with atomic(db):
            return ReviewService._issue(db, order, req.order_item_id)

    @staticmethod
    def _issue(db: Session, order: Order, order_item_id: uuid.UUID) -> tuple[str, datetime]:
        item: OrderItem | None = next((i for i in order.items if i.id == order_item_id), None)
        if item is None:
            raise NotFound(ITEM_NOT_FOUND, code="order_item_not_found")
        if order.status != "delivered":
            raise Conflict(NOT_DELIVERED, code="not_delivered")
        if item.product_id is None:
            raise Conflict(PRODUCT_GONE, code="product_unavailable")
        if ReviewRepository.review_exists(db, item.id):
            raise Conflict(ALREADY_REVIEWED, code="already_reviewed")
        delivered = ReviewRepository.delivered_at(db, order.id) or order.updated_at
        expires_at = delivered + LINK_LIFETIME
        if expires_at <= _now():
            raise Conflict(LINK_EXPIRED, code="review_link_expired")
        token = secrets.token_urlsafe(32)
        if not ReviewRepository.upsert_unused_token(
            db, item.id, hash_review_token(token), expires_at
        ):
            raise Conflict(ALREADY_REVIEWED, code="already_reviewed")
        return token, expires_at

    @staticmethod
    def link_info(db: Session, token: str) -> dict[str, Any]:
        link = ReviewRepository.token_by_hash(db, hash_review_token(token))
        if link is None:
            raise NotFound(LINK_NOT_FOUND, code="review_link_not_found")
        item, _ = ReviewRepository.item_with_order(db, link.order_item_id)
        status = (
            "used"
            if link.used_at is not None
            else "expired"
            if link.expires_at <= _now()
            else "open"
        )
        public = (
            catalog_repository.get_public_products_by_ids(db, [item.product_id])
            if item.product_id
            else []
        )
        product = public[0] if public else None
        image = None
        if product is not None:
            own = [i for i in product.images if i.variant_id is None] or list(product.images)
            first = min(own, key=lambda i: (i.sort_order, str(i.id)), default=None)
            if first is not None:
                image = catalog_service.product_image_data(
                    catalog_service.get_media_storage(), first, product
                )
        variant = item.variant_snapshot or {}
        return {
            "status": status,
            "expires_at": link.expires_at,
            "product": {
                "name": item.product_name_snapshot,
                "slug": product.slug if product is not None else None,
                "image": image,
            },
            "variant_name": variant.get("name") if isinstance(variant, dict) else None,
        }

    # ---- submitting --------------------------------------------------------------------------

    @staticmethod
    def submit(
        db: Session,
        token: str,
        req: ReviewSubmitRequest,
        limiter: LoginRateLimiter,
        ctx: RequestContext,
    ) -> ProductReview:
        token_hash = hash_review_token(token)
        try:
            decision = limiter.check(token_hash, ctx.ip_address)
            if decision.allowed:
                limiter.record_failure(token_hash, ctx.ip_address)  # every attempt counts
        except RateLimitStoreUnavailable:
            logger.error("Review refused: the rate-limit store is unavailable")
            raise ServiceUnavailable(SUBMIT_UNAVAILABLE, code="review_unavailable") from None
        if not decision.allowed:
            logger.warning("Review submission limit reached (%s)", decision.scope)
            raise TooManyRequests(
                SUBMIT_LIMITED,
                code="rate_limited",
                headers={"Retry-After": str(decision.retry_after)},
            )

        with atomic(db):
            link = ReviewRepository.token_by_hash(db, token_hash, lock=True)
            if link is None:
                raise NotFound(LINK_NOT_FOUND, code="review_link_not_found")
            if link.used_at is not None:
                raise Conflict(ALREADY_REVIEWED, code="already_reviewed")
            if link.expires_at <= _now():
                raise Conflict(LINK_EXPIRED, code="review_link_expired")
            item, order = ReviewRepository.item_with_order(db, link.order_item_id)
            if item.product_id is None:
                raise Conflict(PRODUCT_GONE, code="product_unavailable")
            review = ProductReview(
                product_id=item.product_id,
                order_item_id=item.id,
                user_id=order.user_id,
                rating=req.rating,
                title=req.title,
                body=req.body,
                author_name=author_name(order.recipient_name),
                status="pending",
            )
            db.add(review)
            link.used_at = _now()
            db.flush()
            record_email_event(db, "review_thanks", review.id, order.customer_email_snapshot)
            return review

    # ---- public ------------------------------------------------------------------------------

    @staticmethod
    def public_page(
        db: Session, slug: str, page: int, size: int
    ) -> tuple[list[ProductReview], int]:
        product = catalog_repository.get_public_product_by_slug(db, slug)
        if product is None:
            raise NotFound("Product not found", code="product_not_found")
        return ReviewRepository.approved_page(db, product.id, page, size)

    # ---- moderation --------------------------------------------------------------------------

    @staticmethod
    def staff_page(
        db: Session, status: str | None, page: int, size: int
    ) -> tuple[list[tuple[ProductReview, Product, Order]], int]:
        return ReviewRepository.staff_page(db, status, page, size)

    @staticmethod
    def staff_row(db: Session, review_id: uuid.UUID) -> tuple[ProductReview, Product, Order]:
        return ReviewRepository.staff_row(db, review_id)

    @staticmethod
    def moderate(
        db: Session,
        review_id: uuid.UUID,
        new_status: str,
        reason: str | None,
        actor: User,
        ctx: RequestContext,
    ) -> ProductReview:
        with atomic(db):
            review = ReviewRepository.lock_review(db, review_id)
            if review is None:
                raise NotFound(REVIEW_NOT_FOUND, code="review_not_found")
            if review.status == new_status:
                raise Conflict(
                    f"This review is already {new_status}.", code=f"review_already_{new_status}"
                )
            previous = review.status
            review.status = new_status
            review.moderation_reason = reason
            review.moderated_by_user_id = actor.id
            review.moderated_at = _now()
            db.flush()
            recalculate_rating(db, review.product_id)
            action = (
                "catalog.review_approve" if new_status == "approved" else "catalog.review_reject"
            )
            _audit(db, action, review, actor, ctx, previous_status=previous, reason=reason)
            return review
