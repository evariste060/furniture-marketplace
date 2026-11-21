from __future__ import annotations

from datetime import datetime
from typing import Any
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
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import MAX_MONEY_RWF, Entity

# RE-026 B1: deliveries are made only in these three Kigali districts.
DELIVERY_DISTRICTS: tuple[str, ...] = ("Gasabo", "Kicukiro", "Nyarugenge")
_DISTRICT_LIST = ", ".join(f"'{d}'" for d in DELIVERY_DISTRICTS)


class DeliveryZone(Entity):
    """One delivery zone per supported district (module 12; plan §5, RE-026 B1/B5)."""

    __tablename__ = "delivery_zones"
    __table_args__ = (
        UniqueConstraint("code", name="delivery_zone_code"),
        UniqueConstraint("district", name="delivery_zone_district"),
        CheckConstraint(f"district IN ({_DISTRICT_LIST})", name="supported_district"),
    )

    code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    district: Mapped[str] = mapped_column(String(40), nullable=False)
    cod_available: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")


class DeliveryFeeRule(Entity):
    """A zone's flat fee over time. A fee change closes the active rule (is_active false,
    ends_at set) and adds a new one in the same transaction, so history is kept; the partial
    unique index allows at most one active rule per zone."""

    __tablename__ = "delivery_fee_rules"
    __table_args__ = (
        CheckConstraint("fee >= 0", name="fee_nonnegative"),
        CheckConstraint(f"fee <= {MAX_MONEY_RWF}", name="fee_within_cap"),
        CheckConstraint("currency_code = 'RWF'", name="currency_rwf"),
        CheckConstraint(
            "ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at", name="valid_window"
        ),
        Index(
            "uq_delivery_fee_rules_one_active_per_zone",
            "zone_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        Index("ix_delivery_fee_rules_zone_created", "zone_id", "created_at"),
    )

    zone_id: Mapped[UUID] = mapped_column(
        ForeignKey("delivery_zones.id", ondelete="RESTRICT"), nullable=False
    )
    fee: Mapped[int] = mapped_column(BigInteger, nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    currency_code: Mapped[str] = mapped_column(
        String(3), nullable=False, default="RWF", server_default="RWF"
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")


class Setting(Base):
    """Editable configuration values (module 12; module 19 adds keys). Only keys registered in
    app.services.settings_service can be read or written through the API."""

    __tablename__ = "settings"
    __table_args__ = (
        CheckConstraint(r"key ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$'", name="key_format"),
    )

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


# Module 13 (plan §5, RE-026 B3): codes are stored upper-case, so the unique constraint on code
# is case-insensitive in effect; the API upper-cases every code it receives.
DISCOUNT_CODE_PATTERN = "^[A-Z0-9][A-Z0-9_-]*$"
CANONICAL_PHONE_PATTERN = r"^\+2507[0-9]{8}$"  # as users.phone (app.core.identifiers)


class Discount(Entity):
    """A promotion code: a whole percentage (1-100) or a fixed amount off eligible merchandise."""

    __tablename__ = "discounts"
    __table_args__ = (
        UniqueConstraint("code", name="discount_code"),
        CheckConstraint(
            f"code = upper(code) AND code ~ '{DISCOUNT_CODE_PATTERN}'", name="code_upper_case"
        ),
        CheckConstraint("kind IN ('percent', 'fixed')", name="valid_kind"),
        CheckConstraint(
            "(kind = 'percent' AND percent_off BETWEEN 1 AND 100 AND amount_off IS NULL) OR "
            f"(kind = 'fixed' AND amount_off BETWEEN 1 AND {MAX_MONEY_RWF} "
            "AND percent_off IS NULL)",
            name="amount_matches_kind",
        ),
        CheckConstraint("applies_to IN ('all', 'targets')", name="valid_applies_to"),
        CheckConstraint("status IN ('draft', 'active', 'disabled')", name="valid_status"),
        CheckConstraint(
            "ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at", name="valid_window"
        ),
        CheckConstraint(f"min_subtotal BETWEEN 0 AND {MAX_MONEY_RWF}", name="min_subtotal_range"),
        CheckConstraint(
            f"max_discount IS NULL OR max_discount BETWEEN 1 AND {MAX_MONEY_RWF}",
            name="max_discount_range",
        ),
        CheckConstraint(
            "usage_limit_total IS NULL OR usage_limit_total >= 1", name="usage_limit_total_positive"
        ),
        CheckConstraint(
            "usage_limit_per_customer IS NULL OR usage_limit_per_customer >= 1",
            name="usage_limit_per_customer_positive",
        ),
        Index("ix_discounts_status_window", "status", "starts_at", "ends_at"),
    )

    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    percent_off: Mapped[int | None] = mapped_column(Integer)
    amount_off: Mapped[int | None] = mapped_column(BigInteger)
    applies_to: Mapped[str] = mapped_column(
        String(12), nullable=False, default="all", server_default="all"
    )
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="draft", server_default="draft"
    )
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    min_subtotal: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    max_discount: Mapped[int | None] = mapped_column(BigInteger)
    usage_limit_total: Mapped[int | None] = mapped_column(Integer)
    usage_limit_per_customer: Mapped[int | None] = mapped_column(Integer)


class DiscountTarget(Entity):
    """One target of a code with applies_to = 'targets': a category (and its subcategories), a
    brand or a product."""

    __tablename__ = "discount_targets"
    __table_args__ = (
        CheckConstraint(
            "(category_id IS NOT NULL)::int + (brand_id IS NOT NULL)::int "
            "+ (product_id IS NOT NULL)::int = 1",
            name="exactly_one_target",
        ),
        UniqueConstraint("discount_id", "category_id", name="discount_category_target"),
        UniqueConstraint("discount_id", "brand_id", name="discount_brand_target"),
        UniqueConstraint("discount_id", "product_id", name="discount_product_target"),
        Index("ix_discount_targets_category", "category_id"),
        Index("ix_discount_targets_brand", "brand_id"),
        Index("ix_discount_targets_product", "product_id"),
    )

    discount_id: Mapped[UUID] = mapped_column(
        ForeignKey("discounts.id", ondelete="RESTRICT"), nullable=False
    )
    category_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT")
    )
    brand_id: Mapped[UUID | None] = mapped_column(ForeignKey("brands.id", ondelete="RESTRICT"))
    product_id: Mapped[UUID | None] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))


