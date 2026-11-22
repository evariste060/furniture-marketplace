"""Seller orders: one store's part of a parent order (ADR-014 phase 3).

- seller_orders: one row per (order, store) with the store's own fulfilment status and the
  money snapshots taken at checkout (subtotal, the store's share of the order discount, the
  commission rate and amount, the seller's net amount).
- seller_order_status_history: append-only history of each seller order.
- order_items.store_id and store_name_snapshot ("Sold by"), and a deferred composite foreign
  key (order_id, store_id) -> seller_orders, so every line belongs to its store's seller order.

The upgrade refuses while any order exists: an existing line has no recorded store and no
commission snapshot, and the migration never guesses them. It reports the count and changes
nothing; a development database is emptied with the development tooling and reseeded. The
downgrade refuses while any seller order exists, so commission and fulfilment records are never
dropped silently. Runtime grants are in scripts/provision_runtime_role.py (seller_orders SELECT,
INSERT, UPDATE; the history SELECT, INSERT; no DELETE).

Revision ID: c6e8a0b2d4f7
Revises: b2d4f6a8c0e1
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c6e8a0b2d4f7"
down_revision: str | Sequence[str] | None = "b2d4f6a8c0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = "'pending', 'confirmed', 'processing', 'dispatched', 'delivered', 'cancelled'"


def upgrade() -> None:
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM orders")).scalar_one()
    if count:
        raise RuntimeError(
            f"Upgrade refused: every order line must belong to a store's seller order (ADR-014 "
            f"phase 3), and {count} orders exist without one. No order was changed. Remove the "
            "development orders with the development tooling, upgrade, then reseed."
        )

    op.create_table(
        "seller_orders",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("store_name_snapshot", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("subtotal", sa.BigInteger(), nullable=False),
        sa.Column("discount_total", sa.BigInteger(), nullable=False),
        sa.Column("merchandise_total", sa.BigInteger(), nullable=False),
        sa.Column("commission_rate_bps", sa.Integer(), nullable=False),
        sa.Column("commission_amount", sa.BigInteger(), nullable=False),
        sa.Column("seller_net_amount", sa.BigInteger(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(f"status IN ({STATUSES})", name=op.f("ck_seller_orders_valid_status")),
        sa.CheckConstraint(
            "commission_amount + seller_net_amount = merchandise_total",
            name=op.f("ck_seller_orders_commission_and_net_make_merchandise"),
        ),
        sa.CheckConstraint(
            "commission_rate_bps BETWEEN 0 AND 10000",
            name=op.f("ck_seller_orders_commission_rate_in_range"),
        ),
        sa.CheckConstraint(
            "merchandise_total = subtotal - discount_total",
            name=op.f("ck_seller_orders_merchandise_is_net_of_discount"),
        ),
        sa.CheckConstraint(
            "subtotal <= 999999999999", name=op.f("ck_seller_orders_amounts_within_cap")
        ),
        sa.CheckConstraint(
            "subtotal >= 0 AND discount_total >= 0 AND commission_amount >= 0 "
            "AND seller_net_amount >= 0",
            name=op.f("ck_seller_orders_amounts_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_seller_orders_order_id_orders"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name=op.f("fk_seller_orders_store_id_stores"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_seller_orders")),
        sa.UniqueConstraint("order_id", "store_id", name="order_store"),
    )
    op.create_index(
        "ix_seller_orders_store_status_created",
        "seller_orders",
        ["store_id", "status", "created_at"],
        unique=False,
    )
    op.create_table(
        "seller_order_status_history",
        sa.Column("seller_order_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
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
            f"status IN ({STATUSES})", name=op.f("ck_seller_order_status_history_valid_status")
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_seller_order_status_history_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["seller_order_id"],
            ["seller_orders.id"],
            name=op.f("fk_seller_order_status_history_seller_order_id_seller_orders"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_seller_order_status_history")),
    )
    op.create_index(
        "ix_seller_order_status_history_order_created",
        "seller_order_status_history",
        ["seller_order_id", "created_at"],
        unique=False,
    )
    op.add_column("order_items", sa.Column("store_id", sa.Uuid(), nullable=False))
    op.add_column(
        "order_items", sa.Column("store_name_snapshot", sa.String(length=120), nullable=False)
    )
    op.create_foreign_key(
        op.f("fk_order_items_store_id_stores"),
        "order_items",
        "stores",
        ["store_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_order_items_seller_order",
        "order_items",
        "seller_orders",
        ["order_id", "store_id"],
        ["order_id", "store_id"],
        ondelete="RESTRICT",
        initially="DEFERRED",
        deferrable=True,
    )


def downgrade() -> None:
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM seller_orders")).scalar_one()
    if count:
        raise RuntimeError(
            f"Downgrade refused: {count} seller orders exist, with their fulfilment statuses and "
            "commission snapshots. No row was changed."
        )
    op.drop_constraint("fk_order_items_seller_order", "order_items", type_="foreignkey")
    op.drop_constraint(op.f("fk_order_items_store_id_stores"), "order_items", type_="foreignkey")
    op.drop_column("order_items", "store_name_snapshot")
    op.drop_column("order_items", "store_id")
    op.drop_index(
        "ix_seller_order_status_history_order_created", table_name="seller_order_status_history"
    )
    op.drop_table("seller_order_status_history")
    op.drop_index("ix_seller_orders_store_status_created", table_name="seller_orders")
    op.drop_table("seller_orders")
