"""Invoices (module 16; plan §5 "16 — invoices"; §7 Q19; ADR-007).

invoices: one row per order (order_id unique), numbered INV-YYYY-NNNNNN (invoice_number unique),
with the issue time, the VAT-inclusive total, the extracted VAT and the issued document as a JSONB
snapshot. Written once by the issuing transaction; never updated or deleted (the runtime role
gets SELECT and INSERT only).

invoice_counters: the last number issued per year. The issuing transaction increments it under
its row lock, so a rolled-back issuance returns its number and committed numbers are
consecutive. Nothing is backfilled; downgrade drops both tables.

Revision ID: c5e8a2d7f4b1
Revises: a7c2e9d4f6b8
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c5e8a2d7f4b1"
down_revision: str | Sequence[str] | None = "a7c2e9d4f6b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invoices",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_number", sa.String(length=20), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total", sa.BigInteger(), nullable=False),
        sa.Column("vat_amount", sa.BigInteger(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "invoice_number ~ '^INV-[0-9]{4}-[0-9]{6}$'",
            name=op.f("ck_invoices_number_format"),
        ),
        sa.CheckConstraint(
            "total >= 0 AND total <= 999999999999 AND vat_amount >= 0 AND vat_amount <= total",
            name=op.f("ck_invoices_amounts_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_invoices_order_id_orders"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoices")),
        sa.UniqueConstraint("invoice_number", name="invoice_number"),
        sa.UniqueConstraint("order_id", name="order_id"),
    )
    op.create_table(
        "invoice_counters",
        sa.Column("year", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("last_number", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "last_number >= 1 AND last_number <= 999999",
            name=op.f("ck_invoice_counters_last_number_valid"),
        ),
        sa.CheckConstraint(
            "year BETWEEN 2000 AND 9999", name=op.f("ck_invoice_counters_year_valid")
        ),
        sa.PrimaryKeyConstraint("year", name=op.f("pk_invoice_counters")),
    )


def downgrade() -> None:
    op.drop_table("invoice_counters")
    op.drop_table("invoices")
