"""Customer engagement (scope change SC-01, approved 2026-10-27): the wishlist (module 21) and
product reviews with their single-use review links (module 20)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.common import Entity

if TYPE_CHECKING:
    from app.models.catalog import Product

WISHLIST_LIMIT = 200
REVIEW_TITLE_MAX_LENGTH = 80
REVIEW_BODY_MAX_LENGTH = 2000
REVIEW_AUTHOR_MAX_LENGTH = 80
MODERATION_REASON_MAX_LENGTH = 500
REVIEW_STATUSES = ("pending", "approved", "rejected")


class WishlistItem(Entity):
    """A product a signed-in customer saved. Removing it deletes the row."""

    __tablename__ = "wishlist_items"
    __table_args__ = (
        UniqueConstraint("user_id", "product_id", name="user_product"),
        Index("ix_wishlist_items_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    product: Mapped[Product] = relationship(lazy="raise")


class ReviewToken(Entity):
    """The single-use link for reviewing one delivered order item. Only a SHA-256 hash of the
    random token is stored; issuing again replaces the hash while the link is unused. It expires
    90 days after delivery and is spent (used_at) when the review is sent."""

    __tablename__ = "review_tokens"
    __table_args__ = (
        UniqueConstraint("order_item_id", name="review_token_order_item"),
        UniqueConstraint("token_hash", name="review_token_hash"),
    )

    order_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("order_items.id", ondelete="RESTRICT"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProductReview(Entity):
    """A verified buyer's review of one delivered order item. Plain text only. Public only once
    approved; the product's rating totals count approved reviews."""

    __tablename__ = "product_reviews"
    __table_args__ = (
        UniqueConstraint("order_item_id", name="review_order_item"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="rating_range"),
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="valid_status"),
        CheckConstraint(
            "(status = 'pending') = (moderated_at IS NULL)", name="moderated_unless_pending"
        ),
        Index("ix_product_reviews_product_status_created", "product_id", "status", "created_at"),
        Index("ix_product_reviews_status_created", "status", "created_at"),
    )

    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    order_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("order_items.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    title: Mapped[str | None] = mapped_column(String(REVIEW_TITLE_MAX_LENGTH))
    body: Mapped[str | None] = mapped_column(String(REVIEW_BODY_MAX_LENGTH))
    author_name: Mapped[str] = mapped_column(String(REVIEW_AUTHOR_MAX_LENGTH), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    moderation_reason: Mapped[str | None] = mapped_column(String(MODERATION_REASON_MAX_LENGTH))
    moderated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    moderated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
