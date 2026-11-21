"""The runtime role's table allow-list (scripts/provision_runtime_role.py) stays least-privilege."""

import importlib.util
from pathlib import Path

from app.db.base import Base
from app.models import Order  # noqa: F401  (registers every model on Base.metadata)

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "provision_runtime_role.py"
_spec = importlib.util.spec_from_file_location("provision_runtime_role", SCRIPT)
assert _spec is not None
assert _spec.loader is not None
provision = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(provision)

GRANTS: dict[str, tuple[str, ...]] = provision.TABLE_GRANTS

# What app/services/order_service.py and app/services/inventory.py execute for the order routes.
# inventory_balances INSERT is not used by the order routes: staff stock adjustments
# (app/services/inventory.py adjust_stock) create the balance row on first receipt.
ORDER_TABLES = {
    "orders": ["INSERT", "SELECT", "UPDATE"],  # checkout inserts (module 14)
    "order_items": ["INSERT", "SELECT"],
    "order_status_history": ["INSERT", "SELECT"],
    "payment_attempts": ["INSERT", "SELECT", "UPDATE"],
    "payment_events": ["INSERT", "SELECT", "UPDATE"],  # module 15 webhooks
    "stock_reservations": ["INSERT", "SELECT", "UPDATE"],
    "inventory_balances": ["INSERT", "SELECT", "UPDATE"],
    "stock_movements": ["INSERT", "SELECT"],
}


def test_order_fulfilment_tables_have_exactly_the_privileges_the_service_uses():
    assert {table: sorted(GRANTS.get(table, ())) for table in ORDER_TABLES} == ORDER_TABLES


# DELETE is granted only where a built feature physically removes rows: saved addresses, unused
# categories and brands (module 5; the service refuses rows still referenced), and product images
# (module 7; nothing references an image row), cart lines (module 11) and promotion targets
# (module 13; replaced as a set), and media registry rows (ADR-009, 2026-10-26: a failed
# upload's rows, and retired rows once the cleanup worker has deleted their files), and
# homepage banners (2026-10-26; staff delete them, their images are retired), and wishlist rows
# (module 21, 2026-10-27: a customer removes a saved product).
DELETABLE_TABLES = {
    "addresses",
    "categories",
    "brands",
    "product_images",
    "cart_items",
    "discount_targets",
    "media_objects",
    "banners",
    "wishlist_items",
    # Continue with Google: expired sign-in flows are deleted (they hold no lasting record).
    "oauth_login_flows",
    # ADR-012 decisions 8 and 9 (2026-11-16/17): a category's store menu brands and a brand's
    # categories are presentation links, replaced as a set.
    "category_menu_brands",
    "brand_categories",
    # ADR-013 (2026-11-17): staff delete a service without requests, and a service's items.
    # Service requests are never deleted.
    "service_categories",
    "service_items",
}


def test_only_approved_tables_may_be_deleted_and_no_broad_privileges_are_granted():
    allowed = {"SELECT", "INSERT", "UPDATE", "DELETE"}
    for table, privileges in GRANTS.items():
        assert set(privileges) <= allowed, table
        assert len(set(privileges)) == len(privileges), table
        if table not in DELETABLE_TABLES:
            assert "DELETE" not in privileges, table


def test_catalogue_tables_have_exactly_the_privileges_modules_5_to_8_use():
    catalogue = {
        "categories": ["DELETE", "INSERT", "SELECT", "UPDATE"],
        "brands": ["DELETE", "INSERT", "SELECT", "UPDATE"],
        # Module 6: products and variants are created and edited, never deleted.
        "products": ["INSERT", "SELECT", "UPDATE"],
        "product_variants": ["INSERT", "SELECT", "UPDATE"],
        # Module 7: images are uploaded, reordered and deleted.
        "product_images": ["DELETE", "INSERT", "SELECT", "UPDATE"],
        # Module 8: import jobs are created, then finished in place; they are never deleted.
        "import_jobs": ["INSERT", "SELECT", "UPDATE"],
        # ADR-009 media registry: registered, activated, retired, then deleted by the worker.
        "media_objects": ["DELETE", "INSERT", "SELECT", "UPDATE"],
        # Job queue (2026-10-26): jobs and items are created, claimed and finished; kept.
        "jobs": ["INSERT", "SELECT", "UPDATE"],
        "job_items": ["INSERT", "SELECT", "UPDATE"],
    }
    assert {table: sorted(GRANTS.get(table, ())) for table in catalogue} == catalogue


def test_append_only_tables_cannot_be_updated():
    for table in ("audit_records", "order_status_history", "stock_movements", "invoices"):
        assert "UPDATE" not in GRANTS[table], table


def test_every_granted_table_exists_in_the_schema():
    assert set(GRANTS) - {"alembic_version"} <= set(Base.metadata.tables)


def test_password_reset_codes_are_issued_and_updated_but_never_deleted():
    assert sorted(GRANTS["password_reset_codes"]) == ["INSERT", "SELECT", "UPDATE"]


