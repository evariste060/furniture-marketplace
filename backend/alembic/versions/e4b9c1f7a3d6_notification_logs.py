"""Notification logs (module 17; plan §5 "17 — notifications"; §7 Q22).

notification_logs: one customer message per order event (confirmed, dispatched, delivered,
cancelled) and channel (sms or email); (order_id, event, channel) is unique, so a repeated event
records nothing new. The row is inserted in the transaction that changes the order and sent after
it commits; status pending -> sent, or failed (retried at next_attempt_at while attempts < 3).
claimed_until is the sending worker's lease. The recipient must match its channel (canonical
Rwandan mobile number for sms, an address for email); last_error holds a sanitised code only and
no message text is stored. Rows are never deleted (the runtime role gets SELECT, INSERT, UPDATE).

Nothing is backfilled: orders changed before this revision get no notification. Downgrade drops
the table and its log.

Revision ID: e4b9c1f7a3d6
Revises: a1d9c3e5f7b2
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e4b9c1f7a3d6"
down_revision: str | Sequence[str] | None = "a1d9c3e5f7b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DUE = "status IN ('pending', 'failed') AND next_attempt_at IS NOT NULL"


def upgrade() -> None:
    op.create_table(
        "notification_logs",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("event", sa.String(length=16), nullable=False),
        sa.Column("channel", sa.String(length=8), nullable=False),
        sa.Column("recipient", sa.String(length=320), nullable=False),
        sa.Column("status", sa.String(length=8), server_default="pending", nullable=False),
        sa.Column("attempts", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column("provider_message_id", sa.String(length=128), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "(channel = 'sms' AND recipient ~ '^\\+2507[0-9]{8}$') "
            "OR (channel = 'email' AND recipient ~ '^[^@[:space:]]+@[^@[:space:]]+$')",
            name=op.f("ck_notification_logs_recipient_matches_channel"),
        ),
        sa.CheckConstraint(
            "(status = 'sent') = (sent_at IS NOT NULL)",
            name=op.f("ck_notification_logs_sent_at_when_sent"),
        ),
        sa.CheckConstraint(
            "channel IN ('sms', 'email')", name=op.f("ck_notification_logs_valid_channel")
        ),
        sa.CheckConstraint(
            "event IN ('confirmed', 'dispatched', 'delivered', 'cancelled')",
            name=op.f("ck_notification_logs_valid_event"),
        ),
        sa.CheckConstraint(
            "status <> 'pending' OR next_attempt_at IS NOT NULL",
            name=op.f("ck_notification_logs_pending_is_scheduled"),
        ),
        sa.CheckConstraint(
            "status <> 'sent' OR (provider_message_id IS NOT NULL AND next_attempt_at IS NULL "
            "AND claimed_until IS NULL)",
            name=op.f("ck_notification_logs_sent_is_final"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed')",
            name=op.f("ck_notification_logs_valid_status"),
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND attempts <= 3", name=op.f("ck_notification_logs_attempts_bounded")
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_notification_logs_order_id_orders"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_logs")),
        sa.UniqueConstraint("order_id", "event", "channel", name="order_event_channel"),
    )
    op.create_index("ix_notification_logs_created", "notification_logs", ["created_at"])
    op.create_index(
        "ix_notification_logs_due", "notification_logs", ["next_attempt_at"], postgresql_where=DUE
    )
    op.create_index(
        "ix_notification_logs_status_created", "notification_logs", ["status", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_notification_logs_status_created", table_name="notification_logs")
    op.drop_index("ix_notification_logs_due", table_name="notification_logs", postgresql_where=DUE)
    op.drop_index("ix_notification_logs_created", table_name="notification_logs")
    op.drop_table("notification_logs")
