"""Marketplace stores (ADR-014, SC-04; phase 1, approved 2026-11-21).

A store is one seller's shop. Its row is also the seller application: a customer applies (status
pending), an administrator approves or rejects it, an approved store can be suspended and
reinstated. One store per user, for life (owner_user_id unique): a rejected applicant edits and
resubmits the same row. Sellers are store owners, never staff (ADR-014 decision 1).

store_status_history is append-only (the runtime role may only SELECT and INSERT it): one row per
submission and per administrator decision, with the status, the reason and the store name as
they were. Each row is the subject of that event's email (notification_service), so a message
is rendered from what was decided, never from the store's later state, and a second rejection
after a resubmission is a new message rather than a duplicate.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.common import MAX_MONEY_RWF, Entity

if TYPE_CHECKING:
    from app.models.commerce import Order
    from app.models.identity import User
    from app.models.media import MediaObject

STORE_STATUSES: tuple[str, ...] = ("pending", "approved", "rejected", "suspended")
_STATUS_LIST = ", ".join(f"'{s}'" for s in STORE_STATUSES)
STORE_NAME_MIN_LENGTH = 2
STORE_NAME_MAX_LENGTH = 120
STORE_SLUG_MAX_LENGTH = 140
STORE_DESCRIPTION_MAX_LENGTH = 2000
STORE_EMAIL_MAX_LENGTH = 254
STORE_DISTRICT_MAX_LENGTH = 120
STORE_SECTOR_MAX_LENGTH = 120
STORE_STREET_MAX_LENGTH = 240
STORE_REASON_MIN_LENGTH = 10
STORE_REASON_MAX_LENGTH = 500
COMMISSION_BPS_MAX = 10_000  # 100.00 %
SLUG_PATTERN = "^[a-z0-9]+(?:-[a-z0-9]+)*$"
CANONICAL_PHONE = r"^\+2507[0-9]{8}$"


class Store(Entity):
    __tablename__ = "stores"
    __table_args__ = (
        UniqueConstraint("owner_user_id", name="uq_stores_owner_user_id"),  # one store per user
        UniqueConstraint("slug", name="uq_stores_slug"),
        # Store names are unique regardless of letter case (ADR-014 phase 1, owner 2026-11-21).
        Index("uq_stores_name_lower", text("lower(name)"), unique=True),
        Index("ix_stores_status_submitted", "status", "submitted_at"),
        CheckConstraint(f"status IN ({_STATUS_LIST})", name="valid_status"),
        CheckConstraint(f"slug ~ '{SLUG_PATTERN}'", name="slug_format"),
        CheckConstraint(
            f"char_length(btrim(name)) >= {STORE_NAME_MIN_LENGTH}", name="name_not_blank"
        ),
        CheckConstraint(
            f"description IS NULL OR char_length(description) <= {STORE_DESCRIPTION_MAX_LENGTH}",
            name="description_length",
        ),
        CheckConstraint("contact_email = lower(contact_email)", name="contact_email_lower"),
        CheckConstraint(f"contact_phone ~ '{CANONICAL_PHONE}'", name="contact_phone_canonical"),
        # The current reason is shown to the seller while rejected or suspended, and cleared when
        # the store returns to pending or approved (the history keeps every reason).
        CheckConstraint(
            "(status IN ('rejected', 'suspended')) = (status_reason IS NOT NULL)",
            name="reason_matches_status",
        ),
        CheckConstraint(
            "commission_rate_bps IS NULL OR "
            f"commission_rate_bps BETWEEN 0 AND {COMMISSION_BPS_MAX}",
            name="commission_rate_range",
        ),
        CheckConstraint(
            "status = 'pending' OR (reviewed_at IS NOT NULL)", name="reviewed_when_decided"
        ),
        CheckConstraint(
            "status NOT IN ('approved', 'suspended') OR approved_at IS NOT NULL",
            name="approved_at_once_approved",
        ),
        CheckConstraint(
            "(logo_media_id IS NULL) = (logo_original_media_id IS NULL)",
            name="logo_media_together",
        ),
        CheckConstraint(
            "(cover_media_id IS NULL) = (cover_original_media_id IS NULL)",
            name="cover_media_together",
        ),
    )

    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(STORE_NAME_MAX_LENGTH), nullable=False)
    slug: Mapped[str] = mapped_column(String(STORE_SLUG_MAX_LENGTH), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    contact_email: Mapped[str] = mapped_column(String(STORE_EMAIL_MAX_LENGTH), nullable=False)
    contact_phone: Mapped[str] = mapped_column(String(13), nullable=False)
    district: Mapped[str] = mapped_column(String(STORE_DISTRICT_MAX_LENGTH), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(STORE_SECTOR_MAX_LENGTH))
    street_address: Mapped[str | None] = mapped_column(String(STORE_STREET_MAX_LENGTH))
    logo_media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_objects.id", ondelete="RESTRICT"), unique=True
    )
    logo_original_media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_objects.id", ondelete="RESTRICT"), unique=True
    )
    cover_media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_objects.id", ondelete="RESTRICT"), unique=True
    )
    cover_original_media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_objects.id", ondelete="RESTRICT"), unique=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    status_reason: Mapped[str | None] = mapped_column(String(STORE_REASON_MAX_LENGTH))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # The first approval; kept through suspension and reinstatement.
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # NULL inherits the platform default (setting marketplace.default_commission_bps).
    commission_rate_bps: Mapped[int | None] = mapped_column(Integer)

    logo_media: Mapped[MediaObject | None] = relationship(
        foreign_keys=[logo_media_id], lazy="selectin"
    )
    cover_media: Mapped[MediaObject | None] = relationship(
        foreign_keys=[cover_media_id], lazy="selectin"
    )
    owner: Mapped[User] = relationship(foreign_keys=[owner_user_id])
    reviewed_by: Mapped[User | None] = relationship(foreign_keys=[reviewed_by_user_id])
    history: Mapped[list[StoreStatusHistory]] = relationship(
        back_populates="store", order_by="StoreStatusHistory.created_at"
    )


class StoreStatusHistory(Entity):
    __tablename__ = "store_status_history"
    __table_args__ = (
        CheckConstraint(f"status IN ({_STATUS_LIST})", name="valid_status"),
        Index("ix_store_status_history_store_created", "store_id", "created_at"),
    )

    store_id: Mapped[UUID] = mapped_column(
        ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(STORE_REASON_MAX_LENGTH))
    # The store's name when the event happened, for the email about it.
    store_name: Mapped[str] = mapped_column(String(STORE_NAME_MAX_LENGTH), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    store: Mapped[Store] = relationship(back_populates="history")
    actor: Mapped[User | None] = relationship()


# ---- seller orders (ADR-014 phase 3, owner decisions 2026-11-21) ---------------------------
SELLER_ORDER_STATUSES: tuple[str, ...] = (
    "pending",
    "confirmed",
    "processing",
    "dispatched",
    "delivered",
    "cancelled",
)
_SELLER_ORDER_STATUS_LIST = ", ".join(f"'{s}'" for s in SELLER_ORDER_STATUSES)
SELLER_ORDER_REASON_MAX_LENGTH = 500


class SellerOrder(Entity):
    """One store's part of a parent order: its lines (order_items with this order_id and
    store_id, enforced by a composite foreign key), its own fulfilment status, and the money
    snapshots taken at checkout. The seller moves the status; the parent order's status is
    derived from its seller orders (seller_order_service). Amounts are whole RWF:
    merchandise_total = subtotal - discount_total (the store's share of the order discount,
    the sum of its lines' existing allocation), commission on merchandise_total at the rate
    snapshot, seller_net_amount = merchandise_total - commission_amount. Delivery fees are the
    platform's and never part of a seller order."""

    __tablename__ = "seller_orders"
    __table_args__ = (
        UniqueConstraint("order_id", "store_id", name="order_store"),
        CheckConstraint(f"status IN ({_SELLER_ORDER_STATUS_LIST})", name="valid_status"),
        CheckConstraint(
            "subtotal >= 0 AND discount_total >= 0 AND commission_amount >= 0 "
            "AND seller_net_amount >= 0",
            name="amounts_nonnegative",
        ),
        CheckConstraint(f"subtotal <= {MAX_MONEY_RWF}", name="amounts_within_cap"),
        CheckConstraint(
            "merchandise_total = subtotal - discount_total", name="merchandise_is_net_of_discount"
        ),
        CheckConstraint(
            "commission_amount + seller_net_amount = merchandise_total",
            name="commission_and_net_make_merchandise",
        ),
        CheckConstraint("commission_rate_bps BETWEEN 0 AND 10000", name="commission_rate_in_range"),
        Index("ix_seller_orders_store_status_created", "store_id", "status", "created_at"),
    )

    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    store_id: Mapped[UUID] = mapped_column(
        ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False
    )
    store_name_snapshot: Mapped[str] = mapped_column(String(STORE_NAME_MAX_LENGTH), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    subtotal: Mapped[int] = mapped_column(BigInteger, nullable=False)
    discount_total: Mapped[int] = mapped_column(BigInteger, nullable=False)
    merchandise_total: Mapped[int] = mapped_column(BigInteger, nullable=False)
    commission_rate_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    commission_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    seller_net_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    order: Mapped[Order] = relationship(back_populates="seller_orders")
    store: Mapped[Store] = relationship()
    history: Mapped[list[SellerOrderStatusHistory]] = relationship(
        back_populates="seller_order",
        cascade="save-update, merge",
        order_by="SellerOrderStatusHistory.created_at",
    )


class SellerOrderStatusHistory(Entity):
    """Append-only (the runtime role may only SELECT and INSERT it)."""

    __tablename__ = "seller_order_status_history"
    __table_args__ = (
        CheckConstraint(f"status IN ({_SELLER_ORDER_STATUS_LIST})", name="valid_status"),
        Index("ix_seller_order_status_history_order_created", "seller_order_id", "created_at"),
    )

    seller_order_id: Mapped[UUID] = mapped_column(
        ForeignKey("seller_orders.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reason: Mapped[str | None] = mapped_column(String(SELLER_ORDER_REASON_MAX_LENGTH))

    seller_order: Mapped[SellerOrder] = relationship(back_populates="history")
