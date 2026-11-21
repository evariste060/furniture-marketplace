"""staff: finance role

Approved by the project owner on 2026-10-25 (plan §3): staff_role_assignments.role also accepts
'finance'. The downgrade fails loudly, rather than reassigning anyone, while a finance
assignment exists.

Revision ID: a7c2e4f9b1d3
Revises: f3a8c6e1b5d9
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7c2e4f9b1d3"
down_revision: str | Sequence[str] | None = "f3a8c6e1b5d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_staff_role_assignments_valid_role"
WITH_FINANCE = "role IN ('administrator', 'sales', 'operations', 'management', 'finance')"
WITHOUT_FINANCE = "role IN ('administrator', 'sales', 'operations', 'management')"


def upgrade() -> None:
    op.drop_constraint(op.f(CONSTRAINT), "staff_role_assignments", type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), "staff_role_assignments", WITH_FINANCE)


def downgrade() -> None:
    finance = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM staff_role_assignments WHERE role = 'finance'"))
        .scalar_one()
    )
    if finance:
        raise RuntimeError(
            f"{finance} staff user(s) hold the finance role. Give them another role, then "
            "re-run the downgrade."
        )
    op.drop_constraint(op.f(CONSTRAINT), "staff_role_assignments", type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), "staff_role_assignments", WITHOUT_FINANCE)
