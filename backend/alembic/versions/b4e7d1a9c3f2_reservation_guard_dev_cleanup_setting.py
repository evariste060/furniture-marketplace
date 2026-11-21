"""Let the development seed cleanup delete its own stock reservations (2026-10-27).

The stock_reservations_guard trigger refuses every DELETE. The development seed cleanup
(scripts/seed_development_catalogue.py --cleanup) used to switch the trigger off with
ALTER TABLE ... DISABLE TRIGGER, which needs table ownership and affects every session. It now
runs `SET LOCAL app.dev_seed_cleanup = 'on'` inside its own transaction instead, and the guard
lets a DELETE through only when both hold:

- the setting is 'on' in the current transaction (SET LOCAL ends with the transaction), and
- the current user is a member of the table's owner role (the migration/owner account).

The runtime role cannot use it: it has no DELETE privilege on stock_reservations, so PostgreSQL
refuses the statement before the trigger runs, and it is not a member of the owner role either.

Revision ID: b4e7d1a9c3f2
Revises: a1d9c3e5f7b2
Create Date: 2026-10-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b4e7d1a9c3f2"
down_revision: str | None = "a1d9c3e5f7b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BODY = """
CREATE OR REPLACE FUNCTION stock_reservations_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        {cleanup}RAISE EXCEPTION 'stock_reservations rows are never deleted'
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

_CLEANUP = """IF current_setting('app.dev_seed_cleanup', true) = 'on'
           AND pg_has_role(
               current_user,
               (SELECT relowner FROM pg_class WHERE oid = TG_RELID),
               'MEMBER'
           ) THEN
            RETURN OLD;
        END IF;
        """


def upgrade() -> None:
    op.execute(_BODY.format(cleanup=_CLEANUP))


def downgrade() -> None:
    op.execute(_BODY.format(cleanup=""))
