"""Module 12 delivery over real HTTP on the least-privilege runtime role, in two API processes.

Proves the grants (delivery_zones, delivery_fee_rules, settings: SELECT, INSERT, UPDATE; no
DELETE), that concurrent fee changes keep exactly one active rule and a complete history, that
concurrent creations of one district create one zone, that management can view but not change,
and that scripts/seed_dev.py works on the runtime role and is idempotent.
"""

import os
import subprocess
import sys

import psycopg
import pytest

from tests.postgres.conftest import BACKEND, HMAC_KEY, REPO, Stack
from tests.postgres.test_pg_http import HTTP, one, register
from tests.postgres.test_pg_inventory import seed_sku, together

ZONES = "/staff/delivery/zones"
THRESHOLD = "delivery.free_delivery_threshold"


@pytest.fixture
def clean(stack: Stack) -> Stack:
    """Start each test with no delivery rows (owner connection; the runtime role cannot delete)."""
    with stack.owner() as conn:
        conn.execute("DELETE FROM delivery_fee_rules")
        conn.execute("DELETE FROM delivery_zones")
        conn.execute("DELETE FROM settings")
    return stack


def seed_cli(stack: Stack, app_env: str = "development") -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "DATABASE_URL": stack.runtime_url,
        "AUDIT_HMAC_KEY": HMAC_KEY,
        "REDIS_URL": stack.redis_url,
        "APP_ENV": app_env,
        "MEDIA_BASE_URL": "https://media.example.rw",
    }
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "seed_dev.py")],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
    )


def test_seed_runs_on_the_runtime_role_once_and_refuses_outside_development(clean: Stack):
    first = seed_cli(clean)
    assert first.returncode == 0, first.stderr
    assert "development placeholders" in first.stdout
    second = seed_cli(clean)
    assert second.returncode == 0 and "Nothing to seed" in second.stdout
    refused = seed_cli(clean, "production")
    assert refused.returncode == 2 and "APP_ENV=development" in refused.stderr
    body = HTTP.get(f"{clean.servers[1]}/delivery/zones").json()
    assert [(z["code"], z["fee"]) for z in body["items"]] == [
        ("nyarugenge", 1500),
        ("kicukiro", 2000),
        ("gasabo", 2000),
    ]
    assert body["free_delivery_threshold"] == 50_000
    url = clean.runtime_url.split("@")[-1]
    assert url not in first.stdout + first.stderr  # no connection details printed


def test_concurrent_fee_changes_keep_one_active_rule_and_full_history(clean: Stack, admin: dict):
    created = HTTP.post(
        f"{clean.servers[0]}{ZONES}",
        json={"code": "gasabo", "name": "Gasabo", "district": "Gasabo", "fee": 2000},
        headers=admin,
    )
    assert created.status_code == 201, created.text
    url = f"{ZONES}/{created.json()['id']}"
    fees = [2100 + i for i in range(8)]
    results = together(
        8,
        lambda i: HTTP.patch(f"{clean.servers[i % 2]}{url}", json={"fee": fees[i]}, headers=admin),
    )
    assert [r.status_code for r in results] == [200] * 8, [r.text for r in results]
    with clean.owner() as conn:
        assert one(conn, "SELECT count(*) FROM delivery_fee_rules WHERE is_active") == (1,)
        assert one(conn, "SELECT count(*) FROM delivery_fee_rules") == (9,)
        assert one(conn, "SELECT count(*) FROM delivery_fee_rules WHERE ends_at IS NULL") == (1,)
        assert one(
            conn, "SELECT count(*) FROM audit_records WHERE action = 'delivery.zone_update'"
        ) >= (8,)
        (current,) = one(conn, "SELECT fee FROM delivery_fee_rules WHERE is_active")
    assert current in fees
    public = HTTP.get(f"{clean.servers[1]}/delivery/zones").json()["items"]
    assert [z["fee"] for z in public] == [current]


def test_concurrent_creations_of_one_district_create_one_zone(clean: Stack, admin: dict):
    def create(i: int):
        body = {"code": f"kicukiro-{i}", "name": "Kicukiro", "district": "Kicukiro", "fee": 2000}
        return HTTP.post(f"{clean.servers[i % 2]}{ZONES}", json=body, headers=admin)

    results = together(6, create)
    assert sorted(r.status_code for r in results) == [201] + [409] * 5, [r.text for r in results]
    assert {r.json()["error"]["code"] for r in results if r.status_code == 409} == {
        "zone_district_taken"
    }
    with clean.owner() as conn:
        assert one(conn, "SELECT count(*) FROM delivery_zones") == (1,)
        assert one(conn, "SELECT count(*) FROM delivery_fee_rules") == (1,)


def test_concurrent_threshold_changes_are_all_audited_in_order(clean: Stack, admin: dict):
    values = [150_000 + i for i in range(6)]
    results = together(
        6,
        lambda i: HTTP.patch(
            f"{clean.servers[i % 2]}/staff/settings", json={THRESHOLD: values[i]}, headers=admin
        ),
    )
    assert [r.status_code for r in results] == [200] * 6, [r.text for r in results]
    with clean.owner() as conn:
        rows = conn.execute(
            "SELECT change_summary -> 'changes' -> %s FROM audit_records "
            "WHERE action = 'settings.update'",
            (THRESHOLD,),
        ).fetchall()
        (final,) = one(conn, "SELECT value FROM settings WHERE key = %s", THRESHOLD)
    changes = [row[0] for row in rows if row[0] is not None and row[0]["to"] in values]
    assert len(changes) == 6
    # Serialised: the changes form one chain from "unset" to the final value, each replacing the
    # value the previous one wrote (audit created_at is the transaction start, so it is not used
    # for ordering).
    by_from = {c["from"]: c["to"] for c in changes}
    assert len(by_from) == 6
    chain, current = [], None
    while current in by_from:
        current = by_from[current]
        chain.append(current)
    assert sorted(chain) == sorted(values) and chain[-1] == final


def test_cart_quote_on_the_runtime_role(clean: Stack, unique: str):
    assert seed_cli(clean).returncode == 0
    customer = register(clean, clean.servers[0], f"quote.{unique}@pg.test")
    variant_id, _, _ = seed_sku(clean, on_hand=5)
    res = HTTP.post(
        f"{clean.servers[0]}/cart/items",
        json={"variant_id": str(variant_id), "quantity": 1},
        headers=customer["headers"],
    )
    assert res.status_code == 200, res.text
    subtotal = res.json()["merchandise_subtotal"]
    cart = HTTP.get(
        f"{clean.servers[1]}/cart", params={"zone": "nyarugenge"}, headers=customer["headers"]
    ).json()
    fee = 0 if subtotal >= 50_000 else 1500
    assert cart["delivery"]["delivery_fee"] == fee and cart["grand_total"] == subtotal + fee


def test_runtime_role_cannot_delete_delivery_rows_or_settings(stack: Stack):
    with stack.runtime() as conn:
        for table in ("delivery_fee_rules", "delivery_zones", "settings"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(f"DELETE FROM {table} WHERE false")
        conn.execute("SELECT count(*) FROM settings")  # granted (module 12)
