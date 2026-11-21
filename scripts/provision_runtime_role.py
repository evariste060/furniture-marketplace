"""Create or update the least-privilege application runtime role and its grants.

Run from backend/ after every `alembic upgrade`:

    uv run python ../scripts/provision_runtime_role.py --dotenv

Settings come from the process environment only, so a missing value can never fall back to
another database. --dotenv also reads backend/.env (local development; the environment wins):
- MIGRATION_DATABASE_URL: the schema-owner account the script connects as.
- DATABASE_URL: the runtime account to create or update; its user name and password are reused,
  so the password is kept in one place. RUNTIME_DB_ROLE / RUNTIME_DB_PASSWORD override them.
The script refuses to run if the runtime account is the owner account.

Everything runs in one transaction, so a failure leaves the role, its password and its grants as
they were. A new role is created with no elevated attributes. For an existing role only LOGIN and
the password are set (a non-superuser owner, as on a managed database, may not change SUPERUSER,
not even to the value it already has), and the script refuses if the role has an elevated
attribute.

The runtime role (DATABASE_URL: the API and the expiry job) gets only what built features need
(see TABLE_GRANTS). Checkout (module 14) inserts orders, their line snapshots (order_items:
SELECT, INSERT), their stock holds (stock_reservations: SELECT, INSERT, UPDATE) and their first
payment attempt (payment_attempts: SELECT, INSERT, UPDATE); fulfilment, cancellation and the
expiry job update order and attempt status and add status-history rows. Nothing on these tables
is ever deleted. Payments (module 15) also initiate attempts and record payment events
(payment_events: SELECT, INSERT, UPDATE; never deleted): signature-verified provider webhooks and
the service's own reconciliation records, which are not verified provider evidence. Invoices
(module 16) are inserted once and read (invoices: SELECT, INSERT), numbered from a per-year
counter (invoice_counters: SELECT, INSERT, UPDATE); neither is ever deleted. Order
notifications (module 17) are inserted with the order change and updated as they are sent or
retried, by the API and scripts/retry_notifications.py (notification_logs: SELECT, INSERT,
UPDATE; never deleted). Policy pages (module 19) are written by staff and read by the public,
and business quote requests are sent by visitors and followed up by staff (pages, quote_requests:
SELECT, INSERT, UPDATE; never deleted). Support conversations are started by visitors and
customers and answered by staff (support_threads: SELECT, INSERT, UPDATE; support_messages:
SELECT, INSERT, as messages are never edited; neither is deleted). Tables without a built feature
get no privileges; extend TABLE_GRANTS in the same change that needs a privilege.
It is not a superuser, cannot create roles/databases, and owns no table, so it cannot drop or
disable the append-only audit trigger. Secrets are never printed.
"""

import argparse
import os
import re
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import sql
from sqlalchemy.engine import make_url

BACKEND_ENV = Path(__file__).resolve().parents[1] / "backend" / ".env"
ELEVATED_ATTRIBUTES = ("rolsuper", "rolcreaterole", "rolcreatedb", "rolreplication", "rolbypassrls")

