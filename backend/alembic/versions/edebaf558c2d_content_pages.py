"""content: pages (module 19; plan §5 "19 — settings & content")

pages: one language version of a content page (privacy, returns, warranty, contact...). One row
per (slug, locale), locale 'en' or 'rw': a missing translation is a missing row, so the public
read returns 404 rather than another language. `body` is Markdown stored as written (the
frontend renders and sanitises it), at most 50,000 characters; the title is at most 200 and not
blank; slugs use the catalogue slug format. Only published rows are public. Managed with
content:manage; rows are never deleted (the runtime role gets SELECT, INSERT, UPDATE).

The table is new and empty: no page content is inserted (TC-20: pages must match
business-approved policies). The downgrade drops it.

Revision ID: edebaf558c2d
Revises: e4b9c1f7a3d6
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "edebaf558c2d"
down_revision: str | Sequence[str] | None = "e4b9c1f7a3d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pages",
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("locale", sa.String(length=2), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_published", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name=op.f("ck_pages_slug_format")),
        sa.CheckConstraint("locale IN ('en', 'rw')", name=op.f("ck_pages_valid_locale")),
        sa.CheckConstraint("char_length(btrim(title)) > 0", name=op.f("ck_pages_title_not_blank")),
        sa.CheckConstraint("char_length(body) <= 50000", name=op.f("ck_pages_body_length")),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name=op.f("fk_pages_updated_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pages")),
        sa.UniqueConstraint("slug", "locale", name="uq_pages_slug_locale"),
    )


def downgrade() -> None:
    op.drop_table("pages")