class DiscountRedemption(Entity):
    """One use of a code by one order. Only active redemptions count towards usage limits; a
    cancellation before dispatch or a reservation expiry releases it (RE-026 B3)."""

    __tablename__ = "discount_redemptions"
    __table_args__ = (
        UniqueConstraint("discount_id", "order_id", name="discount_order_redemption"),
        CheckConstraint("amount >= 0", name="amount_nonnegative"),
        CheckConstraint(f"amount <= {MAX_MONEY_RWF}", name="amount_within_cap"),
        CheckConstraint(f"customer_phone ~ '{CANONICAL_PHONE_PATTERN}'", name="phone_canonical"),
        CheckConstraint("status IN ('active', 'released')", name="valid_status"),
        CheckConstraint(
            "(status = 'active' AND released_at IS NULL AND release_reason IS NULL) OR "
            "(status = 'released' AND released_at IS NOT NULL "
            "AND release_reason IN ('cancelled', 'expired'))",
            name="release_consistent",
        ),
        Index("ix_discount_redemptions_user", "user_id"),
        Index(
            "ix_discount_redemptions_active_discount",
            "discount_id",
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "ix_discount_redemptions_active_phone",
            "customer_phone",
            postgresql_where=text("status = 'active'"),
        ),
    )

    discount_id: Mapped[UUID] = mapped_column(
        ForeignKey("discounts.id", ondelete="RESTRICT"), nullable=False
    )
    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    customer_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="active", server_default="active"
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    release_reason: Mapped[str | None] = mapped_column(String(16))


class AuditRecord(Entity):
    __tablename__ = "audit_records"
    __table_args__ = (
        Index("ix_audit_records_entity_created", "entity_type", "entity_id", "created_at"),
        Index("ix_audit_records_actor_created", "actor_user_id", "created_at"),
    )

    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_identifier_snapshot: Mapped[str | None] = mapped_column(String(180))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(80), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(160))
    change_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    note: Mapped[str | None] = mapped_column(Text)
