"""Inventory over real HTTP and real processes (PR-09, TC-13, TC-14; ADR-002 2026-10-22).

The API runs as two uvicorn processes on the least-privilege runtime role; reservations are made
through the service on separate owner connections (checkout has no HTTP endpoint yet); expiry runs
as parallel operator CLI processes. Assertions read PostgreSQL directly as the owner role.
"""

import os
import re
import secrets
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import psycopg
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services import inventory as inv
from tests.postgres.conftest import BACKEND, HMAC_KEY, REPO, Stack
from tests.postgres.test_pg_http import HTTP, one
from tests.support.commerce import new_order


@pytest.fixture(scope="module")
def owner_sessions(stack: Stack):
    engine = create_engine(stack.owner_url, pool_size=20, max_overflow=10)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


def seed_store(conn, tag: str) -> uuid.UUID:
    """A disposable approved store with its owner (ADR-014 phase 2: every product has one)."""
    owner, store = uuid.uuid4(), uuid.uuid4()
    conn.execute(
        "INSERT INTO users (id, email, full_name) VALUES (%s, %s, 'PG store owner')",
        (owner, f"pg.store.{tag}@pg.test"),
    )
    conn.execute(
        "INSERT INTO stores (id, owner_user_id, name, slug, contact_email, contact_phone, "
        "district, status, submitted_at, reviewed_at, approved_at) VALUES (%s, %s, %s, %s, "
        "'shop@pg.test', '+250788000001', 'Gasabo', 'approved', now(), now(), now())",
        (store, owner, f"PG store {tag}", f"pg-store-{tag}"),
    )
    return store


def seed_sku(stack: Stack, on_hand: int) -> tuple[uuid.UUID, str, str]:
    """A sellable disposable SKU; returns (variant_id, sku, product_slug)."""
    tag = secrets.token_hex(5)
    ids = [uuid.uuid4() for _ in range(4)]
    with stack.owner() as conn:
        store = seed_store(conn, tag)
        conn.execute(
            "INSERT INTO categories (id, name, slug) VALUES (%s, %s, %s)",
            (ids[0], f"PG category {tag}", f"pg-cat-{tag}"),
        )
        conn.execute(
            "INSERT INTO products (id, name, slug, category_id, status, specifications, store_id) "
            "VALUES (%s, %s, %s, %s, 'active', '{}', %s)",
            (ids[1], f"PG product {tag}", f"pg-product-{tag}", ids[0], store),
        )
        conn.execute(
            "INSERT INTO product_variants (id, product_id, sku, name, price) "
            "VALUES (%s, %s, %s, 'PG variant', 1000)",
            (ids[2], ids[1], f"PG-{tag}"),
        )
        conn.execute(
            "INSERT INTO inventory_balances (id, variant_id, on_hand) VALUES (%s, %s, %s)",
            (ids[3], ids[2], on_hand),
        )
    return ids[2], f"PG-{tag}", f"pg-product-{tag}"


def stock(stack: Stack, variant_id: uuid.UUID) -> tuple[int, int, int]:
    """(on_hand, allocated, movements) read directly from PostgreSQL."""
    with stack.owner() as conn:
        on_hand = one(
            conn, "SELECT on_hand FROM inventory_balances WHERE variant_id=%s", variant_id
        )
        allocated = one(
            conn,
            "SELECT coalesce(sum(quantity), 0) FROM stock_reservations "
            "WHERE variant_id=%s AND status IN ('active', 'committed')",
            variant_id,
        )
        moves = one(conn, "SELECT count(*) FROM stock_movements WHERE variant_id=%s", variant_id)
    return on_hand[0], int(allocated[0]), moves[0]


def adjust(stack: Stack, i: int, admin: dict, sku: str, delta: int, key: str, reason="adjustment"):
    return HTTP.post(
        f"{stack.servers[i % 2]}/inventory/{sku}/adjustments",
        json={"reason": reason, "quantity_delta": delta},
        headers={**admin, "Idempotency-Key": key},
    )


