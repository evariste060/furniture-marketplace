"""stores: marketplace stores and seller applications (ADR-014 phase 1, SC-04, 2026-11-21)

- stores: one seller's shop and its application (pending, approved, rejected, suspended). One
  store per user (owner_user_id unique), names unique regardless of letter case, an optional
  commission override in basis points (NULL inherits marketplace.default_commission_bps).
- store_status_history: append-only, one row per submission and per administrator decision,
  with the reason and the store name as they were; each row is the subject of its email.
- media_objects.owner_type also allows 'stores' (logo and cover, phase 2 uploads).
- notification_logs: the five store events about a 'store_status' subject; event widened from
  24 to 32 characters ('store_application_received' is 26).

No rows are inserted: the 10% default commission is the code default while the setting is unset.

Revision ID: f4c8a2e6b9d3
Revises: e5a1c7d9b3f2 (services)
Create Date: 2026-11-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f4c8a2e6b9d3"
down_revision: str | Sequence[str] | None = "e5a1c7d9b3f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_OWNERS = ("products", "categories", "brands", "banners", "jobs", "services")
NEW_OWNERS = (*OLD_OWNERS, "stores")
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
    "support_reply",
    "service_received",
)
STORE_EVENTS = (
    "store_application_received",
    "store_approved",
    "store_rejected",
    "store_suspended",
    "store_reinstated",
)
NEW_EVENTS = (*OLD_EVENTS, *STORE_EVENTS)
OLD_SUBJECTS = ("order", "user", "quote", "review", "support", "service")
NEW_SUBJECTS = (*OLD_SUBJECTS, "store_status")
STATUSES = "status IN ('pending', 'approved', 'rejected', 'suspended')"


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def _checks(owners: Sequence[str], events: Sequence[str], subjects: Sequence[str]) -> None:
    op.drop_constraint(op.f("ck_media_objects_valid_owner_type"), "media_objects", type_="check")
    op.create_check_constraint(
        op.f("ck_media_objects_valid_owner_type"), "media_objects", _in("owner_type", owners)
    )
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


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def _media_fk(column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column],
        ["media_objects.id"],
        name=op.f(f"fk_stores_{column}_media_objects"),
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.alter_column(
        "notification_logs",
        "event",
        existing_type=sa.String(length=24),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
    _checks(NEW_OWNERS, NEW_EVENTS, NEW_SUBJECTS)
    op.create_table(
        "stores",
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=140), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("contact_email", sa.String(length=254), nullable=False),
        sa.Column("contact_phone", sa.String(length=13), nullable=False),
        sa.Column("district", sa.String(length=120), nullable=False),
        sa.Column("sector", sa.String(length=120), nullable=True),
        sa.Column("street_address", sa.String(length=240), nullable=True),
        sa.Column("logo_media_id", sa.Uuid(), nullable=True),
        sa.Column("logo_original_media_id", sa.Uuid(), nullable=True),
        sa.Column("cover_media_id", sa.Uuid(), nullable=True),
        sa.Column("cover_original_media_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("status_reason", sa.String(length=500), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("commission_rate_bps", sa.Integer(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(STATUSES, name=op.f("ck_stores_valid_status")),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'", name=op.f("ck_stores_slug_format")
        ),
        sa.CheckConstraint("char_length(btrim(name)) >= 2", name=op.f("ck_stores_name_not_blank")),
        sa.CheckConstraint(
            "description IS NULL OR char_length(description) <= 2000",
            name=op.f("ck_stores_description_length"),
        ),
        sa.CheckConstraint(
            "contact_email = lower(contact_email)", name=op.f("ck_stores_contact_email_lower")
        ),
        sa.CheckConstraint(
            r"contact_phone ~ '^\+2507[0-9]{8}$'", name=op.f("ck_stores_contact_phone_canonical")
        ),
        sa.CheckConstraint(
            "(status IN ('rejected', 'suspended')) = (status_reason IS NOT NULL)",
            name=op.f("ck_stores_reason_matches_status"),
        ),
        sa.CheckConstraint(
            "commission_rate_bps IS NULL OR commission_rate_bps BETWEEN 0 AND 10000",
            name=op.f("ck_stores_commission_rate_range"),
        ),
        sa.CheckConstraint(
            "status = 'pending' OR (reviewed_at IS NOT NULL)",
            name=op.f("ck_stores_reviewed_when_decided"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('approved', 'suspended') OR approved_at IS NOT NULL",
            name=op.f("ck_stores_approved_at_once_approved"),
        ),
        sa.CheckConstraint(
            "(logo_media_id IS NULL) = (logo_original_media_id IS NULL)",
            name=op.f("ck_stores_logo_media_together"),
        ),
        sa.CheckConstraint(
            "(cover_media_id IS NULL) = (cover_original_media_id IS NULL)",
            name=op.f("ck_stores_cover_media_together"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_stores_owner_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["users.id"],
            name=op.f("fk_stores_reviewed_by_user_id_users"),
            ondelete="SET NULL",
        ),
        _media_fk("logo_media_id"),
        _media_fk("logo_original_media_id"),
        _media_fk("cover_media_id"),
        _media_fk("cover_original_media_id"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stores")),
        sa.UniqueConstraint("owner_user_id", name="uq_stores_owner_user_id"),
        sa.UniqueConstraint("slug", name="uq_stores_slug"),
        sa.UniqueConstraint("logo_media_id", name=op.f("uq_stores_logo_media_id")),
        sa.UniqueConstraint(
            "logo_original_media_id", name=op.f("uq_stores_logo_original_media_id")
        ),
        sa.UniqueConstraint("cover_media_id", name=op.f("uq_stores_cover_media_id")),
        sa.UniqueConstraint(
            "cover_original_media_id", name=op.f("uq_stores_cover_original_media_id")
        ),
    )
    op.create_index("uq_stores_name_lower", "stores", [sa.text("lower(name)")], unique=True)
    op.create_index("ix_stores_status_submitted", "stores", ["status", "submitted_at"])
    op.create_table(
        "store_status_history",
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("store_name", sa.String(length=120), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(STATUSES, name=op.f("ck_store_status_history_valid_status")),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name=op.f("fk_store_status_history_store_id_stores"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_store_status_history_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_store_status_history")),
    )
    op.create_index(
        "ix_store_status_history_store_created",
        "store_status_history",
        ["store_id", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    stores = bind.execute(sa.text("SELECT count(*) FROM stores")).scalar_one()
    messages = bind.execute(
        sa.text("SELECT count(*) FROM notification_logs WHERE subject_type = 'store_status'")
    ).scalar_one()
    media = bind.execute(
        sa.text("SELECT count(*) FROM media_objects WHERE owner_type = 'stores'")
    ).scalar_one()
    if stores or messages or media:
        raise RuntimeError(
            f"Downgrade refused: {stores} store(s), {messages} store notification(s) and "
            f"{media} store media file(s) exist. No row was changed."
        )
    op.drop_index("ix_store_status_history_store_created", table_name="store_status_history")
    op.drop_table("store_status_history")
    op.drop_index("ix_stores_status_submitted", table_name="stores")
    op.drop_index("uq_stores_name_lower", table_name="stores")
    op.drop_table("stores")
    _checks(OLD_OWNERS, OLD_EVENTS, OLD_SUBJECTS)
    op.alter_column(
        "notification_logs",
        "event",
        existing_type=sa.String(length=32),
        type_=sa.String(length=24),
        existing_nullable=False,
    )
