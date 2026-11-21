"""Promotions and discounts (module 13; plan §5, RE-026 B3, B5; ADR-007).

discounts: value is replaced by percent_off (whole percent, 1-100) or amount_off (whole RWF),
exactly the one matching kind; applies_to ('all' | 'targets'), min_subtotal, max_discount,
usage_limit_total and usage_limit_per_customer are added; status loses 'expired'; codes must be
upper-case (the unique constraint is then case-insensitive in effect); rules is dropped.
discount_targets: a target is exactly one of category_id, brand_id, product_id; variant_id is
dropped. discount_redemptions: customer_phone (canonical), status ('active' | 'released'),
released_at and release_reason ('cancelled' | 'expired'), with partial indexes on active rows.
carts gains discount_id (ON DELETE SET NULL) with an index.

Existing data is carried over only when the mapping is unambiguous; otherwise the upgrade stops,
naming the reason, and changes nothing (the whole Alembic run is one transaction). It refuses:
- a discount with a NULL code, a code that is not letters, digits, '-' or '_' once upper-cased,
  or two codes equal ignoring case;
- a value with a fraction, a percentage outside 1-100, or a status of 'expired';
- rules other than '{}' (their meaning cannot be read safely);
- a target on a variant (variant targets are not supported);
- any existing redemption (no canonical phone can be derived without guessing).
A legacy discount with targets becomes applies_to = 'targets', otherwise 'all'.

Downgrade restores the previous columns (value from percent_off or amount_off, rules '{}') and
refuses if a category or brand target exists, which the old schema cannot hold. It drops the
redemption status, phone and release columns and carts.discount_id.

Revision ID: d2f7a9c4e8b1
Revises: b6f1d3a9c8e4
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d2f7a9c4e8b1"
down_revision: str | Sequence[str] | None = "b6f1d3a9c8e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MAX = 999_999_999_999  # ADR-007, as app.models.common.MAX_MONEY_RWF
CODE_PATTERN = "^[A-Z0-9][A-Z0-9_-]*$"
PHONE_PATTERN = r"^\+2507[0-9]{8}$"


def _count(sql: str) -> int:
    return int(op.get_bind().execute(sa.text(sql)).scalar() or 0)


def _refuse(message: str) -> None:
    raise RuntimeError(f"Migration d2f7a9c4e8b1 stopped, nothing was changed: {message}")


def _check_existing_data() -> None:
    checks = (
        ("SELECT count(*) FROM discounts WHERE code IS NULL", "a discount has no code."),
        (
            f"SELECT count(*) FROM discounts WHERE upper(btrim(code)) !~ '{CODE_PATTERN}'",
            "a discount code is not letters, digits, '-' or '_'.",
        ),
        (
            "SELECT count(*) FROM (SELECT upper(btrim(code)) FROM discounts "
            "GROUP BY upper(btrim(code)) HAVING count(*) > 1) AS duplicate",
            "two discount codes differ only in letter case or spaces.",
        ),
        (
            "SELECT count(*) FROM discounts WHERE value <> trunc(value)",
            "a discount value has a fraction; percentages and amounts are whole numbers.",
        ),
        (
            "SELECT count(*) FROM discounts WHERE kind = 'percent' AND NOT value BETWEEN 1 AND 100",
            "a percentage discount is outside 1-100.",
        ),
        (
            "SELECT count(*) FROM discounts WHERE status = 'expired'",
            "a discount has status 'expired'; set it to 'disabled' or 'active' first.",
        ),
        (
            "SELECT count(*) FROM discounts WHERE rules <> '{}'::jsonb",
            "discounts.rules holds data; move it before dropping the column.",
        ),
        (
            "SELECT count(*) FROM discount_targets WHERE variant_id IS NOT NULL",
            "a discount targets a variant; variant targets are not supported.",
        ),
        (
            "SELECT count(*) FROM discount_redemptions",
            "discount redemptions exist; their customer phone cannot be derived safely.",
        ),
    )
    for sql, message in checks:
        if _count(sql):
            _refuse(message)


def upgrade() -> None:
    _check_existing_data()

    # ---- discounts ------------------------------------------------------------------------
    op.add_column("discounts", sa.Column("percent_off", sa.Integer(), nullable=True))
    op.add_column("discounts", sa.Column("amount_off", sa.BigInteger(), nullable=True))
    op.add_column(
        "discounts",
        sa.Column("applies_to", sa.String(length=12), server_default="all", nullable=False),
    )
    op.add_column(
        "discounts",
        sa.Column("min_subtotal", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.add_column("discounts", sa.Column("max_discount", sa.BigInteger(), nullable=True))
    op.add_column("discounts", sa.Column("usage_limit_total", sa.Integer(), nullable=True))
    op.add_column("discounts", sa.Column("usage_limit_per_customer", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE discounts SET code = upper(btrim(code)), "
        "percent_off = CASE WHEN kind = 'percent' THEN value::integer END, "
        "amount_off = CASE WHEN kind = 'fixed' THEN value::bigint END, "
        "applies_to = CASE WHEN EXISTS (SELECT 1 FROM discount_targets t "
        "WHERE t.discount_id = discounts.id) THEN 'targets' ELSE 'all' END"
    )
    op.alter_column("discounts", "code", existing_type=sa.String(length=80), nullable=False)
    for name in ("percent_in_range", "value_positive", "valid_status"):
        op.drop_constraint(op.f(f"ck_discounts_{name}"), "discounts", type_="check")
    op.drop_column("discounts", "value")
    op.drop_column("discounts", "rules")
    checks = {
        "code_upper_case": f"code = upper(code) AND code ~ '{CODE_PATTERN}'",
        "amount_matches_kind": (
            "(kind = 'percent' AND percent_off BETWEEN 1 AND 100 AND amount_off IS NULL) OR "
            f"(kind = 'fixed' AND amount_off BETWEEN 1 AND {MAX} AND percent_off IS NULL)"
        ),
        "valid_applies_to": "applies_to IN ('all', 'targets')",
        "valid_status": "status IN ('draft', 'active', 'disabled')",
        "min_subtotal_range": f"min_subtotal BETWEEN 0 AND {MAX}",
        "max_discount_range": f"max_discount IS NULL OR max_discount BETWEEN 1 AND {MAX}",
        "usage_limit_total_positive": "usage_limit_total IS NULL OR usage_limit_total >= 1",
        "usage_limit_per_customer_positive": (
            "usage_limit_per_customer IS NULL OR usage_limit_per_customer >= 1"
        ),
    }
    for name, condition in checks.items():
        op.create_check_constraint(op.f(f"ck_discounts_{name}"), "discounts", condition)

    # ---- discount_targets -------------------------------------------------------------------
    op.drop_constraint(op.f("ck_discount_targets_one_target"), "discount_targets", type_="check")
    op.drop_constraint("discount_variant_target", "discount_targets", type_="unique")
    op.drop_index("ix_discount_targets_variant", table_name="discount_targets")
    op.drop_constraint(
        op.f("fk_discount_targets_variant_id_product_variants"),
        "discount_targets",
        type_="foreignkey",
    )
    op.drop_column("discount_targets", "variant_id")
    op.add_column("discount_targets", sa.Column("category_id", sa.Uuid(), nullable=True))
    op.add_column("discount_targets", sa.Column("brand_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_discount_targets_category_id_categories"),
        "discount_targets",
        "categories",
        ["category_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_discount_targets_brand_id_brands"),
        "discount_targets",
        "brands",
        ["brand_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_discount_targets_exactly_one_target"),
        "discount_targets",
        "(category_id IS NOT NULL)::int + (brand_id IS NOT NULL)::int "
        "+ (product_id IS NOT NULL)::int = 1",
    )
    op.create_unique_constraint(
        "discount_category_target", "discount_targets", ["discount_id", "category_id"]
    )
    op.create_unique_constraint(
        "discount_brand_target", "discount_targets", ["discount_id", "brand_id"]
    )
    op.create_index("ix_discount_targets_category", "discount_targets", ["category_id"])
    op.create_index("ix_discount_targets_brand", "discount_targets", ["brand_id"])

    # ---- discount_redemptions ---------------------------------------------------------------
    op.add_column(
        "discount_redemptions",
        sa.Column("customer_phone", sa.String(length=20), nullable=False),
    )
    op.add_column(
        "discount_redemptions",
        sa.Column("status", sa.String(length=12), server_default="active", nullable=False),
    )
    op.add_column(
        "discount_redemptions",
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "discount_redemptions",
        sa.Column("release_reason", sa.String(length=16), nullable=True),
    )
    redemption_checks = {
        "phone_canonical": f"customer_phone ~ '{PHONE_PATTERN}'",
        "valid_status": "status IN ('active', 'released')",
        "release_consistent": (
            "(status = 'active' AND released_at IS NULL AND release_reason IS NULL) OR "
            "(status = 'released' AND released_at IS NOT NULL "
            "AND release_reason IN ('cancelled', 'expired'))"
        ),
    }
    for name, condition in redemption_checks.items():
        op.create_check_constraint(
            op.f(f"ck_discount_redemptions_{name}"), "discount_redemptions", condition
        )
    op.create_index(
        "ix_discount_redemptions_active_discount",
        "discount_redemptions",
        ["discount_id"],
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_discount_redemptions_active_phone",
        "discount_redemptions",
        ["customer_phone"],
        postgresql_where=sa.text("status = 'active'"),
    )

    # ---- carts ------------------------------------------------------------------------------
    op.add_column("carts", sa.Column("discount_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_carts_discount_id_discounts"),
        "carts",
        "discounts",
        ["discount_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_carts_discount_id"), "carts", ["discount_id"])


def downgrade() -> None:
    if _count(
        "SELECT count(*) FROM discount_targets "
        "WHERE category_id IS NOT NULL OR brand_id IS NOT NULL"
    ):
        raise RuntimeError(
            "Downgrade from d2f7a9c4e8b1 stopped, nothing was changed: category or brand "
            "discount targets exist, which the previous schema cannot hold."
        )

    op.drop_index(op.f("ix_carts_discount_id"), table_name="carts")
    op.drop_constraint(op.f("fk_carts_discount_id_discounts"), "carts", type_="foreignkey")
    op.drop_column("carts", "discount_id")

    op.drop_index("ix_discount_redemptions_active_phone", table_name="discount_redemptions")
    op.drop_index("ix_discount_redemptions_active_discount", table_name="discount_redemptions")
    for name in ("release_consistent", "valid_status", "phone_canonical"):
        op.drop_constraint(
            op.f(f"ck_discount_redemptions_{name}"), "discount_redemptions", type_="check"
        )
    for column in ("release_reason", "released_at", "status", "customer_phone"):
        op.drop_column("discount_redemptions", column)

    op.drop_index("ix_discount_targets_brand", table_name="discount_targets")
    op.drop_index("ix_discount_targets_category", table_name="discount_targets")
    op.drop_constraint("discount_brand_target", "discount_targets", type_="unique")
    op.drop_constraint("discount_category_target", "discount_targets", type_="unique")
    op.drop_constraint(
        op.f("ck_discount_targets_exactly_one_target"), "discount_targets", type_="check"
    )
    op.drop_constraint(
        op.f("fk_discount_targets_brand_id_brands"), "discount_targets", type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_discount_targets_category_id_categories"), "discount_targets", type_="foreignkey"
    )
    op.drop_column("discount_targets", "brand_id")
    op.drop_column("discount_targets", "category_id")
    op.add_column("discount_targets", sa.Column("variant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_discount_targets_variant_id_product_variants"),
        "discount_targets",
        "product_variants",
        ["variant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_discount_targets_variant", "discount_targets", ["variant_id"])
    op.create_unique_constraint(
        "discount_variant_target", "discount_targets", ["discount_id", "variant_id"]
    )
    op.create_check_constraint(
        op.f("ck_discount_targets_one_target"),
        "discount_targets",
        "(product_id IS NOT NULL) <> (variant_id IS NOT NULL)",
    )

    op.add_column(
        "discounts",
        sa.Column(
            "rules", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
    )
    op.add_column("discounts", sa.Column("value", sa.Numeric(precision=14, scale=2), nullable=True))
    op.execute("UPDATE discounts SET value = coalesce(percent_off::numeric, amount_off::numeric)")
    op.alter_column("discounts", "value", nullable=False)
    for name in (
        "usage_limit_per_customer_positive",
        "usage_limit_total_positive",
        "max_discount_range",
        "min_subtotal_range",
        "valid_status",
        "valid_applies_to",
        "amount_matches_kind",
        "code_upper_case",
    ):
        op.drop_constraint(op.f(f"ck_discounts_{name}"), "discounts", type_="check")
    for column in (
        "usage_limit_per_customer",
        "usage_limit_total",
        "max_discount",
        "min_subtotal",
        "applies_to",
        "amount_off",
        "percent_off",
    ):
        op.drop_column("discounts", column)
    op.alter_column("discounts", "code", existing_type=sa.String(length=80), nullable=True)
    op.create_check_constraint(
        op.f("ck_discounts_valid_status"),
        "discounts",
        "status IN ('draft', 'active', 'disabled', 'expired')",
    )
    op.create_check_constraint(op.f("ck_discounts_value_positive"), "discounts", "value > 0")
    op.create_check_constraint(
        op.f("ck_discounts_percent_in_range"), "discounts", "kind <> 'percent' OR value <= 100"
    )