def test_cart_tables_have_exactly_the_privileges_module_11_uses():
    # Carts are created and updated (expiry, merged -> converted, expired -> abandoned), never
    # deleted; their lines are added, changed and removed.
    assert sorted(GRANTS["carts"]) == ["INSERT", "SELECT", "UPDATE"]
    assert sorted(GRANTS["cart_items"]) == ["DELETE", "INSERT", "SELECT", "UPDATE"]


def test_delivery_and_settings_tables_have_exactly_the_privileges_module_12_uses():
    # Zones are created and edited; fee rules are closed in place and replaced, never deleted
    # (fee history); settings are upserted. No DELETE anywhere.
    delivery = {
        "delivery_zones": ["INSERT", "SELECT", "UPDATE"],
        "delivery_fee_rules": ["INSERT", "SELECT", "UPDATE"],
        "settings": ["INSERT", "SELECT", "UPDATE"],
    }
    assert {table: sorted(GRANTS.get(table, ())) for table in delivery} == delivery


def test_promotion_tables_have_exactly_the_privileges_module_13_uses():
    # Codes are created and edited (and row-locked at checkout), never deleted; targets are
    # replaced as a set; redemptions are inserted and released in place, never deleted.
    promotions = {
        "discounts": ["INSERT", "SELECT", "UPDATE"],
        "discount_targets": ["DELETE", "INSERT", "SELECT"],
        "discount_redemptions": ["INSERT", "SELECT", "UPDATE"],
    }
    assert {table: sorted(GRANTS.get(table, ())) for table in promotions} == promotions


def test_invoice_tables_have_exactly_the_privileges_module_16_uses():
    # Invoices are inserted once and read, never updated or deleted; the year's counter is
    # taken by INSERT ... ON CONFLICT DO UPDATE ... RETURNING and never deleted, so a committed
    # number cannot be reused.
    invoices = {
        "invoices": ["INSERT", "SELECT"],
        "invoice_counters": ["INSERT", "SELECT", "UPDATE"],
    }
    assert {table: sorted(GRANTS.get(table, ())) for table in invoices} == invoices


def test_review_tables_have_exactly_the_privileges_module_20_uses():
    assert sorted(GRANTS["review_tokens"]) == ["INSERT", "SELECT", "UPDATE"]
    assert sorted(GRANTS["product_reviews"]) == ["INSERT", "SELECT", "UPDATE"]


def test_wishlist_table_has_exactly_the_privileges_module_21_uses():
    # Save (INSERT ... ON CONFLICT DO NOTHING), list and count (SELECT), remove (DELETE).
    assert sorted(GRANTS["wishlist_items"]) == ["DELETE", "INSERT", "SELECT"]
    assert "UPDATE" in GRANTS["users"]  # the limit check locks the customer's users row


def test_notification_logs_have_exactly_the_privileges_module_17_uses():
    # Inserted with the order change, then claimed and updated per attempt; never deleted, so the
    # log of what was sent stays complete.
    assert sorted(GRANTS["notification_logs"]) == ["INSERT", "SELECT", "UPDATE"]


def test_content_tables_have_exactly_the_privileges_module_19_uses():
    # Pages are written in place (one row per slug and language) and read; quote requests are
    # sent and their status changed. No route deletes either, so the runtime role has no DELETE.
    assert sorted(GRANTS["pages"]) == ["INSERT", "SELECT", "UPDATE"]
    assert sorted(GRANTS["quote_requests"]) == ["INSERT", "SELECT", "UPDATE"]


def test_support_tables_have_exactly_the_privileges_support_uses():
    # Threads change status; messages are only ever added. Nothing is deleted or edited.
    assert sorted(GRANTS["support_threads"]) == ["INSERT", "SELECT", "UPDATE"]
    assert sorted(GRANTS["support_messages"]) == ["INSERT", "SELECT"]


def test_google_sign_in_tables_have_exactly_the_privileges_the_service_uses():
    # Identities are linked and used, never deleted; flows are created, consumed and purged.
    assert sorted(GRANTS["oauth_identities"]) == ["INSERT", "SELECT", "UPDATE"]
    assert sorted(GRANTS["oauth_login_flows"]) == ["DELETE", "INSERT", "SELECT", "UPDATE"]


def test_email_verification_tokens_are_issued_and_updated_but_never_deleted():
    # Issued at registration and resend; consumed or revoked in place.
    assert sorted(GRANTS["email_verification_tokens"]) == ["INSERT", "SELECT", "UPDATE"]


def test_stores_are_never_deleted_and_their_history_is_append_only():
    # ADR-014 phase 1: applicants insert and edit their store, administrators decide on it.
    assert sorted(GRANTS["stores"]) == ["INSERT", "SELECT", "UPDATE"]
    assert sorted(GRANTS["store_status_history"]) == ["INSERT", "SELECT"]
