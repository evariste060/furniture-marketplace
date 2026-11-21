"""Staff provisioning and administration over real HTTP (two API processes, runtime DB role).

TC-16 / PR-15 evidence for the approved staff scope (ADR-006, 2026-10-22). Every account is
disposable. Assertions read PostgreSQL directly as the owner role.
"""

import hashlib
from urllib.parse import urlsplit

import httpx
import psycopg
import pytest

from tests.postgres.conftest import (
    Stack,
    bootstrap_cli,
    login,
)
from tests.postgres.test_pg_http import HTTP, one, parallel, register
from tests.support.credentials import random_password

STAFF_PASSWORD = random_password()


def create_staff(stack: Stack, admin: dict, unique: str, role: str, tag: str) -> dict:
    email = f"{tag}.{unique}@pg.test"
    res = HTTP.post(
        f"{stack.servers[0]}/staff",
        json={"email": email, "full_name": f"PG {tag}", "password": STAFF_PASSWORD, "role": role},
        headers=admin,
    )
    assert res.status_code == 201, res.text
    return {"id": res.json()["id"], "email": email}


# ---- bootstrap -------------------------------------------------------------------------------
def test_bootstrap_cli_created_admin_with_audit_and_refuses_a_second(stack: Stack, admin: dict):
    me = HTTP.get(f"{stack.servers[1]}/staff/me", headers=admin).json()
    assert me["role"] == "administrator" and "staff:manage" in me["permissions"]
    with stack.owner() as conn:
        assert one(
            conn,
            "SELECT count(*) FROM audit_records WHERE action='staff.bootstrap_administrator' "
            "AND entity_id=%s AND actor_user_id IS NULL",
            me["id"],
        ) == (1,)
        summary = one(
            conn,
            "SELECT change_summary FROM audit_records "
            "WHERE action='staff.bootstrap_administrator' AND entity_id=%s",
            me["id"],
        )[0]
    owner_role = urlsplit(stack.owner_url).username
    assert summary["mode"] == "first" and summary["db_role"] == owner_role
    second_password = random_password()
    again = bootstrap_cli(stack, second_password, "--email", "x2@pg.test", "--full-name", "Xy")
    assert again.returncode == 1 and "active administrator already exists" in again.stderr
    assert second_password not in again.stdout + again.stderr


@pytest.mark.parametrize(
    "owner_override", ["", "runtime"], ids=["owner-url-unset", "owner-url-is-app-account"]
)
def test_bootstrap_cli_requires_the_schema_owner_account(stack: Stack, owner_override: str):
    password = random_password()
    owner = stack.runtime_url if owner_override == "runtime" else ""
    result = bootstrap_cli(
        stack, password, "--email", "noowner@pg.test", "--full-name", "No Owner", owner=owner
    )
    assert result.returncode == 2 and "schema-owner account" in result.stderr
    assert password not in result.stdout + result.stderr
    with stack.owner() as conn:
        assert one(conn, "SELECT count(*) FROM users WHERE email='noowner@pg.test'") == (0,)


def test_bootstrap_cli_never_accepts_a_password_argument(stack: Stack):
    result = bootstrap_cli(
        stack, "", "--email", "arg@pg.test", "--full-name", "Arg", "--password", "Xx-123456"
    )
    assert result.returncode == 2 and "unrecognized arguments" in result.stderr


def test_bootstrap_cli_rejects_weak_password_without_echoing_it(stack: Stack):
    result = bootstrap_cli(stack, "weakpass", "--email", "weak@pg.test", "--full-name", "Weak")
    assert result.returncode == 2 and "Invalid input" in result.stderr
    assert "weakpass" not in result.stdout + result.stderr


