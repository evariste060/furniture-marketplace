"""engagement: customer wishlist (module 21)

Approved by the project owner on 2026-10-27 (scope change SC-01). A signed-in customer saves
products: one row per (customer, product), at most 200 per customer (enforced by the service
under the customer's row lock). Removing a product deletes its row. Products are never deleted
(they are archived), so the product reference is RESTRICT. The table is new and empty.

Revision ID: d3b8e6f1a4c7
Revises: c6f2a8d4e1b9
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d3b8e6f1a4c7"
down_revision: str | None = "c6f2a8d4e1b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wishlist_items",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_wishlist_items_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_wishlist_items_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wishlist_items")),
        sa.UniqueConstraint("user_id", "product_id", name="user_product"),
    )
    op.create_index(
        op.f("ix_wishlist_items_product_id"), "wishlist_items", ["product_id"], unique=False
    )
    op.create_index(
        "ix_wishlist_items_user_created", "wishlist_items", ["user_id", "created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_wishlist_items_user_created", table_name="wishlist_items")
    op.drop_index(op.f("ix_wishlist_items_product_id"), table_name="wishlist_items")
    op.drop_table("wishlist_items")
