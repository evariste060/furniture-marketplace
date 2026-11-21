"""Merge order fulfilment assignment and inventory reservation guards.

Both revisions branch from c3a8e5f1d2b4 and touch disjoint objects (orders column vs
stock_reservations guards), so the merge applies no schema change.

Revision ID: e1b7f3c9a5d2
Revises: d4a6c2b8f031, d7c4a9e2b6f1
"""

from collections.abc import Sequence

revision: str = "e1b7f3c9a5d2"
down_revision: str | Sequence[str] | None = ("d4a6c2b8f031", "d7c4a9e2b6f1")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
