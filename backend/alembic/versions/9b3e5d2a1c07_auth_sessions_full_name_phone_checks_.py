"""auth: sessions, users.full_name, canonical phones, append-only audit records

Builds the authentication layer (ADR-006) on top of the commerce identity schema (PR #2):
- user_sessions: opaque bearer sessions (SHA-256 of token only), cascade with their user.
- users.full_name: display name collected at registration (nullable for existing rows).
- Canonical +2507XXXXXXXX phones on users.phone and addresses.phone. Fails loudly, rather than
  rewriting identifiers, if existing rows are non-canonical.
- audit_records: UPDATE/DELETE/TRUNCATE blocked for every role by trigger. The only permitted
  UPDATE is the users FK action ON DELETE SET NULL clearing actor_user_id.

Revision ID: 9b3e5d2a1c07
Revises: f6ee0bc51c3c
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9b3e5d2a1c07"
down_revision: str | Sequence[str] | None = "f6ee0bc51c3c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PHONE_RE = r"'^\+2507[0-9]{8}$'"


def upgrade() -> None:
    op.create_table(
        "user_sessions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_user_sessions_token_hash")),
    )
    op.create_index(op.f("ix_user_sessions_user_id"), "user_sessions", ["user_id"], unique=False)
    op.add_column("users", sa.Column("full_name", sa.String(length=255), nullable=True))

    op.create_check_constraint(
        op.f("ck_users_phone_canonical"), "users", f"phone IS NULL OR phone ~ {PHONE_RE}"
    )
    op.create_check_constraint(
        op.f("ck_addresses_phone_canonical"), "addresses", f"phone ~ {PHONE_RE}"
    )

    op.execute(
        """
        CREATE FUNCTION audit_records_block_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND OLD.actor_user_id IS NOT NULL AND NEW.actor_user_id IS NULL
               AND (to_jsonb(NEW) - 'actor_user_id') = (to_jsonb(OLD) - 'actor_user_id') THEN
                RETURN NEW;  -- users FK ON DELETE SET NULL
            END IF;
            RAISE EXCEPTION 'audit_records is append-only (% blocked)', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_records_append_only
        BEFORE UPDATE OR DELETE ON audit_records
        FOR EACH ROW EXECUTE FUNCTION audit_records_block_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_records_no_truncate
        BEFORE TRUNCATE ON audit_records
        FOR EACH STATEMENT EXECUTE FUNCTION audit_records_block_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_records_no_truncate ON audit_records")
    op.execute("DROP TRIGGER IF EXISTS audit_records_append_only ON audit_records")
    op.execute("DROP FUNCTION IF EXISTS audit_records_block_mutation()")
    op.drop_constraint(op.f("ck_addresses_phone_canonical"), "addresses", type_="check")
    op.drop_constraint(op.f("ck_users_phone_canonical"), "users", type_="check")
    op.drop_column("users", "full_name")
    op.drop_index(op.f("ix_user_sessions_user_id"), table_name="user_sessions")
    op.drop_table("user_sessions")