TABLE_GRANTS: dict[str, tuple[str, ...]] = {
    "users": ("SELECT", "INSERT", "UPDATE"),  # register, profile; no deletes from the API
    "user_sessions": ("SELECT", "INSERT", "UPDATE"),  # login, touch, revoke
    # Password reset: issue a code, count attempts, mark used or superseded; never deleted here.
    "password_reset_codes": ("SELECT", "INSERT", "UPDATE"),
    # Email verification (ADR-006 amendment 2026-11-12): links are issued, then consumed or
    # revoked in place; never deleted by the API.
    "email_verification_tokens": ("SELECT", "INSERT", "UPDATE"),
    # Continue with Google (ADR-006 amendment 2026-11-11): link and use Google identities (never
    # deleted by the API); sign-in flows are created, consumed once, and expired ones deleted.
    "oauth_identities": ("SELECT", "INSERT", "UPDATE"),
    "oauth_login_flows": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "addresses": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    # Staff provisioning and role changes (one row per staff user, updated in place); no deletes.
    "staff_role_assignments": ("SELECT", "INSERT", "UPDATE"),
    "audit_records": ("SELECT", "INSERT"),  # append-only
    "alembic_version": ("SELECT",),
    # Public catalogue reads; staff category and brand management (module 5) creates, edits
    # (UPDATE also covers SELECT ... FOR UPDATE) and deletes unused rows.
    "categories": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "brands": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "category_menu_brands": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "brand_categories": ("SELECT", "INSERT", "DELETE"),
    # Public catalogue reads; staff product and variant management (module 6) creates and edits
    # (UPDATE also covers SELECT ... FOR UPDATE). No DELETE: a variant DELETE deactivates it.
    "products": ("SELECT", "INSERT", "UPDATE"),
    "product_variants": ("SELECT", "INSERT", "UPDATE"),
    # Public catalogue reads; staff image management (module 7) uploads, edits and deletes rows
    # (UPDATE also covers SELECT ... FOR UPDATE). Deleting an image removes it and its files.
    "product_images": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    # Media registry (ADR-009, 2026-10-26): the API registers files (pending), activates and
    # retires them; it deletes the rows of a failed upload. The cleanup worker (same role)
    # deletes retired rows after their files (UPDATE also covers SELECT ... FOR UPDATE).
    "media_objects": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    # Job queue (2026-10-26): the API creates jobs and items and requeues failed items; the worker
    # (same role) claims items (UPDATE also covers SELECT ... FOR UPDATE SKIP LOCKED) and records
    # their outcome. Jobs are kept as a record; no deletes.
    "jobs": ("SELECT", "INSERT", "UPDATE"),
    # Homepage banners (2026-10-26): staff create, edit and delete them (content:manage).
    "banners": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "job_items": ("SELECT", "INSERT", "UPDATE"),
    # Catalogue import jobs (module 8): created as processing, then finished in place (UPDATE
    # also covers SELECT ... FOR UPDATE). Jobs are kept; no deletes.
    "import_jobs": ("SELECT", "INSERT", "UPDATE"),
    # Carts (module 11): one active cart per customer or guest token, created, then updated
    # (expiry, merge -> converted, expired -> abandoned); never deleted. Lines are added,
    # changed and removed (UPDATE also covers SELECT ... FOR UPDATE).
    "carts": ("SELECT", "INSERT", "UPDATE"),
    "cart_items": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    # Delivery (module 12): zones are created and edited (UPDATE also covers SELECT ... FOR
    # UPDATE), never deleted. A fee change closes the active rule in place (UPDATE) and inserts
    # its replacement; rules are never deleted, so the fee history is kept.
    "delivery_zones": ("SELECT", "INSERT", "UPDATE"),
    "delivery_fee_rules": ("SELECT", "INSERT", "UPDATE"),
    # Settings (module 12; module 19 adds keys): read, and upserted by administrators; never
    # deleted.
    "settings": ("SELECT", "INSERT", "UPDATE"),
    # Promotions (module 13): codes are created and edited (UPDATE also covers SELECT ... FOR
    # UPDATE, the row lock checkout takes on a code), never deleted. Targets are replaced as a
    # set when an administrator changes them, so they are deleted and re-inserted. Redemptions
    # are inserted at checkout and released in place (cancellation, the expiry job); never
    # deleted.
    "discounts": ("SELECT", "INSERT", "UPDATE"),
    "discount_targets": ("SELECT", "INSERT", "DELETE"),
    "discount_redemptions": ("SELECT", "INSERT", "UPDATE"),
    # Orders. SELECT ... FOR UPDATE row locks need UPDATE; INSERT ... RETURNING of
    # server-default timestamps needs SELECT. Checkout (module 14) inserts the order, its lines
    # and its first payment attempt; fulfilment updates status and assignee; nothing is deleted.
    "orders": ("SELECT", "INSERT", "UPDATE"),
    "order_items": ("SELECT", "INSERT"),  # snapshots, never changed after checkout
    "order_status_history": ("SELECT", "INSERT"),  # one row per status change
    # Payment attempts (module 14): checkout records the chosen method; status changes follow
    # §7 Q12-Q14 (cancelled, expired, cash on delivery succeeded on delivery). Never deleted.
    "payment_attempts": ("SELECT", "INSERT", "UPDATE"),
    # Payment events (module 15): each signature-verified webhook is inserted once (provider,
    # event_key) and then marked processed or needs_reconciliation in place; the service also
    # inserts its own reconciliation records (provider 'internal', verification_status
    # 'received': not verified provider evidence) and links early events to their attempt.
    # Never deleted.
    "payment_events": ("SELECT", "INSERT", "UPDATE"),
    # Invoices (module 16): inserted once by the transaction that records the payment success
    # (or the cash-on-delivery delivery) and read for downloads; never updated or deleted.
    # The year's counter is taken by one INSERT ... ON CONFLICT DO UPDATE ... RETURNING, which
    # needs SELECT, INSERT and UPDATE; counters are never deleted, so numbers are never reused.
    "invoices": ("SELECT", "INSERT"),
    "invoice_counters": ("SELECT", "INSERT", "UPDATE"),
    # Order notifications (module 17): inserted in the order's transaction (ON CONFLICT DO
    # NOTHING ... RETURNING), then claimed (SELECT ... FOR UPDATE SKIP LOCKED) and updated with
    # each attempt's result by the API and the retry job. Never deleted.
    "notification_logs": ("SELECT", "INSERT", "UPDATE"),
    # Staff stock adjustments create the balance row on first receipt and lock it with
    # FOR UPDATE; dispatch decrements on_hand.
    "inventory_balances": ("SELECT", "INSERT", "UPDATE"),
    # Append-only ledger: adjustment and dispatch rows, and the dispatch idempotency check.
    "stock_movements": ("SELECT", "INSERT"),
    # Checkout creates holds (module 14); availability reads; status changes by the expiry job,
    # cancellation (released), commit and dispatch (fulfilled). Rows are never deleted.
    "stock_reservations": ("SELECT", "INSERT", "UPDATE"),
    # Wishlist (module 21, SC-01 2026-10-27): customers save products (INSERT ... ON CONFLICT
    # DO NOTHING) and remove them (DELETE). The limit check locks the users row (UPDATE).
    "wishlist_items": ("SELECT", "INSERT", "DELETE"),
    # Reviews (module 20, SC-01 2026-10-27): links are issued (INSERT ... ON CONFLICT DO UPDATE)
    # and spent (UPDATE used_at); reviews are sent (INSERT) and moderated (UPDATE). Neither is
    # ever deleted by the application (only the development seed cleanup, as the owner).
    "review_tokens": ("SELECT", "INSERT", "UPDATE"),
    "product_reviews": ("SELECT", "INSERT", "UPDATE"),
    # Policy pages (module 19, 2026-10-29): each language version is written by
    # INSERT ... ON CONFLICT DO UPDATE (content:manage); pages are never deleted by the
    # application (an unpublished page is hidden).
    "pages": ("SELECT", "INSERT", "UPDATE"),
    # Business quote requests (module 19, 2026-10-29): sent from the Contact page (INSERT) and
    # followed up by staff (UPDATE status). Kept as a record; never deleted by the application.
    "quote_requests": ("SELECT", "INSERT", "UPDATE"),
    # Support messages (2026-11-11): conversations are started (INSERT) and change status and
    # last activity (UPDATE); messages are only added and read, never edited. Neither is deleted.
    "support_threads": ("SELECT", "INSERT", "UPDATE"),
    "support_messages": ("SELECT", "INSERT"),
    # Technical services (ADR-013, 2026-11-17): staff create, edit, reorder and delete
    # services and their items; requests are sent by visitors (INSERT) and followed up by
    # staff (UPDATE). Requests are never deleted by the application.
    "service_categories": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "service_items": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "service_requests": ("SELECT", "INSERT", "UPDATE"),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create or update the runtime database role.")
    parser.add_argument("--dotenv", action="store_true", help="also read backend/.env")
    if parser.parse_args(argv).dotenv:
        load_dotenv(BACKEND_ENV, override=False)
    url = os.environ.get("MIGRATION_DATABASE_URL", "").strip()
    runtime_url = os.environ.get("DATABASE_URL", "").strip()
    runtime = make_url(runtime_url) if runtime_url else None
    role = os.environ.get("RUNTIME_DB_ROLE") or (runtime.username if runtime else None)
    password = os.environ.get("RUNTIME_DB_PASSWORD") or (runtime.password if runtime else None)
    if not url or not role or not password:
        print(
            "Set MIGRATION_DATABASE_URL (owner) and DATABASE_URL (runtime account with password) "
            "in the environment, or pass --dotenv to read backend/.env.",
            file=sys.stderr,
        )
        return 2
    if make_url(url).username == role:
        print(
            "DATABASE_URL uses the owner account; point it at the least-privilege runtime "
            "account (see backend/.env.example).",
            file=sys.stderr,
        )
        return 2
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role):
        print("RUNTIME_DB_ROLE must be a simple lower-case identifier.", file=sys.stderr)
        return 2

    url = url.replace("postgresql+psycopg://", "postgresql://", 1)
    ident = sql.Identifier(role)
    with psycopg.connect(url) as conn:  # one transaction: committed on a clean exit only
        dbname = conn.info.dbname
        attributes = conn.execute(
            sql.SQL("SELECT {} FROM pg_roles WHERE rolname = %s").format(
                sql.SQL(", ").join(sql.Identifier(name) for name in ELEVATED_ATTRIBUTES)
            ),
            (role,),
        ).fetchone()
        if attributes is None:
            conn.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION "
                    "NOBYPASSRLS PASSWORD {}"
                ).format(ident, sql.Literal(password))
            )
        elif any(attributes):
            print(f"Refused: role '{role}' has an elevated attribute.", file=sys.stderr)
            return 2
        else:
            conn.execute(
                sql.SQL("ALTER ROLE {} LOGIN PASSWORD {}").format(ident, sql.Literal(password))
            )
        conn.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(dbname), ident)
        )
        conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(ident))
        # Start from nothing on every public table, then grant the allow-list.
        conn.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(ident))
        conn.execute(sql.SQL("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {}").format(ident))
        for table, privileges in TABLE_GRANTS.items():
            conn.execute(
                sql.SQL("GRANT {} ON TABLE {} TO {}").format(
                    sql.SQL(", ").join(sql.SQL(p) for p in privileges),
                    sql.Identifier(table),
                    ident,
                )
            )
    print(f"Runtime role '{role}' provisioned on database '{dbname}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
