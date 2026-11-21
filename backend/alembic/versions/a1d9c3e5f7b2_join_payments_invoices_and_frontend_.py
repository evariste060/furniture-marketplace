"""merge: join the payments/invoices and frontend phase 1 migration heads

Modules 15 and 16 (payment event metadata, invoices) and the frontend phase 1 backend (finance
role, catalogue media, media registry, job queue, SKU rules, banners) both branched from
f3a8c6e1b5d9. This revision only joins the two heads; it changes no schema. Existing databases on
either head upgrade through it unchanged.

Revision ID: a1d9c3e5f7b2
Revises: c5e8a2d7f4b1, f8c3e7a9b4d5
Create Date: 2026-10-26
"""

from collections.abc import Sequence

revision: str = "a1d9c3e5f7b2"
down_revision: str | Sequence[str] | None = ("c5e8a2d7f4b1", "f8c3e7a9b4d5")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
