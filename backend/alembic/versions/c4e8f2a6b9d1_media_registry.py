"""media: registry of stored files (media_objects); images link to it

Approved by the project owner on 2026-10-26 (checkpoint 1b, topic 1; ADR-009):
- media_objects tracks every stored file: its key, visibility (private/public), kind (original,
  public_source, incoming), state (pending -> active -> deleting), SHA-256, size, dimensions,
  owner, and the cleanup bookkeeping (delete_after, attempts, last_error). Files are never
  overwritten; a file is deleted only by the cleanup worker, after the state that stopped using
  it has been committed.
- product_images: public_media_id and original_media_id replace storage_key, original_key,
  thumbnail_key, width and height (the dimensions are on the public media object).
- categories: image_media_id and image_original_media_id replace image_key, image_width and
  image_height; brands: logo_media_id and logo_original_media_id replace logo_key, logo_width and
  logo_height.

No hosted environment holds images (confirmed by the project owner on 2026-10-26), and image
rows written before this revision have no registry entry (their SHA-256 is unknown without
reading files). The upgrade therefore refuses while any image row exists: run
`scripts/reset_dev_images.py --confirm` on the development database first, then re-seed. The
downgrade moves the links back to keys and dimensions, then drops the registry; stored files are
left untouched.

Revision ID: c4e8f2a6b9d1
Revises: b8d3f5a1c2e7
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4e8f2a6b9d1"
down_revision: str | Sequence[str] | None = "b8d3f5a1c2e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REFUSAL = (
    "Refusing to migrate: {counts} exist without a media registry entry. No hosted environment "
    "holds images; on a development database run `uv run python ../scripts/reset_dev_images.py "
    "--confirm` from backend/ (it deletes image rows and image files only), then upgrade again "
    "and re-seed."
)
OLD_CHECKS = {
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
    ("product_images", "ck_product_images_width_positive"): "width IS NULL OR width > 0",
    ("product_images", "ck_product_images_height_positive"): "height IS NULL OR height > 0",
    ("product_images", "ck_product_images_dimensions_together"): (
        "(width IS NULL) = (height IS NULL)"
    ),
}
# (table, public column, original column)
LINKS = (
    ("product_images", "public_media_id", "original_media_id"),
    ("categories", "image_media_id", "image_original_media_id"),
    ("brands", "logo_media_id", "logo_original_media_id"),
)


def _refuse_unregistered_images() -> None:
    bind = op.get_bind()
    counts = {
        "product image rows": "SELECT count(*) FROM product_images",
        "category images": "SELECT count(*) FROM categories WHERE image_key IS NOT NULL",
        "brand logos": "SELECT count(*) FROM brands WHERE logo_key IS NOT NULL",
    }
    found = {
        label: n for label, query in counts.items() if (n := bind.execute(sa.text(query)).scalar())
    }
    if found:
        listed = ", ".join(f"{n} {label}" for label, n in found.items())
        raise RuntimeError(REFUSAL.format(counts=listed))


def upgrade() -> None:
    _refuse_unregistered_images()
    op.create_table(
        "media_objects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("visibility", sa.String(length=8), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=10), server_default="pending", nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("content_type", sa.String(length=80), nullable=False),
        sa.Column("owner_type", sa.String(length=16), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("delete_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "visibility IN ('private', 'public')", name=op.f("ck_media_objects_valid_visibility")
        ),
        sa.CheckConstraint(
            "kind IN ('original', 'public_source', 'incoming')",
            name=op.f("ck_media_objects_valid_kind"),
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'active', 'deleting')", name=op.f("ck_media_objects_valid_state")
        ),
        sa.CheckConstraint(
            "owner_type IN ('products', 'categories', 'brands', 'banners', 'jobs')",
            name=op.f("ck_media_objects_valid_owner_type"),
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_media_objects_sha256_hex")),
        sa.CheckConstraint("bytes >= 0", name=op.f("ck_media_objects_bytes_nonnegative")),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_media_objects_attempts_nonnegative")),
        sa.CheckConstraint(
            "(width IS NULL) = (height IS NULL) AND (width IS NULL OR (width > 0 AND height > 0))",
            name=op.f("ck_media_objects_dimensions_valid"),
        ),
        sa.CheckConstraint(
            "(kind = 'public_source') = (visibility = 'public')",
            name=op.f("ck_media_objects_kind_matches_visibility"),
        ),
        sa.CheckConstraint(
            "kind <> 'incoming' OR (visibility = 'private' AND delete_after IS NOT NULL)",
            name=op.f("ck_media_objects_incoming_private_and_expiring"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_objects")),
        sa.UniqueConstraint(
            "visibility", "storage_key", name="uq_media_objects_visibility_storage_key"
        ),
    )
    op.create_index("ix_media_objects_state_created", "media_objects", ["state", "created_at"])
    op.create_index(
        "ix_media_objects_state_delete_after", "media_objects", ["state", "delete_after"]
    )
    op.create_index("ix_media_objects_owner", "media_objects", ["owner_type", "owner_id"])

    for (table, name), _ in OLD_CHECKS.items():
        op.drop_constraint(op.f(name), table, type_="check")
    for column in ("storage_key", "original_key", "thumbnail_key", "width", "height"):
        op.drop_column("product_images", column)
    for column in ("image_key", "image_width", "image_height"):
        op.drop_column("categories", column)
    for column in ("logo_key", "logo_width", "logo_height"):
        op.drop_column("brands", column)

    for table, public, original in LINKS:
        required = table == "product_images"  # categories and brands may have no image
        for column in (public, original):
            op.add_column(table, sa.Column(column, sa.Uuid(), nullable=not required))
            op.create_foreign_key(
                op.f(f"fk_{table}_{column}_media_objects"),
                table,
                "media_objects",
                [column],
                ["id"],
                ondelete="RESTRICT",
            )
            op.create_unique_constraint(op.f(f"uq_{table}_{column}"), table, [column])
        if not required:
            op.create_check_constraint(
                op.f(f"ck_{table}_{public.removesuffix('_media_id')}_media_together"),
                table,
                f"({public} IS NULL) = ({original} IS NULL)",
            )


def downgrade() -> None:
    op.add_column("product_images", sa.Column("storage_key", sa.String(length=1024)))
    op.add_column("product_images", sa.Column("original_key", sa.String(length=1024)))
    op.add_column("product_images", sa.Column("thumbnail_key", sa.String(length=1024)))
    op.add_column("product_images", sa.Column("width", sa.Integer()))
    op.add_column("product_images", sa.Column("height", sa.Integer()))
    op.add_column("categories", sa.Column("image_key", sa.String(length=1024)))
    op.add_column("categories", sa.Column("image_width", sa.Integer()))
    op.add_column("categories", sa.Column("image_height", sa.Integer()))
    op.add_column("brands", sa.Column("logo_key", sa.String(length=1024)))
    op.add_column("brands", sa.Column("logo_width", sa.Integer()))
    op.add_column("brands", sa.Column("logo_height", sa.Integer()))
    op.execute(
        "UPDATE product_images i SET storage_key = p.storage_key, original_key = o.storage_key, "
        "width = p.width, height = p.height FROM media_objects p, media_objects o "
        "WHERE p.id = i.public_media_id AND o.id = i.original_media_id"
    )
    op.execute(
        "UPDATE categories c SET image_key = p.storage_key, image_width = p.width, "
        "image_height = p.height FROM media_objects p WHERE p.id = c.image_media_id"
    )
    op.execute(
        "UPDATE brands b SET logo_key = p.storage_key, logo_width = p.width, "
        "logo_height = p.height FROM media_objects p WHERE p.id = b.logo_media_id"
    )
    op.alter_column("product_images", "storage_key", nullable=False)
    for table, public, original in LINKS:
        if table != "product_images":
            op.drop_constraint(
                op.f(f"ck_{table}_{public.removesuffix('_media_id')}_media_together"),
                table,
                type_="check",
            )
        for column in (public, original):
            op.drop_constraint(op.f(f"uq_{table}_{column}"), table, type_="unique")
            op.drop_constraint(
                op.f(f"fk_{table}_{column}_media_objects"), table, type_="foreignkey"
            )
            op.drop_column(table, column)
    for (table, name), condition in OLD_CHECKS.items():
        op.create_check_constraint(op.f(name), table, condition)
    op.drop_index("ix_media_objects_owner", table_name="media_objects")
    op.drop_index("ix_media_objects_state_delete_after", table_name="media_objects")
    op.drop_index("ix_media_objects_state_created", table_name="media_objects")
    op.drop_table("media_objects")
