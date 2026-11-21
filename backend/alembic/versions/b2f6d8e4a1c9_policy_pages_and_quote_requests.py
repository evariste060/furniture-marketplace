"""content: policy pages and business quote requests (module 19); joins the dev and frontend heads

Approved by the project owner on 2026-10-29: the frontend phase 1 module 19 replaces the module 19
first merged into dev (edebaf558c2d). That revision stays in the history, as databases on dev may
have run it; this one joins its head with the frontend phase 1 head (a8d2f6c1e3b7) and changes
its `pages` table to the module 19 shape:

- slug at most 60 characters (the six policy page slugs), title at most 120;
- constraint names of the module 19 model: ck_pages_locale_valid, ck_pages_title_present and the
  unique (slug, locale) constraint slug_locale. The title check becomes "not empty"; the API
  already trims titles, so a blank title cannot be written.

A row that does not fit (a slug over 60 or a title over 120 characters) stops the upgrade with a
message instead of being cut; no row is changed or removed.

It also adds `quote_requests`: the Contact page's business quote requests (company, contact
person, canonical Rwandan mobile phone, optional email, 1-20 product lines as JSON, optional
delivery location, needed-by date and message, the sender's language) and their follow-up status
(new, contacted, closed; handled_at is set exactly when the status is not new). It is new and
empty.

The downgrade drops quote_requests and gives `pages` its edebaf558c2d shape back.

Revision ID: b2f6d8e4a1c9
Revises: a8d2f6c1e3b7, edebaf558c2d
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b2f6d8e4a1c9"
down_revision: str | Sequence[str] | None = ("a8d2f6c1e3b7", "edebaf558c2d")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _refuse_rows_that_do_not_fit(slug_max: int, title_max: int) -> None:
    too_long = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM pages "
                "WHERE char_length(slug) > :slug_max OR char_length(title) > :title_max"
            ),
            {"slug_max": slug_max, "title_max": title_max},
        )
        .scalar_one()
    )
    if too_long:
        raise RuntimeError(
            f"{too_long} page(s) have a slug over {slug_max} or a title over {title_max} "
            "characters; shorten them before upgrading."
        )


def upgrade() -> None:
    _refuse_rows_that_do_not_fit(slug_max=60, title_max=120)
    op.alter_column("pages", "slug", type_=sa.String(length=60), existing_nullable=False)
    op.alter_column("pages", "title", type_=sa.String(length=120), existing_nullable=False)
    op.execute("ALTER TABLE pages RENAME CONSTRAINT ck_pages_valid_locale TO ck_pages_locale_valid")
    op.drop_constraint(op.f("ck_pages_title_not_blank"), "pages", type_="check")
    op.create_check_constraint(op.f("ck_pages_title_present"), "pages", "char_length(title) > 0")
    op.execute("ALTER TABLE pages RENAME CONSTRAINT uq_pages_slug_locale TO slug_locale")

    op.create_table(
        "quote_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reference", sa.String(length=20), nullable=False),
        sa.Column("company", sa.String(length=150), nullable=False),
        sa.Column("contact_name", sa.String(length=120), nullable=False),
        sa.Column("phone", sa.String(length=13), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("lines", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("delivery_location", sa.String(length=120), nullable=True),
        sa.Column("needed_by", sa.Date(), nullable=True),
        sa.Column("message", sa.String(length=2000), nullable=True),
        sa.Column("locale", sa.String(length=2), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="new", nullable=False),
        sa.Column("handled_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('new', 'contacted', 'closed')", name=op.f("ck_quote_requests_status_valid")
        ),
        sa.CheckConstraint(
            r"phone ~ '^\+2507[0-9]{8}$'", name=op.f("ck_quote_requests_phone_canonical")
        ),
        sa.CheckConstraint("locale IN ('en', 'rw')", name=op.f("ck_quote_requests_locale_valid")),
        sa.CheckConstraint(
            "jsonb_typeof(lines) = 'array' AND jsonb_array_length(lines) BETWEEN 1 AND 20",
            name=op.f("ck_quote_requests_lines_shape"),
        ),
        sa.CheckConstraint(
            "(status = 'new') = (handled_at IS NULL)",
            name=op.f("ck_quote_requests_handled_when_not_new"),
        ),
        sa.ForeignKeyConstraint(
            ["handled_by_user_id"],
            ["users.id"],
            name=op.f("fk_quote_requests_handled_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quote_requests")),
        sa.UniqueConstraint("reference", name=op.f("uq_quote_requests_reference")),
    )
    op.create_index("ix_quote_requests_status_created", "quote_requests", ["status", "created_at"])
    op.create_index("ix_quote_requests_created", "quote_requests", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_quote_requests_created", table_name="quote_requests")
    op.drop_index("ix_quote_requests_status_created", table_name="quote_requests")
    op.drop_table("quote_requests")

    op.execute("ALTER TABLE pages RENAME CONSTRAINT slug_locale TO uq_pages_slug_locale")
    op.drop_constraint(op.f("ck_pages_title_present"), "pages", type_="check")
    op.create_check_constraint(
        op.f("ck_pages_title_not_blank"), "pages", "char_length(btrim(title)) > 0"
    )
    op.execute("ALTER TABLE pages RENAME CONSTRAINT ck_pages_locale_valid TO ck_pages_valid_locale")
    op.alter_column("pages", "title", type_=sa.String(length=200), existing_nullable=False)
    op.alter_column("pages", "slug", type_=sa.String(length=80), existing_nullable=False)
