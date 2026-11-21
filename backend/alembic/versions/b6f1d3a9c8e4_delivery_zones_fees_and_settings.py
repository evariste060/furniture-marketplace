"""Delivery zones, fee history and settings (module 12; plan §5, RE-026 B1, B5).

delivery_zones gains district (unique; Gasabo, Kicukiro or Nyarugenge), cod_available (default
true) and sort_order (default 0); the unused coverage column is dropped. delivery_fee_rules
keeps its fee history: the (zone_id, is_active) index is replaced by a partial unique index
allowing at most one active rule per zone, plus a (zone_id, created_at) index for the history;
the unused rule_data column is dropped. A new settings table holds editable values such as
delivery.free_delivery_threshold.

Existing data is never invented or silently discarded. The upgrade refuses to run, naming the
reason, when:
- a zone's district cannot be taken from its name or code (one of the three districts, any
  letter case); no district is guessed for other zones;
- coverage or rule_data holds anything other than the empty default '{}';
- a zone has more than one active fee rule.
No rows are seeded here: development values come from scripts/seed_dev.py (plan §5).

Downgrade restores the previous columns (coverage and rule_data as '{}') and index, and drops
settings, district, cod_available and sort_order with their values.

Revision ID: b6f1d3a9c8e4
Revises: a3b4d2f1d8e6
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b6f1d3a9c8e4"
down_revision: str | Sequence[str] | None = "a3b4d2f1d8e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DISTRICTS = ("Gasabo", "Kicukiro", "Nyarugenge")
DISTRICT_LIST = ", ".join(f"'{d}'" for d in DISTRICTS)
OLD_INDEX = "ix_delivery_fee_rules_zone_active"
ONE_ACTIVE = "uq_delivery_fee_rules_one_active_per_zone"
HISTORY = "ix_delivery_fee_rules_zone_created"


def _count(sql: str) -> int:
    return int(op.get_bind().execute(sa.text(sql)).scalar() or 0)


def _refuse(message: str) -> None:
    raise RuntimeError(f"Migration b6f1d3a9c8e4 stopped, nothing was changed: {message}")


def _check_existing_data() -> None:
    if _count("SELECT count(*) FROM delivery_zones WHERE coverage <> '{}'::jsonb"):
        _refuse("delivery_zones.coverage holds data; move it before dropping the column.")
    if _count("SELECT count(*) FROM delivery_fee_rules WHERE rule_data <> '{}'::jsonb"):
        _refuse("delivery_fee_rules.rule_data holds data; move it before dropping the column.")
    if _count(
        "SELECT count(*) FROM (SELECT zone_id FROM delivery_fee_rules WHERE is_active "
        "GROUP BY zone_id HAVING count(*) > 1) AS multiple"
    ):
        _refuse("a delivery zone has more than one active fee rule; deactivate all but one.")


def upgrade() -> None:
    _check_existing_data()
    op.add_column("delivery_zones", sa.Column("district", sa.String(length=40), nullable=True))
    # A legacy zone gets a district only when its name or code is exactly one of the three.
    for district in DISTRICTS:
        op.get_bind().execute(
            sa.text(
                "UPDATE delivery_zones SET district = :district WHERE district IS NULL "
                "AND (lower(btrim(name)) = lower(:district) OR lower(btrim(code)) = "
                "lower(:district))"
            ),
            {"district": district},
        )
    if _count("SELECT count(*) FROM delivery_zones WHERE district IS NULL"):
        _refuse(
            "a delivery zone's district cannot be determined from its name or code; "
            "rename it to Gasabo, Kicukiro or Nyarugenge or remove it first."
        )
    op.alter_column("delivery_zones", "district", nullable=False)
    op.create_unique_constraint("delivery_zone_district", "delivery_zones", ["district"])
    op.create_check_constraint(
        op.f("ck_delivery_zones_supported_district"),
        "delivery_zones",
        f"district IN ({DISTRICT_LIST})",
    )
    op.add_column(
        "delivery_zones",
        sa.Column("cod_available", sa.Boolean(), server_default="true", nullable=False),
    )
    op.add_column(
        "delivery_zones",
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
    )
    op.drop_column("delivery_zones", "coverage")

    op.drop_index(OLD_INDEX, table_name="delivery_fee_rules")
    op.create_index(
        ONE_ACTIVE,
        "delivery_fee_rules",
        ["zone_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_index(HISTORY, "delivery_fee_rules", ["zone_id", "created_at"])
    op.drop_column("delivery_fee_rules", "rule_data")

    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            r"key ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$'",
            name=op.f("ck_settings_key_format"),
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name=op.f("fk_settings_updated_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_settings")),
    )


def downgrade() -> None:
    op.drop_table("settings")

    op.add_column(
        "delivery_fee_rules",
        sa.Column(
            "rule_data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )
    op.drop_index(HISTORY, table_name="delivery_fee_rules")
    op.drop_index(ONE_ACTIVE, table_name="delivery_fee_rules")
    op.create_index(OLD_INDEX, "delivery_fee_rules", ["zone_id", "is_active"], unique=False)

    op.add_column(
        "delivery_zones",
        sa.Column(
            "coverage",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )
    op.drop_column("delivery_zones", "sort_order")
    op.drop_column("delivery_zones", "cod_available")
    op.drop_constraint(
        op.f("ck_delivery_zones_supported_district"), "delivery_zones", type_="check"
    )
    op.drop_constraint("delivery_zone_district", "delivery_zones", type_="unique")
    op.drop_column("delivery_zones", "district")