# ---- TC-16 over real HTTP --------------------------------------------------------------------
def test_tc16_restricted_staff_cannot_reach_admin_functions(stack: Stack, admin: dict, unique: str):
    victim = create_staff(stack, admin, unique, "sales", "victim")
    permissions = {  # the final matrix (2026-10-26)
        "sales": [
            "catalog:manage",
            "catalog:read",
            "inventory:adjust",
            "inventory:read",
            "orders:read",
            "promotions:read",
            "quotes:manage",
            "reviews:moderate",
            "services:manage",
            "services:read",
            "staff:self_read",
            "support:read",
            "support:reply",
        ],
        "operations": [
            "catalog:read",
            "delivery:read",
            "inventory:adjust",
            "inventory:read",
            "orders:fulfil",
            "orders:read",
            "staff:self_read",
        ],
        "management": [
            "catalog:read",
            "content:manage",
            "delivery:read",
            "inventory:read",
            "orders:read",
            "payments:read",
            "promotions:read",
            "reports:read",
            "services:read",
            "settings:read",
            "staff:self_read",
            "support:read",
        ],
        "finance": [
            "audit:read",
            "orders:read",
            "payments:read",
            "reports:read",
            "staff:self_read",
        ],
    }
    for role in ("sales", "operations", "management", "finance"):
        member = create_staff(stack, admin, unique, role, f"tc16{role}")
        h = login(stack.servers[1], member["email"], STAFF_PASSWORD)
        base = stack.servers[1]
        assert HTTP.get(f"{base}/staff/me", headers=h).json()["permissions"] == permissions[role]
        assert HTTP.get(f"{base}/staff", headers=h).status_code == 403
        audit_status = 200 if role == "finance" else 403  # audit:read
        assert HTTP.get(f"{base}/audit-logs", headers=h).status_code == audit_status
        new_admin = {
            "email": f"esc.{role}.{unique}@pg.test",
            "full_name": "Escalation",
            "password": STAFF_PASSWORD,
            "role": "administrator",
        }
        assert HTTP.post(f"{base}/staff", json=new_admin, headers=h).status_code == 403
        for target in (victim["id"], member["id"]):
            res = HTTP.patch(
                f"{base}/staff/{target}/role", json={"role": "administrator"}, headers=h
            )
            assert res.status_code == 403
            res = HTTP.patch(f"{base}/staff/{target}/status", json={"is_active": False}, headers=h)
            assert res.status_code == 403
    with stack.owner() as conn:
        assert one(
            conn, "SELECT count(*) FROM users WHERE email LIKE %s", f"esc.%.{unique}@pg.test"
        ) == (0,)
        assert one(
            conn,
            "SELECT count(*) FROM staff_role_assignments s JOIN users u ON u.id=s.user_id "
            "WHERE u.email LIKE %s AND s.role='administrator'",
            f"%.{unique}@pg.test",
        ) == (0,)


# ---- concurrency -----------------------------------------------------------------------------
def test_concurrent_duplicate_staff_creation_across_processes(
    stack: Stack, admin: dict, unique: str
):
    email = f"dup.staff.{unique}@pg.test"
    body = {"email": email, "full_name": "Dup Staff", "password": STAFF_PASSWORD, "role": "sales"}
    codes = parallel(
        lambda i: HTTP.post(f"{stack.servers[i % 2]}/staff", json=body, headers=admin).status_code,
        range(10),
    )
    assert sorted(codes) == [201] + [409] * 9
    with stack.owner() as conn:
        assert one(conn, "SELECT count(*) FROM users WHERE lower(email)=%s", email) == (1,)
        assert one(
            conn,
            "SELECT count(*) FROM audit_records a JOIN users u ON a.entity_id = u.id::text "
            "WHERE a.action='staff.create' AND u.email=%s",
            email,
        ) == (1,)


def test_concurrent_mutual_demotion_always_keeps_an_active_administrator(
    stack: Stack, admin: dict, unique: str
):
    a = create_staff(stack, admin, unique, "administrator", "mutual.a")
    b = create_staff(stack, admin, unique, "administrator", "mutual.b")
    ha = login(stack.servers[0], a["email"], STAFF_PASSWORD)
    hb = login(stack.servers[1], b["email"], STAFF_PASSWORD)
    with stack.owner() as conn:
        # Leave A and B as the only active administrators for this test.
        others = [
            r[0]
            for r in conn.execute(
                "SELECT u.id FROM users u JOIN staff_role_assignments s ON s.user_id=u.id "
                "WHERE s.role='administrator' AND u.is_active AND u.id NOT IN (%s, %s)",
                (a["id"], b["id"]),
            ).fetchall()
        ]
        conn.execute("UPDATE users SET is_active=false WHERE id = ANY(%s)", (others,))
    try:
        jobs = [
            (stack.servers[0], ha, b["id"], "role"),
            (stack.servers[1], hb, a["id"], "role"),
        ]

        def demote(job):
            base, headers, target, _ = job
            return HTTP.patch(
                f"{base}/staff/{target}/role", json={"role": "sales"}, headers=headers
            ).status_code

        codes = parallel(demote, jobs, workers=2)
        assert codes.count(200) == 1, codes
        assert set(codes) <= {200, 401, 403, 409}
        with stack.owner() as conn:
            active_admins = one(
                conn,
                "SELECT count(*) FROM users u JOIN staff_role_assignments s ON s.user_id=u.id "
                "WHERE s.role='administrator' AND u.is_active AND u.id IN (%s, %s)",
                a["id"],
                b["id"],
            )[0]
        assert active_admins == 1
    finally:
        with stack.owner() as conn:
            conn.execute("UPDATE users SET is_active=true WHERE id = ANY(%s)", (others,))


