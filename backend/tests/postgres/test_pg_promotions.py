"""Module 13 promotions over real HTTP and on the least-privilege runtime role.

Proves the grants (discounts: SELECT, INSERT, UPDATE; discount_targets: SELECT, INSERT, DELETE;
discount_redemptions: SELECT, INSERT, UPDATE), that management can view but not change
promotions, that customers apply and remove codes through the API on two processes, that
concurrent redemptions on the runtime role take a limited code's uses exactly once, and that the
expiry job, running as the runtime role, releases an expired order's redemption.
"""

import os
import secrets
import subprocess
import sys
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services import inventory as inv
from app.services.promotion_service import PromotionNotApplicable, redeem
from tests.postgres.conftest import BACKEND, HMAC_KEY, REPO, Stack
from tests.postgres.test_pg_http import HTTP, one, register
from tests.postgres.test_pg_inventory import seed_sku
from tests.postgres.test_pg_staff import STAFF_PASSWORD, create_staff
from tests.support.commerce import new_order

PROMOTIONS = "/staff/promotions"


def create_promotion(stack: Stack, admin: dict, **fields) -> dict:
    body = {
        "code": f"PG{secrets.token_hex(4).upper()}",
        "name": "PG promotion",
        "kind": "percent",
        "percent_off": 10,
        "status": "active",
        **fields,
    }
    res = HTTP.post(f"{stack.servers[0]}{PROMOTIONS}", json=body, headers=admin)
    assert res.status_code == 201, res.text
    return res.json()


@pytest.fixture(scope="module")
def owner_sessions(stack: Stack):
    engine = create_engine(stack.owner_url, pool_size=5, max_overflow=5)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture(scope="module")
def runtime_sessions(stack: Stack):
    engine = create_engine(stack.runtime_url, pool_size=10, max_overflow=5)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


def test_customers_apply_and_remove_codes_over_http(stack: Stack, admin: dict, unique: str):
    promo = create_promotion(stack, admin, percent_off=20)
    customer = register(stack, stack.servers[0], f"promo.{unique}@pg.test")
    variant_id, _, _ = seed_sku(stack, on_hand=5)
    added = HTTP.post(
        f"{stack.servers[0]}/cart/items",
        json={"variant_id": str(variant_id), "quantity": 1},
        headers=customer["headers"],
    )
    assert added.status_code == 200, added.text
    applied = HTTP.post(
        f"{stack.servers[1]}/cart/apply-code",
        json={"code": promo["code"].lower()},
        headers=customer["headers"],
    )
    assert applied.status_code == 200, applied.text
    assert (applied.json()["discount_total"], applied.json()["subtotal_after_discount"]) == (
        200,
        800,
    )
    removed = HTTP.delete(f"{stack.servers[0]}/cart/code", headers=customer["headers"])
    assert removed.status_code == 200 and removed.json()["discount"] is None
    with stack.owner() as conn:
        assert one(
            conn, "SELECT count(*) FROM discount_redemptions WHERE discount_id = %s", promo["id"]
        ) == (0,)


def test_management_can_view_but_not_change_promotions(stack: Stack, admin: dict, unique: str):
    promo = create_promotion(stack, admin)
    staff = create_staff(stack, admin, unique, "management", "mgmt-promo")
    res = HTTP.post(
        f"{stack.servers[0]}/auth/login",
        json={"identifier": staff["email"], "password": STAFF_PASSWORD},
    )
    h = {"Authorization": f"Bearer {res.json()['session_token']}"}
    base = stack.servers[1]
    assert HTTP.get(f"{base}{PROMOTIONS}", headers=h).status_code == 200
    assert HTTP.get(f"{base}{PROMOTIONS}/{promo['id']}", headers=h).status_code == 200
    body = {"code": "NOPE", "name": "x", "kind": "percent", "percent_off": 5}
    assert HTTP.post(f"{base}{PROMOTIONS}", json=body, headers=h).status_code == 403
    assert (
        HTTP.patch(f"{base}{PROMOTIONS}/{promo['id']}", json={"name": "y"}, headers=h).status_code
        == 403
    )


def test_concurrent_redemptions_on_the_runtime_role_take_each_use_once(
    stack: Stack,
    admin: dict,
    owner_sessions,
    runtime_sessions,
):
    promo = create_promotion(stack, admin, usage_limit_total=1)
    variant_id, _, _ = seed_sku(stack, on_hand=10)
    orders = []
    for _ in range(6):
        with owner_sessions() as s:
            result = inv.create_order_with_reservations(
                s, new_order({variant_id: 1}), expires_at=datetime.now(UTC) + timedelta(hours=1)
            )
            orders.append(result.order.id)
    barrier = threading.Barrier(6)
    results: list[str] = []
    lock = threading.Lock()

    def checkout(i: int):
        with runtime_sessions() as session:
            barrier.wait(timeout=30)
            try:
                redeem(
                    session,
                    discount_id=uuid.UUID(promo["id"]),
                    order_id=orders[i],
                    user_id=None,
                    customer_phone=f"07884000{i:02d}",
                    amount=100,
                )
                session.commit()
                outcome = "redeemed"
            except PromotionNotApplicable as exc:
                session.rollback()
                outcome = exc.reason
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=checkout, args=(i,)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert sorted(results) == ["redeemed"] + ["usage_limit_reached"] * 5
    with stack.owner() as conn:
        assert one(
            conn,
            "SELECT count(*) FROM discount_redemptions WHERE discount_id = %s AND "
            "status = 'active'",
            promo["id"],
        ) == (1,)


def test_the_expiry_job_releases_redemptions_as_the_runtime_role(
    stack: Stack,
    admin: dict,
    owner_sessions,
    runtime_sessions,
):
    promo = create_promotion(stack, admin)
    variant_id, _, _ = seed_sku(stack, on_hand=2)
    with owner_sessions() as s:
        order_id = inv.create_order_with_reservations(
            s, new_order({variant_id: 1}), expires_at=datetime.now(UTC) + timedelta(seconds=1)
        ).order.id
    with runtime_sessions() as session:
        redeem(
            session,
            discount_id=uuid.UUID(promo["id"]),
            order_id=order_id,
            user_id=None,
            customer_phone="0788499999",
            amount=50,
        )
        session.commit()
    time.sleep(1.5)
    env = {
        **os.environ,
        "DATABASE_URL": stack.runtime_url,
        "MIGRATION_DATABASE_URL": "",
        "AUDIT_HMAC_KEY": HMAC_KEY,
        "REDIS_URL": stack.redis_url,
    }
    cmd = [sys.executable, str(REPO / "scripts" / "expire_reservations.py")]
    result = subprocess.run(cmd, cwd=BACKEND, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    with stack.owner() as conn:
        assert one(
            conn,
            "SELECT status, release_reason FROM discount_redemptions WHERE order_id = %s",
            order_id,
        ) == ("released", "expired")


def test_runtime_role_privileges_on_promotion_tables(stack: Stack):
    with stack.runtime() as conn:
        conn.execute("DELETE FROM discount_targets WHERE false")  # granted: targets are replaced
        for table in ("discounts", "discount_redemptions"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(f"DELETE FROM {table} WHERE false")
