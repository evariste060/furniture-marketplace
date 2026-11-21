"""Password reset codes (module 2).

Revision ID: 37b61c6765c1
Revises: 528e6436c34e
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "37b61c6765c1"
down_revision: str | Sequence[str] | None = "528e6436c34e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "password_reset_codes",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("channel", sa.String(length=8), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
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
            "attempts >= 0", name=op.f("ck_password_reset_codes_attempts_nonnegative")
        ),
        sa.CheckConstraint(
            "channel IN ('email', 'sms')", name=op.f("ck_password_reset_codes_valid_channel")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_password_reset_codes_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_password_reset_codes")),
    )
    op.create_index(
        "ix_password_reset_codes_user_created",
        "password_reset_codes",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_password_reset_codes_user_created", table_name="password_reset_codes")
    op.drop_table("password_reset_codes")
