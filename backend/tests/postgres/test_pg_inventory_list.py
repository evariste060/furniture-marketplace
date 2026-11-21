"""Module 10 stock list over real HTTP on the least-privilege runtime role.

Proves that GET /inventory works with the runtime role's existing grants (no new grants), and
that both API processes report the same reservation-aware figures as GET /inventory/{sku}.
"""

from datetime import UTC, datetime, timedelta

from app.services import inventory as inv
from tests.postgres.conftest import Stack
from tests.postgres.test_pg_http import HTTP
from tests.postgres.test_pg_inventory import owner_sessions, seed_sku  # noqa: F401
from tests.support.commerce import new_order


def test_the_stock_list_reports_holds_and_low_stock_on_the_runtime_role(
    stack: Stack,
    admin: dict,
    owner_sessions,  # noqa: F811
):
    variant_id, sku, _ = seed_sku(stack, on_hand=6)
    with stack.owner() as conn:
        conn.execute(
            "UPDATE product_variants SET low_stock_threshold = 2 WHERE id = %s", (variant_id,)
        )
    with owner_sessions() as session:
        inv.create_order_with_reservations(
            session, new_order({variant_id: 4}), expires_at=datetime.now(UTC) + timedelta(hours=1)
        )
    for base in stack.servers:
        listing = HTTP.get(f"{base}/inventory", params={"q": sku}, headers=admin)
        assert listing.status_code == 200, listing.text
        (item,) = listing.json()["items"]
        assert (item["on_hand"], item["reserved_quantity"], item["available_quantity"]) == (6, 4, 2)
        assert item["is_low_stock"] is True
        single = HTTP.get(f"{base}/inventory/{sku}", headers=admin).json()
        assert {k: item[k] for k in single} == single
        low = HTTP.get(f"{base}/inventory", params={"low_stock": "true", "q": sku}, headers=admin)
        assert [i["sku"] for i in low.json()["items"]] == [sku]
