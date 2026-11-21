"""Money as whole RWF in BIGINT columns (ADR-007).

Converts every Numeric(14, 2) amount column except discounts.value (replaced by typed columns in
the promotions module) to BIGINT and adds a per-table maximum-amount check. The upgrade refuses to
run if any stored amount has a fractional part or exceeds the cap: stored data is never rounded
silently. The downgrade converts back to Numeric(14, 2) without loss.

Revision ID: 528e6436c34e
Revises: e1b7f3c9a5d2
"""

from collections.abc import Sequence

from alembic import op

revision: str = "528e6436c34e"
down_revision: str | Sequence[str] | None = "e1b7f3c9a5d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MAX_MONEY_RWF = 999_999_999_999  # frozen copy of app.models.common.MAX_MONEY_RWF

# table -> (amount columns, cap check name)
MONEY_COLUMNS: dict[str, tuple[tuple[str, ...], str]] = {
    "product_variants": (("price", "compare_at_price"), "amounts_within_cap"),
    "orders": (
        ("subtotal", "discount_total", "delivery_fee", "tax_total", "total"),
        "amounts_within_cap",
    ),
    "order_items": (
        ("unit_price", "line_subtotal", "discount_amount", "tax_amount", "line_total"),
        "amounts_within_cap",
    ),
    "payment_attempts": (("amount",), "amount_within_cap"),
    "delivery_fee_rules": (("fee",), "fee_within_cap"),
    "discount_redemptions": (("amount",), "amount_within_cap"),
}


def _check_convertible() -> None:
    bind = op.get_bind()
    problems = []
    for table, (columns, _) in MONEY_COLUMNS.items():
        for column in columns:
            count = bind.exec_driver_sql(
                f"SELECT count(*) FROM {table} "
                f"WHERE {column} <> trunc({column}) OR {column} > {MAX_MONEY_RWF}"
            ).scalar_one()
            if count:
                problems.append(f"{table}.{column}: {count} row(s)")
    if problems:
        # Counts only: amounts themselves are not printed.
        raise RuntimeError(
            "Cannot convert money to whole RWF: fractional or over-cap amounts in "
            + "; ".join(problems)
            + ". Correct these rows (ADR-007) and run the migration again."
        )


def upgrade() -> None:
    _check_convertible()
    for table, (columns, check) in MONEY_COLUMNS.items():
        for column in columns:
            op.execute(
                f"ALTER TABLE {table} ALTER COLUMN {column} TYPE BIGINT USING {column}::bigint"
            )
        op.create_check_constraint(
            op.f(f"ck_{table}_{check}"),
            table,
            " AND ".join(f"{column} <= {MAX_MONEY_RWF}" for column in columns),
        )


def downgrade() -> None:
    for table, (columns, check) in MONEY_COLUMNS.items():
        op.drop_constraint(op.f(f"ck_{table}_{check}"), table, type_="check")
        for column in columns:
            op.execute(
                f"ALTER TABLE {table} ALTER COLUMN {column} TYPE NUMERIC(14, 2) "
                f"USING {column}::numeric(14, 2)"
            )
