"""products: every product belongs to one store (ADR-014 phase 2)

products.store_id references stores (RESTRICT: a store with products is never deleted, and the
runtime role cannot delete stores at all) and is NOT NULL, with an index on (store_id, status)
for the seller's own product list.

The upgrade refuses to run while products exist: it never invents an owner for them. On a
development database, remove the demo catalogue with the development-only tooling (or reseed it
after the upgrade, which assigns the demo products to demo stores); production and staging hold
no products yet. Only the count is reported. The downgrade drops the column.

Revision ID: b2d4f6a8c0e1
Revises: a9d3f5b7c1e2
Create Date: 2026-11-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2d4f6a8c0e1"
down_revision: str | Sequence[str] | None = "a9d3f5b7c1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM products")).scalar_one()
    if count:
        raise RuntimeError(
            f"ADR-014 phase 2 gives every product a store, but {count} products exist without "
            "one. No product was changed. On a development database, remove the demo catalogue "
            "with the development tooling, upgrade, then reseed it; never run this against "
            "real data without an approved assignment of products to stores."
        )
    op.add_column("products", sa.Column("store_id", sa.Uuid(), nullable=False))
    op.create_foreign_key(
        op.f("fk_products_store_id_stores"),
        "products",
        "stores",
        ["store_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_products_store_status", "products", ["store_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_products_store_status", table_name="products")
    op.drop_constraint(op.f("fk_products_store_id_stores"), "products", type_="foreignkey")
    op.drop_column("products", "store_id")
