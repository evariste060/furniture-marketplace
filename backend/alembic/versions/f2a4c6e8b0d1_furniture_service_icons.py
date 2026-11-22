"""Furniture service icons (ADR-014 phase 6): hammer, truck, ruler, sofa and paintbrush join
the icons staff choose for a service. The earlier icons stay valid, so no row changes.

Revision ID: f2a4c6e8b0d1
Revises: c6e8a0b2d4f7
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f2a4c6e8b0d1"
down_revision: str | None = "c6e8a0b2d4f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = ("cctv", "gate", "fingerprint", "network", "wrench", "graduation-cap", "shield", "cpu")
NEW = (*OLD, "hammer", "truck", "ruler", "sofa", "paintbrush")
NAME = "ck_service_categories_icon_valid"


def _check(icons: tuple[str, ...]) -> str:
    return "icon IN (" + ", ".join(f"'{icon}'" for icon in icons) + ")"


def upgrade() -> None:
    op.drop_constraint(op.f(NAME), "service_categories", type_="check")
    op.create_check_constraint(op.f(NAME), "service_categories", _check(NEW))


def downgrade() -> None:
    # Refuses (the constraint fails) while a service uses a furniture icon: change it first.
    op.drop_constraint(op.f(NAME), "service_categories", type_="check")
    op.create_check_constraint(op.f(NAME), "service_categories", _check(OLD))
