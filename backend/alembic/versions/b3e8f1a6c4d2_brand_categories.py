"""catalog: the main categories each brand belongs to (ADR-012 decision 9, approved 2026-11-17)

- brand_categories: (brand_id, category_id). Staff choose at least one main category when they
  add a brand; the admin lists each main category's brands from it, and the product editor
  offers the category's brands first (a suggestion, never a restriction on products). Deleting
  the brand or the category deletes its rows (CASCADE).

A brand in a main category's store menu belongs to that category (2026-11-17), so the
upgrade links every brand already in a store menu to that category. Other existing brands are
linked by scripts/backfill_brand_categories.py (dry run first). The downgrade drops the table
and the links are lost.

Revision ID: b3e8f1a6c4d2
Revises: a7d2e9c4b1f6 (category menu brands)
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b3e8f1a6c4d2"
down_revision: str | Sequence[str] | None = "a7d2e9c4b1f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "brand_categories",
        sa.Column("brand_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            ["brands.id"],
            name=op.f("fk_brand_categories_brand_id_brands"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_brand_categories_category_id_categories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("brand_id", "category_id", name=op.f("pk_brand_categories")),
    )
    op.create_index("ix_brand_categories_category_id", "brand_categories", ["category_id"])
    op.execute(
        "INSERT INTO brand_categories (brand_id, category_id) "
        "SELECT DISTINCT brand_id, category_id FROM category_menu_brands"
    )


def downgrade() -> None:
    op.drop_index("ix_brand_categories_category_id", table_name="brand_categories")
    op.drop_table("brand_categories")
