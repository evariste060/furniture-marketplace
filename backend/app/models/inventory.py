from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.common import Entity

if TYPE_CHECKING:
    from app.models.catalog import ProductVariant


class InventoryBalance(Entity):
    __tablename__ = "inventory_balances"
    __table_args__ = (
        CheckConstraint("on_hand >= 0", name="on_hand_nonnegative"),
        CheckConstraint(
            "unavailable_quantity >= 0 AND unavailable_quantity <= on_hand",
            name="unavailable_in_range",
        ),
    )

    variant_id: Mapped[UUID] = mapped_column(
        ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    on_hand: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    unavailable_quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    variant: Mapped[ProductVariant] = relationship(back_populates="inventory")


class StockMovement(Entity):
    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint("quantity_delta <> 0", name="movement_nonzero"),
        CheckConstraint(
            "reason IN ('receipt', 'dispatch', 'adjustment', 'inspected_return')",
            name="valid_reason",
        ),
        UniqueConstraint("source_key", name="stock_movement_source_key"),
        Index("ix_stock_movements_variant_created", "variant_id", "created_at"),
    )

    variant_id: Mapped[UUID] = mapped_column(
        ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    quantity_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    source_key: Mapped[str] = mapped_column(String(160), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))


class StockReservation(Entity):
    """Temporary allocation of available stock to an order (ADR-002 lifecycle, 2026-10-22).

    Allowed transitions (also enforced by a database trigger): active -> committed | released |
    expired, committed -> fulfilled. Rows are never deleted.
    """

    __tablename__ = "stock_reservations"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint(
            "status IN ('active', 'committed', 'released', 'expired', 'fulfilled')",
            name="valid_status",
        ),
        CheckConstraint(
            "(status <> 'committed' OR committed_at IS NOT NULL) "
            "AND (status NOT IN ('released', 'expired') OR released_at IS NOT NULL) "
            "AND (status <> 'fulfilled' OR fulfilled_at IS NOT NULL)",
            name="status_timestamps_consistent",
        ),
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
        UniqueConstraint("order_id", "variant_id", name="reservation_order_variant"),
        UniqueConstraint("idempotency_key", name="reservation_idempotency_key"),
        Index("ix_stock_reservations_variant_status", "variant_id", "status"),
        Index("ix_stock_reservations_expiry", "expires_at", postgresql_where="status = 'active'"),
    )

    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    variant_id: Mapped[UUID] = mapped_column(
        ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    release_reason: Mapped[str | None] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
