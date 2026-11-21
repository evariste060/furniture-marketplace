from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import MAX_MONEY_RWF, Entity
from app.models.operations import CANONICAL_PHONE_PATTERN

if TYPE_CHECKING:
    from app.models.identity import User


class Cart(Entity):
    __tablename__ = "carts"
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL) <> (guest_token_hash IS NOT NULL)", name="one_owner"
        ),
        CheckConstraint("status IN ('active', 'converted', 'abandoned')", name="valid_status"),
        Index(
            "uq_carts_active_user",
            "user_id",
            unique=True,
            postgresql_where="status = 'active' AND user_id IS NOT NULL",
        ),
        Index(
            "uq_carts_active_guest",
            "guest_token_hash",
            unique=True,
            postgresql_where="status = 'active' AND guest_token_hash IS NOT NULL",
        ),
    )

    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    guest_token_hash: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The promotion code applied to the cart (module 13): one code per cart, re-checked and
    # re-priced on every read; nothing is reserved until checkout.
    discount_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("discounts.id", ondelete="SET NULL"), index=True
    )

    user: Mapped[User | None] = relationship(back_populates="carts")
    items: Mapped[list[CartItem]] = relationship(
        back_populates="cart", cascade="all, delete-orphan"
    )


class CartItem(Entity):
    __tablename__ = "cart_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("price_at_add >= 0", name="price_at_add_nonnegative"),
        UniqueConstraint("cart_id", "variant_id", name="cart_variant"),
    )

    cart_id: Mapped[UUID] = mapped_column(
        ForeignKey("carts.id", ondelete="CASCADE"), nullable=False
    )
    variant_id: Mapped[UUID] = mapped_column(
        ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    # The variant's price when the line was added, topped up or accepted (frontend phase 4,
    # 2026-10-27): only to tell the customer about a price change. Null for older lines.
    price_at_add: Mapped[int | None] = mapped_column(BigInteger)

    cart: Mapped[Cart] = relationship(back_populates="items")


class Order(Entity):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("order_number", name="order_number"),
        UniqueConstraint("checkout_idempotency_key", name="checkout_idempotency_key"),
        CheckConstraint(
            "status IN ('received', 'confirmed', 'processing', "
            "'dispatched', 'delivered', 'cancelled')",
            name="valid_status",
        ),
        CheckConstraint("currency_code = 'RWF'", name="currency_rwf"),
        CheckConstraint(
            "subtotal >= 0 AND discount_total >= 0 AND delivery_fee >= 0 "
            "AND tax_total >= 0 AND total >= 0",
            name="amounts_nonnegative",
        ),
        CheckConstraint(
            f"subtotal <= {MAX_MONEY_RWF} AND discount_total <= {MAX_MONEY_RWF} "
            f"AND delivery_fee <= {MAX_MONEY_RWF} AND tax_total <= {MAX_MONEY_RWF} "
            f"AND total <= {MAX_MONEY_RWF}",
            name="amounts_within_cap",
        ),
        CheckConstraint(
            "checkout_request_hash IS NULL OR checkout_request_hash ~ '^[0-9a-f]{64}$'",
            name="checkout_request_hash_hex",
        ),
        Index("ix_orders_customer_created", "user_id", "created_at"),
        Index("ix_orders_status_created", "status", "created_at"),
        Index("ix_orders_fulfilment_assignee_user_id", "fulfilment_assignee_user_id"),
    )

    order_number: Mapped[str] = mapped_column(String(40), nullable=False)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    checkout_idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    # SHA-256 of the normalised checkout request (module 14): a retry with the same key replays
    # the order only when it asks for the same thing. NULL for orders not made by checkout.
    checkout_request_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="received", server_default="received"
    )
    currency_code: Mapped[str] = mapped_column(
        String(3), nullable=False, default="RWF", server_default="RWF"
    )
    subtotal: Mapped[int] = mapped_column(BigInteger, nullable=False)
    discount_total: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    delivery_fee: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    tax_total: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    total: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_treatment: Mapped[str | None] = mapped_column(String(80))
    tax_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    discount_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("discounts.id", ondelete="SET NULL")
    )
    discount_code_snapshot: Mapped[str | None] = mapped_column(String(80))
    discount_name_snapshot: Mapped[str | None] = mapped_column(String(160))
    discount_rules_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    delivery_zone_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("delivery_zones.id", ondelete="SET NULL")
    )
    fulfilment_assignee_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    delivery_method_snapshot: Mapped[str | None] = mapped_column(String(80))
    delivery_zone_snapshot: Mapped[str | None] = mapped_column(String(160))
    recipient_name: Mapped[str] = mapped_column(String(180), nullable=False)
    recipient_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    delivery_address_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    customer_email_snapshot: Mapped[str | None] = mapped_column(String(320))
    customer_note: Mapped[str | None] = mapped_column(String(1000))

    user: Mapped[User | None] = relationship(back_populates="orders", foreign_keys=[user_id])
    fulfilment_assignee: Mapped[User | None] = relationship(
        foreign_keys=[fulfilment_assignee_user_id]
    )
    items: Mapped[list[OrderItem]] = relationship(
        back_populates="order", cascade="save-update, merge"
    )
    status_history: Mapped[list[OrderStatusHistory]] = relationship(
        back_populates="order",
        cascade="save-update, merge",
        order_by="OrderStatusHistory.created_at",
    )
    payment_attempts: Mapped[list[PaymentAttempt]] = relationship(back_populates="order")


