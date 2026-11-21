"""Checkout request fingerprint (module 14; plan §5 "14 — orders & checkout").

orders gains checkout_request_hash: the SHA-256 (hex) of the normalised checkout request, so a
retry with the same Idempotency-Key replays the original order only when it asks for the same
thing (address, payment method, contact details); a different request with a reused key is
refused (409). Existing orders keep NULL (they were not created by the checkout API); nothing
is changed or removed.

Downgrade drops the column and its check.

Revision ID: f3a8c6e1b5d9
Revises: d2f7a9c4e8b1
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3a8c6e1b5d9"
down_revision: str | Sequence[str] | None = "d2f7a9c4e8b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("checkout_request_hash", sa.String(length=64), nullable=True))
    op.create_check_constraint(
        op.f("ck_orders_checkout_request_hash_hex"),
        "orders",
        "checkout_request_hash IS NULL OR checkout_request_hash ~ '^[0-9a-f]{64}$'",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_orders_checkout_request_hash_hex"), "orders", type_="check")
    op.drop_column("orders", "checkout_request_hash")
