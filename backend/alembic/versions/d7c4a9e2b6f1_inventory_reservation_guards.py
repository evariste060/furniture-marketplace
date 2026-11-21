"""Database guards for the approved stock reservation lifecycle (ADR-002, 2026-10-22).

- stock_reservations: only approved status transitions (active -> committed | released | expired,
  committed -> fulfilled); order, SKU, quantity, idempotency key and expiry are immutable; rows
  are never deleted; a reservation must expire after it was created.
- Allocation guard (deferred, checked at commit): active + committed reservations for a SKU can
  never exceed its reservable physical stock (on_hand - unavailable_quantity). It fires when a
  reservation is created and when physical stock is reduced, and locks the balance row first so
  concurrent writers are checked one at a time. The services already enforce this with row
  locks; these triggers are a last line of defence against faulty future code.

Revision ID: d7c4a9e2b6f1
Revises: c3a8e5f1d2b4
Create Date: 2026-10-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d7c4a9e2b6f1"
down_revision: str | None = "c3a8e5f1d2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        op.f("ck_stock_reservations_expires_after_created"),
        "stock_reservations",
        "expires_at > created_at",
    )

    op.execute(
        """
        CREATE FUNCTION stock_reservations_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'stock_reservations rows are never deleted'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            IF NEW.order_id <> OLD.order_id OR NEW.variant_id <> OLD.variant_id
               OR NEW.quantity <> OLD.quantity OR NEW.idempotency_key <> OLD.idempotency_key
               OR NEW.expires_at <> OLD.expires_at OR NEW.created_at <> OLD.created_at THEN
                RAISE EXCEPTION 'stock reservation % is immutable apart from its status', OLD.id
                    USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.status <> OLD.status AND NOT (
                (OLD.status = 'active' AND NEW.status IN ('committed', 'released', 'expired'))
                OR (OLD.status = 'committed' AND NEW.status = 'fulfilled')
            ) THEN
                RAISE EXCEPTION 'invalid stock reservation transition % -> %',
                    OLD.status, NEW.status USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER stock_reservations_guard
        BEFORE UPDATE OR DELETE ON stock_reservations
        FOR EACH ROW EXECUTE FUNCTION stock_reservations_guard()
        """
    )

    op.execute(
        """
        CREATE FUNCTION inventory_allocation_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            physical integer;
            allocated bigint;
        BEGIN
            -- Lock first, then read in a new statement, so concurrent writers are serialised
            -- and each check sees every committed allocation.
            PERFORM 1 FROM inventory_balances WHERE variant_id = NEW.variant_id FOR UPDATE;
            SELECT on_hand - unavailable_quantity INTO physical
              FROM inventory_balances WHERE variant_id = NEW.variant_id;
            SELECT coalesce(sum(quantity), 0) INTO allocated
              FROM stock_reservations
             WHERE variant_id = NEW.variant_id AND status IN ('active', 'committed');
            IF allocated > coalesce(physical, 0) THEN
                RAISE EXCEPTION 'stock allocation % exceeds reservable stock % for SKU %',
                    allocated, coalesce(physical, 0), NEW.variant_id
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER stock_reservations_allocation_guard
        AFTER INSERT ON stock_reservations
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW WHEN (NEW.status IN ('active', 'committed'))
        EXECUTE FUNCTION inventory_allocation_guard()
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER inventory_balances_allocation_guard
        AFTER UPDATE ON inventory_balances
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW WHEN (
            NEW.on_hand < OLD.on_hand
            OR NEW.unavailable_quantity > OLD.unavailable_quantity
            OR NEW.variant_id <> OLD.variant_id
        )
        EXECUTE FUNCTION inventory_allocation_guard()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS inventory_balances_allocation_guard ON inventory_balances")
    op.execute("DROP TRIGGER IF EXISTS stock_reservations_allocation_guard ON stock_reservations")
    op.execute("DROP FUNCTION IF EXISTS inventory_allocation_guard()")
    op.execute("DROP TRIGGER IF EXISTS stock_reservations_guard ON stock_reservations")
    op.execute("DROP FUNCTION IF EXISTS stock_reservations_guard()")
    op.drop_constraint(
        op.f("ck_stock_reservations_expires_after_created"), "stock_reservations", type_="check"
    )
