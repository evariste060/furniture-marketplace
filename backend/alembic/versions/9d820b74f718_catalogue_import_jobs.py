"""Catalogue import jobs (module 8).

Revision ID: 9d820b74f718
Revises: 76768b844c03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "9d820b74f718"
down_revision: str | Sequence[str] | None = "76768b844c03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "import_jobs",
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("file_format", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="processing", nullable=False),
        sa.Column("total_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("imported_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "errors", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("errors_truncated", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "file_format IN ('csv', 'xlsx')", name=op.f("ck_import_jobs_valid_file_format")
        ),
        sa.CheckConstraint(
            "status IN ('processing', 'completed', 'failed')",
            name=op.f("ck_import_jobs_valid_status"),
        ),
        sa.CheckConstraint(
            "total_rows >= 0 AND imported_rows >= 0 AND error_rows >= 0",
            name=op.f("ck_import_jobs_counts_nonnegative"),
        ),
        sa.CheckConstraint(
            "imported_rows + error_rows <= total_rows",
            name=op.f("ck_import_jobs_counts_within_total"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(errors) = 'array' AND jsonb_array_length(errors) <= 1000",
            name=op.f("ck_import_jobs_errors_capped_array"),
        ),
        sa.CheckConstraint(
            "(status = 'processing') = (finished_at IS NULL)",
            name=op.f("ck_import_jobs_finished_when_final"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_import_jobs_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_jobs")),
    )
    op.create_index(
        "ix_import_jobs_created_by_created", "import_jobs", ["created_by_user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_import_jobs_created_by_created", table_name="import_jobs")
    op.drop_table("import_jobs")
