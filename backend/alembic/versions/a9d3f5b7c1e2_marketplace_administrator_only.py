"""staff: the Marketplace Administrator is the only staff role (SC-05)

Approved by the project owner on 2026-11-21: FurniHub keeps only the administrator staff role;
sales, operations, management and finance are removed. staff_role_assignments.role then accepts
'administrator' only.

The upgrade refuses to run while any staff assignment holds another role: it never converts,
disables or deletes an account. Reassign or retire those accounts deliberately first. Only the
count per role is reported, never who holds it. The downgrade restores the five-role check and
changes no rows.

Revision ID: a9d3f5b7c1e2
Revises: f4c8a2e6b9d3
Create Date: 2026-11-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a9d3f5b7c1e2"
down_revision: str | Sequence[str] | None = "f4c8a2e6b9d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_staff_role_assignments_valid_role"
ADMINISTRATOR_ONLY = "role IN ('administrator')"
FIVE_ROLES = "role IN ('administrator', 'sales', 'operations', 'management', 'finance')"


def upgrade() -> None:
    others = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT role, count(*) FROM staff_role_assignments "
                "WHERE role <> 'administrator' GROUP BY role ORDER BY role"
            )
        )
        .all()
    )
    if others:
        held = ", ".join(f"{role}: {count}" for role, count in others)
        raise RuntimeError(
            "SC-05 keeps only the Marketplace Administrator staff role, but staff assignments "
            f"with other roles exist ({held}). No account was changed. Make each of these "
            "accounts an administrator or retire it deliberately, then re-run the upgrade."
        )
    op.drop_constraint(op.f(CONSTRAINT), "staff_role_assignments", type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), "staff_role_assignments", ADMINISTRATOR_ONLY)


def downgrade() -> None:
    op.drop_constraint(op.f(CONSTRAINT), "staff_role_assignments", type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), "staff_role_assignments", FIVE_ROLES)
