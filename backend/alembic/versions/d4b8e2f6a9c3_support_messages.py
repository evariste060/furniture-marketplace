"""support messages: customer questions and staff replies (approved 2026-11-11)

Adds two new, empty tables:

- support_threads: one question from the Contact page and its follow-up. A random reference
  (M-YYMMDD-XXXXXX), the signed-in customer it belongs to (null for guests; SET NULL if the
  account is deleted), the sender's name, canonical Rwandan mobile phone and/or email (at least
  one), topic (order, product, payment, warranty, returns, other), subject, optional order
  number, language, status (open, answered, closed) and the time of
  the last message.
- support_messages: the plain-text messages of a thread (1-2,000 characters), by the customer or
  by staff (staff_user_id, SET NULL if the account is deleted). Deleted with their thread.

notification_logs accepts the event 'support_reply' and the subject type 'support' (the staff
reply that is emailed).

The downgrade drops both tables and restores the notification constraints. It stops with a
message instead of deleting rows when a support_reply notification exists.

Revision ID: d4b8e2f6a9c3
Revises: c7e2a9f4d1b6
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4b8e2f6a9c3"
down_revision: str | Sequence[str] | None = "c7e2a9f4d1b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_EVENTS = (
    "confirmed",
    "dispatched",
    "delivered",
    "cancelled",
    "received",
    "staff_new_order",
    "payment_succeeded",
    "welcome",
    "quote_received",
    "review_thanks",
)
NEW_EVENTS = (*OLD_EVENTS, "support_reply")
OLD_SUBJECTS = ("order", "user", "quote", "review")
NEW_SUBJECTS = (*OLD_SUBJECTS, "support")


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _notification_checks(events: Sequence[str], subjects: Sequence[str]) -> None:
    op.drop_constraint(op.f("ck_notification_logs_valid_event"), "notification_logs", type_="check")
    op.drop_constraint(
        op.f("ck_notification_logs_valid_subject_type"), "notification_logs", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_notification_logs_valid_event"), "notification_logs", _in("event", events)
    )
    op.create_check_constraint(
        op.f("ck_notification_logs_valid_subject_type"),
        "notification_logs",
        _in("subject_type", subjects),
    )


def upgrade() -> None:
    op.create_table(
        "support_threads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reference", sa.String(length=20), nullable=False),
        sa.Column("customer_user_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("phone", sa.String(length=13), nullable=True),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("topic", sa.String(length=16), nullable=False),
        sa.Column("subject", sa.String(length=120), nullable=False),
        sa.Column("order_number", sa.String(length=32), nullable=True),
        sa.Column("locale", sa.String(length=2), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('open', 'answered', 'closed')", name=op.f("ck_support_threads_status_valid")
        ),
        sa.CheckConstraint(
            r"phone IS NULL OR phone ~ '^\+2507[0-9]{8}$'",
            name=op.f("ck_support_threads_phone_canonical"),
        ),
        sa.CheckConstraint(
            "phone IS NOT NULL OR email IS NOT NULL", name=op.f("ck_support_threads_has_contact")
        ),
        sa.CheckConstraint("locale IN ('en', 'rw')", name=op.f("ck_support_threads_locale_valid")),
        sa.CheckConstraint(
            "topic IN ('order', 'product', 'payment', 'warranty', 'returns', 'other')",
            name=op.f("ck_support_threads_topic_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["customer_user_id"],
            ["users.id"],
            name=op.f("fk_support_threads_customer_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_support_threads")),
        sa.UniqueConstraint("reference", name=op.f("uq_support_threads_reference")),
    )
    op.create_index(
        "ix_support_threads_status_last", "support_threads", ["status", "last_message_at"]
    )
    op.create_index("ix_support_threads_last", "support_threads", ["last_message_at"])
    op.create_index(
        "ix_support_threads_customer_last",
        "support_threads",
        ["customer_user_id", "last_message_at"],
    )

    op.create_table(
        "support_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("author", sa.String(length=16), nullable=False),
        sa.Column("staff_user_id", sa.Uuid(), nullable=True),
        sa.Column("body", sa.String(length=2000), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "author IN ('customer', 'staff')", name=op.f("ck_support_messages_author_valid")
        ),
        sa.CheckConstraint(
            "char_length(body) BETWEEN 1 AND 2000", name=op.f("ck_support_messages_body_length")
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"],
            ["support_threads.id"],
            name=op.f("fk_support_messages_thread_id_support_threads"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["staff_user_id"],
            ["users.id"],
            name=op.f("fk_support_messages_staff_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_support_messages")),
    )
    op.create_index(
        "ix_support_messages_thread_created", "support_messages", ["thread_id", "created_at"]
    )

    _notification_checks(NEW_EVENTS, NEW_SUBJECTS)


def downgrade() -> None:
    newer = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM notification_logs WHERE subject_type = 'support'"))
        .scalar_one()
    )
    if newer:
        raise RuntimeError(
            f"Downgrade refused: {newer} support reply notification(s) exist. No row was changed."
        )
    _notification_checks(OLD_EVENTS, OLD_SUBJECTS)
    op.drop_index("ix_support_messages_thread_created", table_name="support_messages")
    op.drop_table("support_messages")
    op.drop_index("ix_support_threads_customer_last", table_name="support_threads")
    op.drop_index("ix_support_threads_last", table_name="support_threads")
    op.drop_index("ix_support_threads_status_last", table_name="support_threads")
    op.drop_table("support_threads")
