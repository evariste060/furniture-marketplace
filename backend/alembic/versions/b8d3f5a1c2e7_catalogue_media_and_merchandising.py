"""catalogue: category images and descriptions, brand logos, featured products, image originals

Approved by the project owner on 2026-10-25 (B1, B2; ADR-009):
- categories: description (storefront subtitle), image_key, image_width, image_height;
- brands: logo_key, logo_width, logo_height;
- products: is_featured (default false) with a partial index for the featured listing;
- product_images: original_key, the exact uploaded original in private storage. Null for rows
  created before ADR-009; their files are kept and keep working.
Every new column is nullable or has a default, so existing rows stay valid. The downgrade drops
the columns only; stored files are left untouched.

Revision ID: b8d3f5a1c2e7
Revises: a7c2e4f9b1d3
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b8d3f5a1c2e7"
down_revision: str | Sequence[str] | None = "a7c2e4f9b1d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECKS = {
    ("categories", "ck_categories_image_fields_together"): (
        "(image_key IS NULL) = (image_width IS NULL) "
        "AND (image_key IS NULL) = (image_height IS NULL)"
    ),
    ("categories", "ck_categories_image_dimensions_positive"): (
        "image_width IS NULL OR (image_width > 0 AND image_height > 0)"
    ),
    ("brands", "ck_brands_logo_fields_together"): (
        "(logo_key IS NULL) = (logo_width IS NULL) AND (logo_key IS NULL) = (logo_height IS NULL)"
    ),
    ("brands", "ck_brands_logo_dimensions_positive"): (
        "logo_width IS NULL OR (logo_width > 0 AND logo_height > 0)"
    ),
}


def upgrade() -> None:
    op.add_column("categories", sa.Column("description", sa.String(length=500)))
    op.add_column("categories", sa.Column("image_key", sa.String(length=1024)))
    op.add_column("categories", sa.Column("image_width", sa.Integer()))
    op.add_column("categories", sa.Column("image_height", sa.Integer()))
    op.add_column("brands", sa.Column("logo_key", sa.String(length=1024)))
    op.add_column("brands", sa.Column("logo_width", sa.Integer()))
    op.add_column("brands", sa.Column("logo_height", sa.Integer()))
    for (table, name), condition in CHECKS.items():
        op.create_check_constraint(op.f(name), table, condition)
    op.add_column(
        "products",
        sa.Column("is_featured", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_products_featured", "products", ["status"], postgresql_where=sa.text("is_featured")
    )
    op.add_column("product_images", sa.Column("original_key", sa.String(length=1024)))


def downgrade() -> None:
    op.drop_column("product_images", "original_key")
    op.drop_index("ix_products_featured", table_name="products")
    op.drop_column("products", "is_featured")
    for table, name in CHECKS:
        op.drop_constraint(op.f(name), table, type_="check")
    op.drop_column("brands", "logo_height")
    op.drop_column("brands", "logo_width")
    op.drop_column("brands", "logo_key")
    op.drop_column("categories", "image_height")
    op.drop_column("categories", "image_width")
    op.drop_column("categories", "image_key")
    op.drop_column("categories", "description")
