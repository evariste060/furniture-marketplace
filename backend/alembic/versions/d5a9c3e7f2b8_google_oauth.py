"""auth: Continue with Google (ADR-006 amendment, 2026-11-11)

Two new tables, nothing else changes:

- oauth_identities: a Google account (its stable subject, `sub`) linked to a user. One Google
  account per user and one user per Google account (two unique constraints). Sign-in matches the
  subject, never the email address.
- oauth_login_flows: one row per sign-in or link attempt between its start and Google's answer.
  Only SHA-256 digests of the state, the browser-binding flow token and the nonce are stored; the
  PKCE code verifier is erased when the flow is used. A flow is consumed once (consumed_at).

The downgrade drops both tables; it stops instead of dropping when a Google identity exists, so
no account silently loses its only way to sign in.

Revision ID: d5a9c3e7f2b8
Revises: a9d3f7c2e5b8 (category spotlight product)
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d5a9c3e7f2b8"
down_revision: str | Sequence[str] | None = "a9d3f7c2e5b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "oauth_identities",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "provider IN ('google')", name=op.f("ck_oauth_identities_valid_provider")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_oauth_identities_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_identities")),
        sa.UniqueConstraint("provider", "subject", name="uq_oauth_identities_provider_subject"),
        sa.UniqueConstraint("user_id", "provider", name="uq_oauth_identities_user_id_provider"),
    )
    op.create_table(
        "oauth_login_flows",
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("purpose", sa.String(length=8), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("flow_token_hash", sa.String(length=64), nullable=False),
        sa.Column("nonce_hash", sa.String(length=64), nullable=False),
        sa.Column("code_verifier", sa.String(length=128), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "provider IN ('google')", name=op.f("ck_oauth_login_flows_valid_provider")
        ),
        sa.CheckConstraint(
            "purpose IN ('login', 'link')", name=op.f("ck_oauth_login_flows_valid_purpose")
        ),
        sa.CheckConstraint(
            "(purpose = 'link') = (user_id IS NOT NULL)",
            name=op.f("ck_oauth_login_flows_link_flow_has_user"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_oauth_login_flows_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_login_flows")),
        sa.UniqueConstraint("state_hash", name=op.f("uq_oauth_login_flows_state_hash")),
    )
    op.create_index(op.f("ix_oauth_login_flows_expires_at"), "oauth_login_flows", ["expires_at"])


def downgrade() -> None:
    linked = op.get_bind().scalar(sa.text("SELECT count(*) FROM oauth_identities"))
    if linked:
        raise RuntimeError(
            f"{linked} Google sign-in identities exist; downgrading would remove them. "
            "Unlink them first (and make sure each account has another way to sign in)."
        )
    op.drop_index(op.f("ix_oauth_login_flows_expires_at"), table_name="oauth_login_flows")
    op.drop_table("oauth_login_flows")
    op.drop_table("oauth_identities")
