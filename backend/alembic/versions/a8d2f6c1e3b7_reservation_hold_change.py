"""inventory: an active hold's expiry may change, at most 24 hours after it was created

Approved by the project owner on 2026-10-27 (frontend phase 4 decision 2a). A customer may switch
an unpaid order's payment method (POST /payments/{order_number}/method), and the stock hold then
follows the new method's rule from the order's creation (15 minutes for mobile money, 24 hours
for cash on delivery; §7 Q11, Q13). Until now the stock_reservations_guard trigger made every
column but the status immutable. It now also lets expires_at change while the hold stays
'active', never beyond 24 hours after the hold was created (the longest approved hold), so the
database itself still bounds how long stock can be held. Everything else is unchanged: no
DELETE (apart from the development cleanup of b4e7d1a9c3f2), no other column, the same status
transitions.

Revision ID: a8d2f6c1e3b7
Revises: f1a7c3e9d2b4
Create Date: 2026-10-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a8d2f6c1e3b7"
down_revision: str | None = "f1a7c3e9d2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BODY = """
CREATE OR REPLACE FUNCTION stock_reservations_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF current_setting('app.dev_seed_cleanup', true) = 'on'
           AND pg_has_role(
               current_user,
               (SELECT relowner FROM pg_class WHERE oid = TG_RELID),
               'MEMBER'
           ) THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'stock_reservations rows are never deleted'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NEW.order_id <> OLD.order_id OR NEW.variant_id <> OLD.variant_id
       OR NEW.quantity <> OLD.quantity OR NEW.idempotency_key <> OLD.idempotency_key
       OR NEW.created_at <> OLD.created_at {expiry} THEN
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

_CAPPED = """OR (NEW.expires_at <> OLD.expires_at AND NOT (
           OLD.status = 'active' AND NEW.status = 'active'
           AND NEW.expires_at <= OLD.created_at + interval '24 hours'
       ))"""
_IMMUTABLE = "OR NEW.expires_at <> OLD.expires_at"


def upgrade() -> None:
    op.execute(_BODY.format(expiry=_CAPPED))


def downgrade() -> None:
    op.execute(_BODY.format(expiry=_IMMUTABLE))
