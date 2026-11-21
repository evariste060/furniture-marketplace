"""notifications: one outbox for every transactional message (approved 2026-11-02)

notification_logs held only the four order status messages (confirmed, dispatched, delivered,
cancelled), one per order, event and channel. The transactional email work adds messages that
belong to other records, or to the same order more than once, so the table changes to:

- subject_type ('order', 'user', 'quote', 'review') and subject_id: the record a message is
  rendered from when it is sent (no message text is stored, as before);
- order_id becomes optional: set exactly for order messages, and then equal to subject_id;
- dedupe_key (unique) replaces the unique (order_id, event, channel): one message per event,
  subject, channel and, for the staff new-order alert, recipient;
- event: up to 24 characters, adding received, staff_new_order, payment_succeeded, welcome,
  quote_received and review_thanks.

Existing rows are order messages: subject_type 'order', subject_id their order_id and dedupe_key
'order:<order id>:<event>:<channel>', the key the API uses for those messages, so an existing
message is never sent again.

The downgrade restores the old shape. It stops with a message instead of deleting rows when a
message of a new kind exists.

Revision ID: c7e2a9f4d1b6
Revises: b2f6d8e4a1c9
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7e2a9f4d1b6"
down_revision: str | Sequence[str] | None = "b2f6d8e4a1c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_EVENTS = ("confirmed", "dispatched", "delivered", "cancelled")
NEW_EVENTS = (
    *OLD_EVENTS,
    "received",
    "staff_new_order",
    "payment_succeeded",
    "welcome",
    "quote_received",
    "review_thanks",
)


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    op.add_column("notification_logs", sa.Column("subject_type", sa.String(16), nullable=True))
    op.add_column("notification_logs", sa.Column("subject_id", sa.Uuid(), nullable=True))
    op.add_column("notification_logs", sa.Column("dedupe_key", sa.String(400), nullable=True))
    op.execute(
        "UPDATE notification_logs SET subject_type = 'order', subject_id = order_id, "
        "dedupe_key = 'order:' || order_id::text || ':' || event || ':' || channel"
    )
    for column in ("subject_type", "subject_id", "dedupe_key"):
        op.alter_column("notification_logs", column, nullable=False)
    op.alter_column("notification_logs", "order_id", nullable=True)
    op.alter_column("notification_logs", "event", type_=sa.String(24), existing_type=sa.String(16))
    op.drop_constraint(op.f("order_event_channel"), "notification_logs", type_="unique")
    op.create_unique_constraint(
        op.f("uq_notification_logs_dedupe_key"), "notification_logs", ["dedupe_key"]
    )
    op.drop_constraint(op.f("ck_notification_logs_valid_event"), "notification_logs", type_="check")
    op.create_check_constraint(
        op.f("ck_notification_logs_valid_event"), "notification_logs", _in("event", NEW_EVENTS)
    )
    op.create_check_constraint(
        op.f("ck_notification_logs_valid_subject_type"),
        "notification_logs",
        _in("subject_type", ("order", "user", "quote", "review")),
    )
    op.create_check_constraint(
        op.f("ck_notification_logs_order_subject_matches"),
        "notification_logs",
        "(subject_type = 'order') = (order_id IS NOT NULL) "
        "AND (order_id IS NULL OR subject_id = order_id)",
    )


def downgrade() -> None:
    newer = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM notification_logs "
                "WHERE order_id IS NULL OR NOT " + _in("event", OLD_EVENTS)
            )
        )
        .scalar_one()
    )
    if newer:
        raise RuntimeError(
            f"Downgrade refused: {newer} notification(s) of the newer kinds exist; the old "
            "notification_logs shape cannot hold them. No row was changed."
        )
    op.drop_constraint(
        op.f("ck_notification_logs_order_subject_matches"), "notification_logs", type_="check"
    )
    op.drop_constraint(
        op.f("ck_notification_logs_valid_subject_type"), "notification_logs", type_="check"
    )
    op.drop_constraint(op.f("ck_notification_logs_valid_event"), "notification_logs", type_="check")
    op.create_check_constraint(
        op.f("ck_notification_logs_valid_event"), "notification_logs", _in("event", OLD_EVENTS)
    )
    op.drop_constraint(op.f("uq_notification_logs_dedupe_key"), "notification_logs", type_="unique")
    op.create_unique_constraint(
        op.f("order_event_channel"), "notification_logs", ["order_id", "event", "channel"]
    )
    op.alter_column("notification_logs", "event", type_=sa.String(16), existing_type=sa.String(24))
    op.alter_column("notification_logs", "order_id", nullable=False)
    for column in ("dedupe_key", "subject_id", "subject_type"):
        op.drop_column("notification_logs", column)