# ---- sessions --------------------------------------------------------------------------------
def test_role_change_and_disable_revoke_sessions_on_every_process(
    stack: Stack, admin: dict, unique: str
):
    member = create_staff(stack, admin, unique, "sales", "revoke")
    h = login(stack.servers[1], member["email"], STAFF_PASSWORD)
    res = HTTP.patch(
        f"{stack.servers[0]}/staff/{member['id']}/role", json={"role": "operations"}, headers=admin
    )
    assert res.status_code == 200
    assert HTTP.get(f"{stack.servers[1]}/staff/me", headers=h).status_code == 401
    with stack.owner() as conn:
        token = h["Authorization"].removeprefix("Bearer ")
        assert one(
            conn,
            "SELECT is_active, revoked_at IS NOT NULL FROM user_sessions WHERE token_hash=%s",
            hashlib.sha256(token.encode()).hexdigest(),
        ) == (False, True)
        summary = one(
            conn,
            "SELECT change_summary FROM audit_records WHERE action='staff.role_change' "
            "AND entity_id=%s",
            member["id"],
        )[0]
        assert summary["old_role"] == "sales" and summary["new_role"] == "operations"

    h2 = login(stack.servers[1], member["email"], STAFF_PASSWORD)
    assert HTTP.get(f"{stack.servers[1]}/staff/me", headers=h2).json()["role"] == "operations"
    res = HTTP.patch(
        f"{stack.servers[0]}/staff/{member['id']}/status", json={"is_active": False}, headers=admin
    )
    assert res.status_code == 200
    assert HTTP.get(f"{stack.servers[1]}/staff/me", headers=h2).status_code == 401
    res = HTTP.post(
        f"{stack.servers[1]}/auth/login",
        json={"identifier": member["email"], "password": STAFF_PASSWORD},
    )
    assert res.status_code == 403


# ---- database guarantees ---------------------------------------------------------------------
def test_database_allows_only_one_role_per_user(stack: Stack, admin: dict, unique: str):
    member = create_staff(stack, admin, unique, "sales", "onerole")
    with stack.owner() as conn, pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(
            "INSERT INTO staff_role_assignments (id, user_id, role) "
            "VALUES (gen_random_uuid(), %s, 'administrator')",
            (member["id"],),
        )


def test_runtime_role_can_assign_but_not_delete_staff_roles(stack: Stack, admin: dict):
    with stack.runtime() as conn:
        privileges = {
            p: one(conn, "SELECT has_table_privilege('staff_role_assignments', %s)", p)[0]
            for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
        }
        assert privileges == {
            "SELECT": True,
            "INSERT": True,
            "UPDATE": True,
            "DELETE": False,
            "TRUNCATE": False,
        }
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM staff_role_assignments")


# ---- audit atomicity -------------------------------------------------------------------------
def test_audit_failure_rolls_back_staff_changes_over_http(
    stack: Stack, admin: dict, unique: str, failing_audit
):
    actor = create_staff(stack, admin, unique, "administrator", "rb.actor")
    target = create_staff(stack, admin, unique, "sales", "rb.target")
    h = login(stack.servers[0], actor["email"], STAFF_PASSWORD)
    failing_audit(actor["email"])
    fresh = httpx.Client(timeout=60, headers={"Connection": "close"})
    base, tid = stack.servers[0], target["id"]
    attempts = {
        "create": fresh.post(
            f"{base}/staff",
            json={
                "email": f"rb.new.{unique}@pg.test",
                "full_name": "Rolled Back",
                "password": STAFF_PASSWORD,
                "role": "administrator",
            },
            headers=h,
        ),
        "update": fresh.patch(f"{base}/staff/{tid}", json={"full_name": "Rolled Back"}, headers=h),
        "role": fresh.patch(f"{base}/staff/{tid}/role", json={"role": "administrator"}, headers=h),
        "status": fresh.patch(f"{base}/staff/{tid}/status", json={"is_active": False}, headers=h),
    }
    assert {k: r.status_code for k, r in attempts.items()} == dict.fromkeys(attempts, 500)
    with stack.owner() as conn:
        assert one(
            conn, "SELECT count(*) FROM users WHERE email=%s", f"rb.new.{unique}@pg.test"
        ) == (0,)
        assert one(conn, "SELECT full_name, is_active FROM users WHERE id=%s", tid) == (
            "PG rb.target",
            True,
        )
        assert one(conn, "SELECT role FROM staff_role_assignments WHERE user_id=%s", tid) == (
            "sales",
        )


def test_customers_and_unauthenticated_callers_are_refused(stack: Stack, admin: dict, unique: str):
    customer = register(stack, stack.servers[0], f"cust.staff.{unique}@pg.test")
    me = HTTP.get(f"{stack.servers[0]}/staff/me", headers=admin).json()
    for headers, expected in ((customer["headers"], 403), ({}, 401)):
        assert HTTP.get(f"{stack.servers[1]}/staff/me", headers=headers).status_code == expected
        assert HTTP.get(f"{stack.servers[1]}/staff", headers=headers).status_code == expected
        res = HTTP.patch(
            f"{stack.servers[1]}/staff/{me['id']}/status",
            json={"is_active": False},
            headers=headers,
        )
        assert res.status_code == expected
    res = HTTP.patch(
        f"{stack.servers[0]}/staff/{customer['user']['id']}/role",
        json={"role": "administrator"},
        headers=admin,
    )
    assert res.status_code == 404
    with stack.owner() as conn:
        assert one(conn, "SELECT is_staff FROM users WHERE id=%s", customer["user"]["id"]) == (
            False,
        )
