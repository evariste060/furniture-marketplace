"""cart: the price a line was added at

Approved by the project owner on 2026-10-27 (frontend phase 4 decision 1). The cart page tells
the customer when a price changed after they added the product (Cart.dc.html "Price updated:
was RWF 230,000" and "Accept changes"). A line keeps the variant's price from when it was added
(or last topped up, or accepted); null for lines added before this revision, which show no
notice. Display only: totals and checkout always use the current price.

Revision ID: f1a7c3e9d2b4
Revises: e5c9a2f7b3d1
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f1a7c3e9d2b4"
down_revision: str | None = "e5c9a2f7b3d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cart_items", sa.Column("price_at_add", sa.BigInteger(), nullable=True))
    op.create_check_constraint(
        op.f("ck_cart_items_price_at_add_nonnegative"), "cart_items", "price_at_add >= 0"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_cart_items_price_at_add_nonnegative"), "cart_items", type_="check")
    op.drop_column("cart_items", "price_at_add")
