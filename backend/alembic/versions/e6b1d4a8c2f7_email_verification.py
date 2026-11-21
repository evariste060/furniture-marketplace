"""auth: email verification of new customer accounts (ADR-006 amendment, 2026-11-12)

- users.email_verified_at (nullable timestamp): when the email address was proven. Every account
  that exists before this revision and has an email is marked verified at its creation time, so
  no existing customer or staff member is locked out. From now on a customer who registers with
  an email and a password starts unverified and gets no session until they verify.
- email_verification_tokens: one row per verification link sent. Only the SHA-256 of the token
  is stored (unique), with the address it verifies, its expiry, and when it was used (consumed)
  or superseded (revoked); a token is never both.

The downgrade stops while any customer with an email is still unverified: the previous code has
no such state and would let them sign in without having proven the address. Otherwise it drops
the table and the column.

Revision ID: e6b1d4a8c2f7
Revises: d5a9c3e7f2b8 (Continue with Google)
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e6b1d4a8c2f7"
down_revision: str | Sequence[str] | None = "d5a9c3e7f2b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True)))
    # Existing accounts stay able to sign in: their addresses count as verified.
    op.execute("UPDATE users SET email_verified_at = created_at WHERE email IS NOT NULL")

    op.create_table(
        "email_verification_tokens",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "consumed_at IS NULL OR revoked_at IS NULL",
            name=op.f("ck_email_verification_tokens_consumed_or_revoked_not_both"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_email_verification_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_verification_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_email_verification_tokens_token_hash")),
    )
    op.create_index(
        "ix_email_verification_tokens_user_created",
        "email_verification_tokens",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    unverified = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM users "
            "WHERE email IS NOT NULL AND email_verified_at IS NULL AND NOT is_staff"
        )
    )
    if unverified:
        raise RuntimeError(
            f"{unverified} customers have not verified their email; downgrading would let them "
            "sign in without having proven the address. Remove or verify those accounts first."
        )
    op.drop_index(
        "ix_email_verification_tokens_user_created", table_name="email_verification_tokens"
    )
    op.drop_table("email_verification_tokens")
    op.drop_column("users", "email_verified_at")
