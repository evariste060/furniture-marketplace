"""catalogue: case-insensitive SKUs, one product image per position, import warnings

Approved by the project owner on 2026-10-26 (checkpoint 1b, topics 5 and 6):
- product_variants: SKUs are unique ignoring case (unique index on lower(sku)), and "__" is not
  allowed in a SKU (validated by the API; existing SKUs are checked here).
- product_images: at most one product-level image per position (partial unique index on
  (product_id, sort_order) WHERE variant_id IS NULL), so a bulk upload's "<slug>__<n>" file names
  one image exactly. Variant images are not affected.
- import_jobs.warnings: rows applied with a change, e.g. a product asked to be active without
  images, which is created as a draft.

The upgrade first checks the existing data and refuses, listing what to fix, if any SKUs differ
only by case or contain "__", or if a product has two product-level images at one position.
The downgrade drops the indexes and the column.

Revision ID: e7b2d6f4a8c3
Revises: d5f9b3c7e1a2
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e7b2d6f4a8c3"
down_revision: str | Sequence[str] | None = "d5f9b3c7e1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LISTED = 20  # problems listed in the refusal; the count is always complete


def _problems() -> list[str]:
    bind = op.get_bind()
    problems: list[str] = []
    case_duplicates = bind.execute(
        sa.text(
            "SELECT lower(sku), string_agg(sku, ', ' ORDER BY sku) FROM product_variants "
            "GROUP BY lower(sku) HAVING count(*) > 1 ORDER BY 1"
        )
    ).all()
    problems += [f"SKUs differing only by case: {skus}" for _, skus in case_duplicates]
    double_underscore = bind.execute(
        sa.text("SELECT sku FROM product_variants WHERE sku LIKE '%\\_\\_%' ORDER BY sku")
    ).scalars()
    problems += [f"SKU containing '__': {sku}" for sku in double_underscore]
    positions = bind.execute(
        sa.text(
            "SELECT p.slug, i.sort_order, count(*) FROM product_images i "
            "JOIN products p ON p.id = i.product_id WHERE i.variant_id IS NULL "
            "GROUP BY p.slug, i.sort_order HAVING count(*) > 1 ORDER BY 1, 2"
        )
    ).all()
    problems += [
        f"product {slug}: {count} images at position {sort_order + 1}"
        for slug, sort_order, count in positions
    ]
    return problems


def upgrade() -> None:
    problems = _problems()
    if problems:
        listed = "; ".join(problems[:LISTED])
        more = f" (and {len(problems) - LISTED} more)" if len(problems) > LISTED else ""
        raise RuntimeError(
            f"Refusing to migrate: {len(problems)} problem(s) to fix first: {listed}{more}. "
            "Rename the SKUs, or move images to free positions (PATCH /staff/images/{id} "
            "sort_order), then upgrade again."
        )
    op.create_index(
        "uq_product_variants_sku_lower",
        "product_variants",
        [sa.text("lower(sku)")],
        unique=True,
    )
    op.create_index(
        "uq_product_images_product_position",
        "product_images",
        ["product_id", "sort_order"],
        unique=True,
        postgresql_where=sa.text("variant_id IS NULL"),
    )
    op.add_column(
        "import_jobs",
        sa.Column(
            "warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_import_jobs_warnings_array"),
        "import_jobs",
        "jsonb_typeof(warnings) = 'array'",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_import_jobs_warnings_array"), "import_jobs", type_="check")
    op.drop_column("import_jobs", "warnings")
    op.drop_index("uq_product_images_product_position", table_name="product_images")
    op.drop_index("uq_product_variants_sku_lower", table_name="product_variants")
