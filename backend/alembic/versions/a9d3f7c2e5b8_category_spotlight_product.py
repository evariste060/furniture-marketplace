"""category spotlight product: the product staff showcase per category (approved 2026-11-11)

Adds categories.spotlight_product_id, a nullable reference to products (SET NULL when the
product is deleted). The home page's category spotlight shows that product while it is public
and in the category or a subcategory; with none chosen it shows the category's best seller.

The downgrade drops the column (the picks are lost).

Revision ID: a9d3f7c2e5b8
Revises: d4b8e2f6a9c3
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a9d3f7c2e5b8"
down_revision: str | Sequence[str] | None = "d4b8e2f6a9c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK = "fk_categories_spotlight_product_id_products"


def upgrade() -> None:
    op.add_column("categories", sa.Column("spotlight_product_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        FK, "categories", "products", ["spotlight_product_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint(FK, "categories", type_="foreignkey")
    op.drop_column("categories", "spotlight_product_id")
