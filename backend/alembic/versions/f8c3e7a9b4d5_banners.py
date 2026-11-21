"""content: storefront banners

Approved by the project owner on 2026-10-26 (checkpoint 1b, topic 9). A banner is the homepage
hero: English and Kinyarwanda title (required, at most 80), subtitle (at most 160) and call to
action label (at most 30, required with a CTA URL), an on-site CTA URL (at most 200), one image
(media registry, required while active), a position, an active flag and an optional window
(starts_at <= now() < ends_at; null is open-ended). Several banners may exist so campaigns can be
scheduled; the storefront shows the first active one by position. Managed with content:manage.

The table is new and empty: no sample content is inserted. The downgrade drops it.

Revision ID: f8c3e7a9b4d5
Revises: e7b2d6f4a8c3
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f8c3e7a9b4d5"
down_revision: str | Sequence[str] | None = "e7b2d6f4a8c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "banners",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title_en", sa.String(length=80), nullable=False),
        sa.Column("title_rw", sa.String(length=80), nullable=False),
        sa.Column("subtitle_en", sa.String(length=160), nullable=True),
        sa.Column("subtitle_rw", sa.String(length=160), nullable=True),
        sa.Column("cta_label_en", sa.String(length=30), nullable=True),
        sa.Column("cta_label_rw", sa.String(length=30), nullable=True),
        sa.Column("cta_url", sa.String(length=200), nullable=True),
        sa.Column("image_media_id", sa.Uuid(), nullable=True),
        sa.Column("image_original_media_id", sa.Uuid(), nullable=True),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("position >= 0", name=op.f("ck_banners_position_nonnegative")),
        sa.CheckConstraint(
            "starts_at IS NULL OR ends_at IS NULL OR ends_at > starts_at",
            name=op.f("ck_banners_window_valid"),
        ),
        sa.CheckConstraint(
            "cta_url IS NULL OR (cta_label_en IS NOT NULL AND cta_label_rw IS NOT NULL)",
            name=op.f("ck_banners_cta_label_with_url"),
        ),
        sa.CheckConstraint(
            "(image_media_id IS NULL) = (image_original_media_id IS NULL)",
            name=op.f("ck_banners_image_media_together"),
        ),
        sa.CheckConstraint(
            "NOT is_active OR image_media_id IS NOT NULL",
            name=op.f("ck_banners_active_has_image"),
        ),
        sa.ForeignKeyConstraint(
            ["image_media_id"],
            ["media_objects.id"],
            name=op.f("fk_banners_image_media_id_media_objects"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["image_original_media_id"],
            ["media_objects.id"],
            name=op.f("fk_banners_image_original_media_id_media_objects"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_banners")),
        sa.UniqueConstraint("image_media_id", name=op.f("uq_banners_image_media_id")),
        sa.UniqueConstraint(
            "image_original_media_id", name=op.f("uq_banners_image_original_media_id")
        ),
    )
    op.create_index("ix_banners_active_position", "banners", ["is_active", "position"])


def downgrade() -> None:
    op.drop_index("ix_banners_active_position", table_name="banners")
    op.drop_table("banners")