def together(n: int, fn) -> list:
    barrier = Barrier(n)

    def run(i):
        barrier.wait(timeout=30)
        return fn(i)

    with ThreadPoolExecutor(n) as pool:
        return list(pool.map(run, range(n)))


def _expired_count(stdout: bytes) -> int:
    """Orders expired by one expire_reservations.py run, from its summary line."""
    match = re.search(rb"Expired (\d+) order", stdout)
    assert match is not None, stdout.decode(errors="replace")
    return int(match.group(1))


def test_public_catalogue_and_inventory_reads_work_on_the_runtime_role(stack: Stack, admin: dict):
    variant_id, sku, slug = seed_sku(stack, on_hand=4)
    for base in stack.servers:
        listing = HTTP.get(f"{base}/catalog/products", params={"q": slug})
        assert listing.status_code == 200, listing.text
        detail = HTTP.get(f"{base}/catalog/products/{slug}")
        assert detail.status_code == 200, detail.text
        figures = HTTP.get(f"{base}/inventory/{sku}", headers=admin)
        assert figures.status_code == 200, figures.text
        assert figures.json()["available_quantity"] == 4


def test_concurrent_http_removals_never_touch_reserved_stock(
    stack: Stack, admin: dict, owner_sessions
):
    variant_id, sku, _ = seed_sku(stack, on_hand=5)
    with owner_sessions() as s:
        inv.create_order_with_reservations(
            s, new_order({variant_id: 3}), expires_at=datetime.now(UTC) + timedelta(hours=1)
        )
    tag = secrets.token_hex(4)
    codes = sorted(
        r.status_code
        for r in together(10, lambda i: adjust(stack, i, admin, sku, -1, f"rm-{tag}-{i:02d}"))
    )
    assert codes == [201, 201] + [409] * 8
    assert stock(stack, variant_id) == (3, 3, 2)
    with stack.owner() as conn:
        audits = one(
            conn,
            "SELECT count(*) FROM audit_records WHERE action='inventory.adjust' AND entity_id=%s",
            str(variant_id),
        )
    assert audits == (2,)


def test_concurrent_retries_with_one_idempotency_key_apply_once(stack: Stack, admin: dict):
    variant_id, sku, _ = seed_sku(stack, on_hand=0)
    key = f"receipt-{secrets.token_hex(6)}"
    results = together(8, lambda i: adjust(stack, i, admin, sku, 7, key, reason="receipt"))
    assert sorted(r.status_code for r in results) == [200] * 7 + [201]
    assert len({r.json()["movement"]["id"] for r in results}) == 1
    assert stock(stack, variant_id) == (7, 0, 1)


