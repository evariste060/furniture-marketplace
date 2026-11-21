"""Add order fulfilment assignment.

Revision ID: d4a6c2b8f031
Revises: c3a8e5f1d2b4
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4a6c2b8f031"
down_revision: str | Sequence[str] | None = "c3a8e5f1d2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("fulfilment_assignee_user_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_orders_fulfilment_assignee_user_id_users",
        "orders",
        "users",
        ["fulfilment_assignee_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_orders_fulfilment_assignee_user_id",
        "orders",
        ["fulfilment_assignee_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_orders_fulfilment_assignee_user_id", table_name="orders")
    op.drop_constraint("fk_orders_fulfilment_assignee_user_id_users", "orders", type_="foreignkey")
    op.drop_column("orders", "fulfilment_assignee_user_id")