class OrderItem(Entity):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint(
            "unit_price >= 0 AND line_subtotal >= 0 AND discount_amount >= 0 "
            "AND tax_amount >= 0 AND line_total >= 0",
            name="amounts_nonnegative",
        ),
        CheckConstraint(
            f"unit_price <= {MAX_MONEY_RWF} AND line_subtotal <= {MAX_MONEY_RWF} "
            f"AND discount_amount <= {MAX_MONEY_RWF} AND tax_amount <= {MAX_MONEY_RWF} "
            f"AND line_total <= {MAX_MONEY_RWF}",
            name="amounts_within_cap",
        ),
        Index("ix_order_items_variant", "variant_id"),
    )

    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[UUID | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    variant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("product_variants.id", ondelete="SET NULL")
    )
    sku_snapshot: Mapped[str] = mapped_column(String(80), nullable=False)
    product_name_snapshot: Mapped[str] = mapped_column(String(240), nullable=False)
    brand_model_snapshot: Mapped[str | None] = mapped_column(String(320))
    variant_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    specifications_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    warranty_snapshot: Mapped[str | None] = mapped_column(Text)
    image_snapshot: Mapped[str | None] = mapped_column(String(1024))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    line_subtotal: Mapped[int] = mapped_column(BigInteger, nullable=False)
    discount_amount: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    tax_amount: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    tax_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    line_total: Mapped[int] = mapped_column(BigInteger, nullable=False)

    order: Mapped[Order] = relationship(back_populates="items")


class OrderStatusHistory(Entity):
    __tablename__ = "order_status_history"
    __table_args__ = (
        CheckConstraint(
            "status IN ('received', 'confirmed', 'processing', "
            "'dispatched', 'delivered', 'cancelled')",
            name="valid_status",
        ),
        Index("ix_order_status_history_order_created", "order_id", "created_at"),
    )

    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reason: Mapped[str | None] = mapped_column(String(500))

    order: Mapped[Order] = relationship(back_populates="status_history")


