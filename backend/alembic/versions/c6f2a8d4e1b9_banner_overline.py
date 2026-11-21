"""content: optional banner overline

Approved by the project owner on 2026-10-27 (frontend phase 2 decision 6). The homepage hero
shows a short line above the title (Main.dc.html "Latest electronics, better everyday life").
Banners get an optional overline in English and Kinyarwanda, at most 40 characters each; the
storefront shows it only when present. Existing banners get none.

Revision ID: c6f2a8d4e1b9
Revises: b4e7d1a9c3f2
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c6f2a8d4e1b9"
down_revision: str | None = "b4e7d1a9c3f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("banners", sa.Column("overline_en", sa.String(length=40), nullable=True))
    op.add_column("banners", sa.Column("overline_rw", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("banners", "overline_rw")
    op.drop_column("banners", "overline_en")
