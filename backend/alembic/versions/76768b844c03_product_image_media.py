"""Product image thumbnail and dimensions (module 7).

Adds nullable columns so existing rows stay valid: they have no thumbnail or recorded size.

Revision ID: 76768b844c03
Revises: 37b61c6765c1
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "76768b844c03"
down_revision: str | Sequence[str] | None = "37b61c6765c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECKS = {
    "ck_product_images_width_positive": "width IS NULL OR width > 0",
    "ck_product_images_height_positive": "height IS NULL OR height > 0",
    "ck_product_images_dimensions_together": "(width IS NULL) = (height IS NULL)",
}


def upgrade() -> None:
    op.add_column("product_images", sa.Column("thumbnail_key", sa.String(length=1024)))
    op.add_column("product_images", sa.Column("width", sa.Integer()))
    op.add_column("product_images", sa.Column("height", sa.Integer()))
    for name, condition in CHECKS.items():
        op.create_check_constraint(op.f(name), "product_images", condition)


def downgrade() -> None:
    for name in CHECKS:
        op.drop_constraint(op.f(name), "product_images", type_="check")
    op.drop_column("product_images", "height")
    op.drop_column("product_images", "width")
    op.drop_column("product_images", "thumbnail_key")
