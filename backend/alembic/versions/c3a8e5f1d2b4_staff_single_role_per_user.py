"""staff: exactly one role per staff user

ADR-006 (approved 2026-10-22): each staff user holds a single role. Replaces the (user_id, role)
unique constraint with a unique constraint on user_id. Fails loudly, rather than choosing a role
on the operator's behalf, if any user currently holds more than one role.

Revision ID: c3a8e5f1d2b4
Revises: 9b3e5d2a1c07
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3a8e5f1d2b4"
down_revision: str | Sequence[str] | None = "9b3e5d2a1c07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conflicts = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM (SELECT user_id FROM staff_role_assignments "
                "GROUP BY user_id HAVING count(*) > 1) AS multi"
            )
        )
        .scalar_one()
    )
    if conflicts:
        raise RuntimeError(
            f"{conflicts} user(s) hold more than one staff role. Keep exactly one role per user "
            "in staff_role_assignments, then re-run the migration."
        )
    op.drop_constraint("staff_user_role", "staff_role_assignments", type_="unique")
    op.create_unique_constraint(
        op.f("uq_staff_role_assignments_user_id"), "staff_role_assignments", ["user_id"]
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("uq_staff_role_assignments_user_id"), "staff_role_assignments", type_="unique"
    )
    op.create_unique_constraint("staff_user_role", "staff_role_assignments", ["user_id", "role"])
