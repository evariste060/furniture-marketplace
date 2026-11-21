"""catalog: brands listed per category in the storefront's category menu (ADR-012 amendment,
approved 2026-11-16)

- category_menu_brands: (category_id, brand_id) with a 1-based position, unique per category.
  Staff choose and order the brands the "All Categories" menu shows for a main category, even
  before the brand has products there. Deleting the category or the brand deletes its rows
  (CASCADE): the list is presentation only, never history.

The downgrade drops the table; the lists are lost (the menu then lists brands from products).

Revision ID: a7d2e9c4b1f6
Revises: e6b1d4a8c2f7 (email verification)
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7d2e9c4b1f6"
down_revision: str | Sequence[str] | None = "e6b1d4a8c2f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "category_menu_brands",
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("brand_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint("position >= 1", name=op.f("ck_category_menu_brands_position_positive")),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_category_menu_brands_category_id_categories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_category_menu_brands_brand_id_brands"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("category_id", "brand_id", name=op.f("pk_category_menu_brands")),
        sa.UniqueConstraint("category_id", "position", name="category_position"),
    )
    op.create_index("ix_category_menu_brands_brand_id", "category_menu_brands", ["brand_id"])


def downgrade() -> None:
    op.drop_index("ix_category_menu_brands_brand_id", table_name="category_menu_brands")
    op.drop_table("category_menu_brands")
