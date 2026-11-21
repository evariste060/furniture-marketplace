"""Payment event metadata (module 15; plan §5 "15 — payments").

payment_events gains payload_metadata: sanitised provider facts (allow-listed fields, masked
phone numbers, never card data or secrets). Existing events get '{}'; nothing is changed or
removed. Downgrade drops the column.

Revision ID: a7c2e9d4f6b8
Revises: f3a8c6e1b5d9
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a7c2e9d4f6b8"
down_revision: str | Sequence[str] | None = "f3a8c6e1b5d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "payment_events",
        sa.Column(
            "payload_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("payment_events", "payload_metadata")
