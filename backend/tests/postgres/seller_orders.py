"""Move orders through their stores' seller orders over real HTTP (ADR-014 phase 3).

Staff no longer confirm, process, dispatch or deliver an order; each store moves its own seller
order and the order follows. A store seeded by SQL (test_pg_inventory.seed_store) has an owner
without a password, so a bearer session is inserted for it with the owner connection, as the
application would store one (only the token's hash).
"""

import uuid
from datetime import UTC, datetime, timedelta

from app.core.security import generate_session_token, hash_session_token
from tests.postgres.conftest import Stack
from tests.postgres.test_pg_http import HTTP

STEPS = ("confirmed", "processing", "dispatched", "delivered")


def owner_headers(stack: Stack, store_id: str) -> dict:
    raw = generate_session_token()
    now = datetime.now(UTC)
    with stack.owner() as conn:
        conn.execute(
            "INSERT INTO user_sessions (id, user_id, token_hash, last_active_at, expires_at) "
            "SELECT %s, owner_user_id, %s, %s, %s FROM stores WHERE id = %s",
            (uuid.uuid4(), hash_session_token(raw), now, now + timedelta(days=1), store_id),
        )
    return {"Authorization": f"Bearer {raw}"}


def advance(stack: Stack, order_id: str, target: str) -> None:
    """Every seller order of the order, step by step to `target`, on alternating processes."""
    with stack.owner() as conn:
        rows = conn.execute(
            "SELECT id, store_id FROM seller_orders WHERE order_id = %s ORDER BY id", (order_id,)
        ).fetchall()
    assert rows, "the order has no seller orders"
    headers = {store: owner_headers(stack, store) for _, store in rows}
    for i, status in enumerate(STEPS[: STEPS.index(target) + 1]):
        for seller_order_id, store in rows:
            res = HTTP.patch(
                f"{stack.servers[i % 2]}/seller/orders/{seller_order_id}/status",
                json={"status": status},
                headers=headers[store],
            )
            assert res.status_code == 200, (status, res.text)