def test_reservations_racing_http_removals_never_oversell(
    stack: Stack, admin: dict, owner_sessions
):
    variant_id, sku, _ = seed_sku(stack, on_hand=10)
    tag = secrets.token_hex(4)

    def act(i):
        if i % 2:
            return adjust(stack, i, admin, sku, -1, f"race-{tag}-{i:02d}").status_code == 201
        try:
            with owner_sessions() as s:
                inv.create_order_with_reservations(
                    s,
                    new_order({variant_id: 1}),
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            return True
        except inv.InsufficientStock:
            return False

    successes = sum(together(24, act))
    on_hand, allocated, removals = stock(stack, variant_id)
    assert successes == 10  # every unit went to exactly one reservation or removal
    assert on_hand == 10 - removals and allocated == on_hand


def test_parallel_expiry_processes_release_each_hold_once(stack: Stack, owner_sessions):
    variant_id, _, _ = seed_sku(stack, on_hand=12)
    orders = []
    for _ in range(12):
        with owner_sessions() as s:
            result = inv.create_order_with_reservations(
                s, new_order({variant_id: 1}), expires_at=datetime.now(UTC) + timedelta(seconds=1)
            )
            orders.append(result.order.id)
    time.sleep(1.5)
    env = {
        **os.environ,
        "DATABASE_URL": stack.runtime_url,  # the job runs on the least-privilege role
        "MIGRATION_DATABASE_URL": "",
        "AUDIT_HMAC_KEY": HMAC_KEY,
        "REDIS_URL": stack.redis_url,
    }
    cmd = [sys.executable, str(REPO / "scripts" / "expire_reservations.py"), "--batch-size", "2"]
    procs = [
        subprocess.Popen(cmd, cwd=BACKEND, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for _ in range(3)
    ]
    outputs = [p.communicate(timeout=120) for p in procs]
    assert all(p.returncode == 0 for p in procs), [o[1].decode() for o in outputs]
    expired = sum(_expired_count(out) for out, _ in outputs)
    assert expired == 12
    with stack.owner() as conn:
        assert one(
            conn,
            "SELECT count(*) FROM stock_reservations WHERE order_id = ANY(%s) AND status='expired'",
            orders,
        ) == (12,)
        assert one(
            conn,
            "SELECT count(*) FROM audit_records WHERE action='inventory.reservation_expire' "
            "AND entity_id = ANY(%s)",
            [str(o) for o in orders],
        ) == (12,)
    assert stock(stack, variant_id)[1] == 0
    again = subprocess.run(cmd, cwd=BACKEND, env=env, capture_output=True, text=True)
    assert again.returncode == 0 and "Expired 0 order(s)" in again.stdout


def test_runtime_role_cannot_delete_or_rewrite_reservations(stack: Stack, owner_sessions):
    """Since module 14 the runtime role inserts orders and holds (checkout); it still cannot
    delete them, rewrite a committed hold or touch the ledger."""
    variant_id, _, _ = seed_sku(stack, on_hand=2)
    with owner_sessions() as s:
        order_id = inv.create_order_with_reservations(
            s, new_order({variant_id: 1}), expires_at=datetime.now(UTC) + timedelta(hours=1)
        ).order.id
    with owner_sessions() as s:
        inv.commit_order_reservations(s, order_id)
    with stack.runtime() as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM stock_reservations WHERE order_id=%s", (order_id,))
        # The development cleanup setting (migration b4e7d1a9c3f2) gives it nothing: the
        # runtime role has no DELETE privilege and does not own the table.
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("SET LOCAL app.dev_seed_cleanup = 'on'")
            conn.execute("DELETE FROM stock_reservations WHERE order_id=%s", (order_id,))
        owner = conn.execute(
            "SELECT pg_has_role(current_user, relowner, 'MEMBER') FROM pg_class "
            "WHERE oid = 'stock_reservations'::regclass"
        ).fetchone()
        assert owner == (False,)
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "UPDATE stock_reservations SET status='released', released_at=now() "
                "WHERE order_id=%s",
                (order_id,),
            )
        # Checkout (module 14) inserts orders; deleting them stays denied.
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM orders WHERE id=%s", (order_id,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM stock_movements")
    assert stock(stack, variant_id)[1] == 1


def test_runtime_role_moves_an_active_hold_only_within_24_hours(stack: Stack, owner_sessions):
    """Migration a8d2f6c1e3b7 (frontend phase 4, 2026-10-27): a payment-method switch moves an
    active hold's expiry, never beyond 24 hours after the hold was created; nothing else."""
    variant_id, _, _ = seed_sku(stack, on_hand=2)
    with owner_sessions() as s:
        order_id = inv.create_order_with_reservations(
            s, new_order({variant_id: 1}), expires_at=datetime.now(UTC) + timedelta(minutes=15)
        ).order.id
    with stack.runtime() as conn:
        conn.execute(
            "UPDATE stock_reservations SET expires_at = created_at + interval '24 hours' "
            "WHERE order_id=%s",
            (order_id,),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "UPDATE stock_reservations SET expires_at = created_at + interval '25 hours' "
                "WHERE order_id=%s",
                (order_id,),
            )
        with pytest.raises(psycopg.errors.CheckViolation):  # the other columns stay fixed
            conn.execute(
                "UPDATE stock_reservations SET quantity = 2 WHERE order_id=%s", (order_id,)
            )
    with owner_sessions() as s:
        inv.commit_order_reservations(s, order_id)
    with stack.runtime() as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(  # a committed hold's expiry is fixed
            "UPDATE stock_reservations SET expires_at = created_at + interval '1 hour' "
            "WHERE order_id=%s",
            (order_id,),
        )