class PaymentAttempt(Entity):
    __tablename__ = "payment_attempts"
    __table_args__ = (
        CheckConstraint(
            "method IN ('mtn_momo', 'airtel_money', 'card', 'cash_on_delivery')",
            name="valid_method",
        ),
        CheckConstraint(
            "status IN ('created', 'pending', 'succeeded', 'failed', "
            "'cancelled', 'expired', 'refunded', 'partially_refunded')",
            name="valid_status",
        ),
        CheckConstraint("amount >= 0 AND currency_code = 'RWF'", name="amount_currency_valid"),
        CheckConstraint(f"amount <= {MAX_MONEY_RWF}", name="amount_within_cap"),
        UniqueConstraint("provider", "provider_reference", name="provider_reference"),
        Index("ix_payment_attempts_order_created", "order_id", "created_at"),
    )

    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    method: Mapped[str] = mapped_column(String(24), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(80))
    provider_reference: Mapped[str | None] = mapped_column(String(180))
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency_code: Mapped[str] = mapped_column(
        String(3), nullable=False, default="RWF", server_default="RWF"
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="created", server_default="created"
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    order: Mapped[Order] = relationship(back_populates="payment_attempts")
    events: Mapped[list[PaymentEvent]] = relationship(
        back_populates="attempt", cascade="save-update, merge"
    )


class PaymentEvent(Entity):
    __tablename__ = "payment_events"
    __table_args__ = (
        UniqueConstraint("provider", "event_key", name="provider_event_key"),
        CheckConstraint(
            "verification_status IN ('received', 'verified', 'rejected')",
            name="verification_status_valid",
        ),
        CheckConstraint(
            "processing_status IN ('pending', 'processed', 'duplicate', "
            "'needs_reconciliation', 'rejected')",
            name="processing_status_valid",
        ),
        Index("ix_payment_events_attempt_received", "attempt_id", "created_at"),
    )

    attempt_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("payment_attempts.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    event_key: Mapped[str] = mapped_column(String(200), nullable=False)
    payload_digest: Mapped[str | None] = mapped_column(String(128))
    verification_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="received", server_default="received"
    )
    processing_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_summary: Mapped[str | None] = mapped_column(String(500))
    # Sanitised provider facts (module 15): allow-listed fields only; phone numbers masked; never
    # card data, secrets or the raw payload (payload_digest keeps its SHA-256).
    payload_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    attempt: Mapped[PaymentAttempt | None] = relationship(back_populates="events")


# Module 16 (§7 Q19): INV-YYYY-NNNNNN, gapless per year.
INVOICE_NUMBER_PATTERN = r"^INV-[0-9]{4}-[0-9]{6}$"
MAX_INVOICE_SEQUENCE = 999_999  # NNNNNN


class Invoice(Entity):
    """An issued invoice (module 16). Written once, in the transaction that records the payment
    success (or the delivery of a cash-on-delivery order); never updated or deleted. snapshot is
    the document as issued; downloads render it, never live order data."""

    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("order_id", name="order_id"),
        UniqueConstraint("invoice_number", name="invoice_number"),
        CheckConstraint(f"invoice_number ~ '{INVOICE_NUMBER_PATTERN}'", name="number_format"),
        CheckConstraint(
            f"total >= 0 AND total <= {MAX_MONEY_RWF} AND vat_amount >= 0 AND vat_amount <= total",
            name="amounts_valid",
        ),
    )

    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    invoice_number: Mapped[str] = mapped_column(String(20), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total: Mapped[int] = mapped_column(BigInteger, nullable=False)
    vat_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class InvoiceCounter(Base):
    """The last invoice number issued in a year (module 16). Incremented in the issuing
    transaction under its row lock, so a rolled-back issuance gives its number back and
    committed numbers are consecutive and never reused."""

    __tablename__ = "invoice_counters"
    __table_args__ = (
        CheckConstraint("year BETWEEN 2000 AND 9999", name="year_valid"),
        CheckConstraint(
            f"last_number >= 1 AND last_number <= {MAX_INVOICE_SEQUENCE}", name="last_number_valid"
        ),
    )

    year: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    last_number: Mapped[int] = mapped_column(Integer, nullable=False)


# Seller application events (ADR-014 phase 1); the subject is a store_status_history row.
STORE_STATUS_EVENTS = (
    "store_application_received",
    "store_approved",
    "store_rejected",
    "store_suspended",
    "store_reinstated",
)
# Module 17 (§7 Q22): order notifications.
# Order status messages to the customer (module 17).
ORDER_STATUS_EVENTS = ("confirmed", "dispatched", "delivered", "cancelled")
# Every message the outbox carries: order status messages, order placed (to the customer and the
# staff alert list), payment received, welcome, quote request and review acknowledgements.
NOTIFICATION_EVENTS = (
    *ORDER_STATUS_EVENTS,
    "received",
    "staff_new_order",
    "payment_succeeded",
    "welcome",
    "quote_received",
    "review_thanks",
    "support_reply",
    "service_received",  # a service request with an email (ADR-013)
    # Seller applications and decisions (ADR-014 phase 1), to the owner's verified email.
    *STORE_STATUS_EVENTS,
)
NOTIFICATION_SUBJECTS = ("order", "user", "quote", "review", "support", "service", "store_status")
MAX_NOTIFICATION_ATTEMPTS = 3
EMAIL_PATTERN = r"^[^@[:space:]]+@[^@[:space:]]+$"


class NotificationLog(Entity):
    """One message (module 17 outbox), recorded in the transaction of the business change it
    reports (an order event, a registration, a quote request, a review) and sent after it commits.
    Never deleted. subject_type/subject_id name the record the message is rendered from at send
    time (no message text is stored); order_id is set exactly for order messages. dedupe_key is
    unique: one message per event, subject, channel and (staff alerts) recipient.

    status: 'pending' until an attempt finishes; 'sent' once the provider accepted it; 'failed'
    after a failed attempt (retried at next_attempt_at while attempts < 3, final when
    next_attempt_at is NULL). claimed_until is the lease of the worker sending it now: a row is
    never claimed by a second worker before the lease ends."""

    __tablename__ = "notification_logs"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_notification_logs_dedupe_key"),
        CheckConstraint(
            "event IN (" + ", ".join(f"'{e}'" for e in NOTIFICATION_EVENTS) + ")",
            name="valid_event",
        ),
        CheckConstraint(
            "subject_type IN (" + ", ".join(f"'{s}'" for s in NOTIFICATION_SUBJECTS) + ")",
            name="valid_subject_type",
        ),
        CheckConstraint(
            "(subject_type = 'order') = (order_id IS NOT NULL) "
            "AND (order_id IS NULL OR subject_id = order_id)",
            name="order_subject_matches",
        ),
        CheckConstraint("channel IN ('sms', 'email')", name="valid_channel"),
        CheckConstraint("status IN ('pending', 'sent', 'failed')", name="valid_status"),
        CheckConstraint(
            f"attempts >= 0 AND attempts <= {MAX_NOTIFICATION_ATTEMPTS}", name="attempts_bounded"
        ),
        CheckConstraint(
            f"(channel = 'sms' AND recipient ~ '{CANONICAL_PHONE_PATTERN}') "
            f"OR (channel = 'email' AND recipient ~ '{EMAIL_PATTERN}')",
            name="recipient_matches_channel",
        ),
        CheckConstraint("(status = 'sent') = (sent_at IS NOT NULL)", name="sent_at_when_sent"),
        CheckConstraint(
            "status <> 'sent' OR (provider_message_id IS NOT NULL AND next_attempt_at IS NULL "
            "AND claimed_until IS NULL)",
            name="sent_is_final",
        ),
        CheckConstraint(
            "status <> 'pending' OR next_attempt_at IS NOT NULL", name="pending_is_scheduled"
        ),
        Index(
            "ix_notification_logs_due",
            "next_attempt_at",
            postgresql_where="status IN ('pending', 'failed') AND next_attempt_at IS NOT NULL",
        ),
        Index("ix_notification_logs_created", "created_at"),
        Index("ix_notification_logs_status_created", "status", "created_at"),
    )

    order_id: Mapped[UUID | None] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"))
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_id: Mapped[UUID] = mapped_column(nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(400), nullable=False)
    event: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(8), nullable=False)
    recipient: Mapped[str] = mapped_column(String(320), nullable=False)
    status: Mapped[str] = mapped_column(
        String(8), nullable=False, default="pending", server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    last_error: Mapped[str | None] = mapped_column(String(200))  # sanitised code only
    provider_message_id: Mapped[str | None] = mapped_column(String(128))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
