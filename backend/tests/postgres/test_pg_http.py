"""Acceptance regression tests over real HTTP against PostgreSQL and Redis.

Every account is disposable (random email/phone). Assertions read PostgreSQL directly.
"""

import hashlib
import hmac
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
import psycopg
import pytest
from openapi_spec_validator import validate

from app.core.security import hash_reset_code
from tests.postgres.conftest import HMAC_KEY, LOGIN_WINDOW, Stack
from tests.support.credentials import random_password

# One keep-alive client: opening a new connection per call costs 0.5-2 s on Windows and would
# distort the timing-sensitive rate-limit window tests.
HTTP = httpx.Client(
    timeout=60, limits=httpx.Limits(max_connections=64, max_keepalive_connections=64)
)
PASSWORD = random_password()  # per run; never a fixed credential
ADDRESS = {
    "recipient_name": "Test Home",
    "phone": "0788123456",
    "district": "Gasabo",
    "street_address": "KG 11 Ave",
}


def ref(identifier: str) -> str:
    return hmac.new(HMAC_KEY.encode(), identifier.encode(), hashlib.sha256).hexdigest()


def register(
    stack: Stack, base: str, email: str | None = None, phone: str | None = None, **extra
) -> dict:
    """Register through the API. An email registration then verifies through the real endpoint
    with the link the server sent (console mail in the server log) and signs in, so the result
    always carries a session."""
    body = {"full_name": "PG Tester", "password": PASSWORD, **extra}
    if email:
        body["email"] = email
    if phone:
        body["phone"] = phone
    res = HTTP.post(f"{base}/auth/register", json=body, timeout=30)
    assert res.status_code == 201, res.text
    data = res.json()
    if data["verification_required"]:
        assert data["session_token"] is None
        token = stack.verification_token(body["email"])
        verified = HTTP.post(f"{base}/auth/email/verify", json={"token": token}, timeout=30)
        assert verified.status_code == 200, verified.text
        login = HTTP.post(
            f"{base}/auth/login",
            json={"identifier": body["email"], "password": body["password"]},
            timeout=30,
        )
        assert login.status_code == 200, login.text
        data.update(login.json())
    data["headers"] = {"Authorization": f"Bearer {data['session_token']}"}
    return data


def parallel(fn, items, workers: int = 10) -> list:
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(fn, items))


def one(conn: psycopg.Connection, sql: str, *args):
    return conn.execute(sql, args).fetchone()


# ---- registration ------------------------------------------------------------------------
def test_concurrent_duplicate_email_registration_across_processes(stack: Stack, unique: str):
    email = f"race.{unique}@pg.test"

    def attempt(i: int) -> int:
        base = stack.servers[i % 2]
        body = {"email": email, "full_name": "Race", "password": PASSWORD}
        return HTTP.post(f"{base}/auth/register", json=body, timeout=60).status_code

    codes = parallel(attempt, range(12), workers=12)
    assert sorted(codes) == [201] + [409] * 11
    with stack.owner() as conn:
        assert one(conn, "SELECT count(*) FROM users WHERE email=%s", email)[0] == 1


def test_concurrent_duplicate_phone_in_mixed_formats(stack: Stack, unique: str, phone_factory):
    canonical = phone_factory()
    formats = [canonical, canonical[1:], "0" + canonical[4:]]

    def attempt(i: int) -> int:
        body = {
            "email": f"ph{i}.{unique}@pg.test",
            "phone": formats[i % 3],
            "full_name": "Race",
            "password": PASSWORD,
        }
        return HTTP.post(f"{stack.servers[i % 2]}/auth/register", json=body, timeout=60).status_code

    codes = parallel(attempt, range(9), workers=9)
    assert sorted(codes) == [201] + [409] * 8
    with stack.owner() as conn:
        assert one(conn, "SELECT count(*) FROM users WHERE phone=%s", canonical)[0] == 1


def test_oversized_and_invalid_registration_input_is_422(stack: Stack, unique: str):
    base = stack.servers[0]
    cases = [
        {"email": "a" * 250 + f"{unique}@pg.test", "full_name": "Long", "password": PASSWORD},
        {"email": f"e.{unique}@pg.test", "full_name": "X" * 256, "password": PASSWORD},
        {"phone": "0688123456", "full_name": "Bad Phone", "password": PASSWORD},
        {"email": f"w.{unique}@pg.test", "full_name": "Weak", "password": "weakpass"},
    ]
    for body in cases:
        res = HTTP.post(f"{base}/auth/register", json=body, timeout=30)
        assert res.status_code == 422, body
        assert "sqlalchemy" not in res.text.lower() and "psycopg" not in res.text.lower()


def test_public_registration_creates_customer_only(stack: Stack, unique: str):
    email = f"esc.{unique}@pg.test"
    data = register(
        stack,
        stack.servers[0],
        email,
        role="administrator",
        roles=["administrator"],
        is_staff=True,
        is_active=False,
    )
    assert data["user"]["roles"] == ["customer"] and data["user"]["is_staff"] is False
    with stack.owner() as conn:
        assert one(conn, "SELECT is_staff, is_active FROM users WHERE email=%s", email) == (
            False,
            True,
        )
        assert one(
            conn,
            "SELECT count(*) FROM staff_role_assignments s JOIN users u ON u.id = s.user_id "
            "WHERE u.email=%s",
            email,
        ) == (0,)


# ---- phone normalisation -----------------------------------------------------------------
def test_login_with_every_approved_phone_format(stack: Stack, phone_factory):
    phone = phone_factory()
    register(stack, stack.servers[0], phone="0" + phone[4:])
    with stack.owner() as conn:
        assert one(conn, "SELECT count(*) FROM users WHERE phone=%s", phone)[0] == 1
    for identifier in (
        phone,
        phone[1:],
        "0" + phone[4:],
        f"0{phone[4:7]} {phone[7:10]} {phone[10:]}",
    ):
        res = HTTP.post(
            f"{stack.servers[1]}/auth/login",
            json={"identifier": identifier, "password": PASSWORD},
            timeout=30,
        )
        assert res.status_code == 200, identifier


def test_database_rejects_non_canonical_phone(stack: Stack, unique: str):
    with stack.owner() as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO users (id, email, phone) VALUES (%s, %s, '0788000000')",
            (uuid.uuid4(), f"chk.{unique}@pg.test"),
        )


# ---- audit atomicity ---------------------------------------------------------------------
def test_oversized_user_agent_change_is_persisted_with_audit(stack: Stack, unique: str):
    user = register(stack, stack.servers[0], f"ua.{unique}@pg.test")
    headers = {**user["headers"], "User-Agent": "X" * 600}
    res = HTTP.post(f"{stack.servers[0]}/customers/me/addresses", json=ADDRESS, headers=headers)
    assert res.status_code == 201
    login = HTTP.post(
        f"{stack.servers[0]}/auth/login",
        json={"identifier": f"ua.{unique}@pg.test", "password": PASSWORD},
        headers={"User-Agent": "Y" * 600},
    )
    assert login.status_code == 200
    with stack.owner() as conn:
        uid = user["user"]["id"]
        row = one(
            conn,
            "SELECT length(change_summary->>'user_agent') FROM audit_records "
            "WHERE actor_user_id=%s AND action='address.create'",
            uid,
        )
        assert row == (512,)
        assert one(
            conn, "SELECT max(length(user_agent)) FROM user_sessions WHERE user_id=%s", uid
        ) == (512,)


def test_audit_failure_rolls_back_protected_changes(stack: Stack, unique: str, failing_audit):
    email = f"rb.{unique}@pg.test"
    user = register(stack, stack.servers[0], email)
    base, h = stack.servers[0], user["headers"]
    first = HTTP.post(f"{base}/customers/me/addresses", json=ADDRESS, headers=h).json()
    failing_audit(email)
    # The server closes the connection after an unhandled 500; avoid keep-alive reuse races.
    fresh = httpx.Client(timeout=60, headers={"Connection": "close"})

    attempts = {
        "create": fresh.post(f"{base}/customers/me/addresses", json=ADDRESS, headers=h),
        "update": fresh.put(
            f"{base}/customers/me/addresses/{first['id']}",
            json={"recipient_name": "Rolled Back"},
            headers=h,
        ),
        "delete": fresh.delete(f"{base}/customers/me/addresses/{first['id']}", headers=h),
        "profile": fresh.patch(
            f"{base}/customers/me", json={"full_name": "Rolled Back"}, headers=h
        ),
        "logout": fresh.post(f"{base}/auth/logout", headers=h),
    }
    assert {k: r.status_code for k, r in attempts.items()} == dict.fromkeys(attempts, 500)

    with stack.owner() as conn:
        uid = user["user"]["id"]
        assert one(conn, "SELECT count(*) FROM addresses WHERE user_id=%s", uid) == (1,)
        assert one(conn, "SELECT recipient_name FROM addresses WHERE id=%s", first["id"]) == (
            "Test Home",
        )
        assert one(conn, "SELECT full_name FROM users WHERE id=%s", uid) == ("PG Tester",)
        assert one(
            conn,
            "SELECT count(*) FROM user_sessions WHERE user_id=%s AND revoked_at IS NOT NULL",
            uid,
        ) == (0,)
    assert fresh.get(f"{base}/auth/me", headers=h).status_code == 200  # logout rolled back


# ---- default address under concurrency ---------------------------------------------------
def _defaults(stack: Stack, uid: str) -> tuple[int, int]:
    with stack.owner() as conn:
        return one(
            conn,
            "SELECT count(*), count(*) FILTER (WHERE is_default) FROM addresses WHERE user_id=%s",
            uid,
        )


def test_concurrent_first_addresses_produce_exactly_one_default(stack: Stack, unique: str):
    user = register(stack, stack.servers[0], f"first.{unique}@pg.test")

    def create(i: int) -> tuple[int, str | None]:
        res = HTTP.post(
            f"{stack.servers[i % 2]}/customers/me/addresses",
            json={**ADDRESS, "recipient_name": f"Rcpt {i}", "is_default": False},
            headers=user["headers"],
            timeout=60,
        )
        code = None if res.status_code == 201 else res.json().get("error", {}).get("code")
        return res.status_code, code

    # Was flaky once (2026-10-23) without a recorded cause; the messages below record status and
    # error code per request plus the stored counts, so any recurrence explains itself.
    results = parallel(create, range(10))
    counts = _defaults(stack, user["user"]["id"])
    assert results == [(201, None)] * 10, f"responses={results} (addresses, defaults)={counts}"
    assert counts == (10, 1), f"(addresses, defaults)={counts}"


def test_concurrent_create_as_default_produces_exactly_one_default(stack: Stack, unique: str):
    user = register(stack, stack.servers[0], f"cdef.{unique}@pg.test")

    def create(i: int) -> int:
        return HTTP.post(
            f"{stack.servers[i % 2]}/customers/me/addresses",
            json={**ADDRESS, "recipient_name": f"Rcpt {i}", "is_default": True},
            headers=user["headers"],
            timeout=60,
        ).status_code

    assert parallel(create, range(10)) == [201] * 10
    assert _defaults(stack, user["user"]["id"]) == (10, 1)


def test_concurrent_set_default_and_delete_keep_exactly_one_default(stack: Stack, unique: str):
    user = register(stack, stack.servers[0], f"sdef.{unique}@pg.test")
    base, h = stack.servers[0], user["headers"]
    ids = [
        HTTP.post(
            f"{base}/customers/me/addresses",
            json={**ADDRESS, "recipient_name": f"R{i:02}"},
            headers=h,
        ).json()["id"]
        for i in range(10)
    ]

    def set_default(i: int) -> int:
        url = f"{stack.servers[i % 2]}/customers/me/addresses/{ids[i]}/default"
        return HTTP.post(url, headers=h, timeout=60).status_code

    assert parallel(set_default, range(10)) == [200] * 10
    assert _defaults(stack, user["user"]["id"]) == (10, 1)

    def delete(i: int) -> int:
        url = f"{stack.servers[i % 2]}/customers/me/addresses/{ids[i]}"
        return HTTP.delete(url, headers=h, timeout=60).status_code

    assert parallel(delete, range(0, 10, 2)) == [200] * 5  # deletes include the current default
    assert _defaults(stack, user["user"]["id"]) == (5, 1)


def test_unsetting_default_rejected_and_db_constraint_backstop(stack: Stack, unique: str):
    user = register(stack, stack.servers[0], f"uns.{unique}@pg.test")
    base, h = stack.servers[0], user["headers"]
    first = HTTP.post(f"{base}/customers/me/addresses", json=ADDRESS, headers=h).json()
    second = HTTP.post(f"{base}/customers/me/addresses", json=ADDRESS, headers=h).json()
    res = HTTP.put(
        f"{base}/customers/me/addresses/{first['id']}", json={"is_default": False}, headers=h
    )
    assert res.status_code == 422
    with stack.owner() as conn, pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute("UPDATE addresses SET is_default = true WHERE id=%s", (second["id"],))


# ---- ownership ---------------------------------------------------------------------------
def test_cross_customer_access_blocked_and_rows_unchanged(stack: Stack, unique: str):
    alice = register(stack, stack.servers[0], f"alice.{unique}@pg.test")
    bob = register(stack, stack.servers[1], f"bob.{unique}@pg.test")
    base = stack.servers[0]
    addr = HTTP.post(
        f"{base}/customers/me/addresses", json=ADDRESS, headers=alice["headers"]
    ).json()
    with stack.owner() as conn:
        before = one(conn, "SELECT * FROM addresses WHERE id=%s", addr["id"])
    url = f"{base}/customers/me/addresses/{addr['id']}"
    codes = [
        HTTP.get(url, headers=bob["headers"]).status_code,
        HTTP.put(url, json={"recipient_name": "Hacked"}, headers=bob["headers"]).status_code,
        HTTP.post(f"{url}/default", headers=bob["headers"]).status_code,
        HTTP.delete(url, headers=bob["headers"]).status_code,
    ]
    assert codes == [404] * 4
    created = HTTP.post(
        f"{base}/customers/me/addresses",
        json={**ADDRESS, "user_id": alice["user"]["id"]},
        headers=bob["headers"],
    ).json()
    with stack.owner() as conn:
        assert one(conn, "SELECT * FROM addresses WHERE id=%s", addr["id"]) == before
        assert (
            str(one(conn, "SELECT user_id FROM addresses WHERE id=%s", created["id"])[0])
            == bob["user"]["id"]
        )


def test_customer_cannot_change_role_via_profile(stack: Stack, unique: str):
    user = register(stack, stack.servers[0], f"role.{unique}@pg.test")
    res = HTTP.patch(
        f"{stack.servers[0]}/customers/me", json={"role": "admin"}, headers=user["headers"]
    )
    assert res.status_code == 422
    with stack.owner() as conn:
        uid = user["user"]["id"]
        assert one(conn, "SELECT is_staff FROM users WHERE id=%s", uid) == (False,)
        assert one(conn, "SELECT count(*) FROM staff_role_assignments WHERE user_id=%s", uid) == (
            0,
        )


# ---- sessions ----------------------------------------------------------------------------
def test_session_expiry_and_revocation(stack: Stack, unique: str):
    email = f"sess.{unique}@pg.test"
    register(stack, stack.servers[0], email)
    login = lambda: HTTP.post(  # noqa: E731
        f"{stack.servers[1]}/auth/login", json={"identifier": email, "password": PASSWORD}
    ).json()["session_token"]
    t1, t2 = login(), login()
    h1, h2 = {"Authorization": f"Bearer {t1}"}, {"Authorization": f"Bearer {t2}"}

    assert HTTP.post(f"{stack.servers[0]}/auth/logout", headers=h1).status_code == 200
    assert HTTP.get(f"{stack.servers[1]}/auth/me", headers=h1).status_code == 401
    with stack.owner() as conn:
        digest = hashlib.sha256(t1.encode()).hexdigest()
        assert one(
            conn,
            "SELECT is_active, revoked_at IS NOT NULL FROM user_sessions WHERE token_hash=%s",
            digest,
        ) == (False, True)
        conn.execute(
            "UPDATE user_sessions SET expires_at = now() - interval '1 second' WHERE token_hash=%s",
            (hashlib.sha256(t2.encode()).hexdigest(),),
        )
    assert HTTP.get(f"{stack.servers[0]}/auth/me", headers=h2).status_code == 401


def test_invalid_tokens_cannot_flood_the_audit_log(stack: Stack, unique: str):
    """QA D-11: unknown tokens write nothing; a stale session is audited once per window."""
    user = register(stack, stack.servers[0], f"flood.{unique}@pg.test")
    assert HTTP.post(f"{stack.servers[0]}/auth/logout", headers=user["headers"]).status_code == 200
    unknown = [{"Authorization": f"Bearer {uuid.uuid4().hex}{uuid.uuid4().hex}"} for _ in range(20)]

    def call(i: int) -> int:
        headers = user["headers"] if i % 2 else unknown[i // 2]
        return HTTP.get(f"{stack.servers[i % 2]}/auth/me", headers=headers).status_code

    assert parallel(call, range(40)) == [401] * 40
    digest = hashlib.sha256(user["session_token"].encode()).hexdigest()
    with stack.owner() as conn:
        (session_id,) = one(conn, "SELECT id::text FROM user_sessions WHERE token_hash=%s", digest)
        rows = conn.execute(
            "SELECT entity_id, change_summary->>'reason' FROM audit_records "
            "WHERE action = 'auth.session_invalid' AND entity_id IN (%s, 'unknown')",
            (session_id,),
        ).fetchall()
    assert rows == [(session_id, "session_revoked")]


def test_a_reset_code_can_be_used_only_once_under_concurrency(stack: Stack, unique: str):
    """Ten simultaneous resets with one valid code across two processes: exactly one succeeds."""
    email = f"reset.{unique}@pg.test"
    user = register(stack, stack.servers[0], email)
    # Issue a code through the API (runtime role inserts it), then replace it with a known one.
    res = HTTP.post(f"{stack.servers[1]}/auth/forgot-password", json={"identifier": email})
    assert res.status_code == 202
    code = "482913"
    with stack.owner() as conn:
        updated = conn.execute(
            "UPDATE password_reset_codes SET code_hash = %s "
            "WHERE user_id = %s AND consumed_at IS NULL",
            (hash_reset_code(user["user"]["id"], code, HMAC_KEY), user["user"]["id"]),
        ).rowcount
    assert updated == 1

    def attempt(i: int) -> int:
        body = {"identifier": email, "code": code, "new_password": f"Parallel-Pass-{i:02d}"}
        return HTTP.post(f"{stack.servers[i % 2]}/auth/reset-password", json=body).status_code

    results = parallel(attempt, range(10))
    assert sorted(results) == [200] + [422] * 9, results
    with stack.owner() as conn:
        assert one(
            conn,
            "SELECT count(*) FILTER (WHERE consumed_at IS NULL), count(*) "
            "FROM password_reset_codes WHERE user_id = %s",
            user["user"]["id"],
        ) == (0, 1)
        assert one(
            conn,
            "SELECT count(*) FROM audit_records WHERE action = 'auth.password_reset' "
            "AND change_summary->>'status' = 'success' AND actor_user_id = %s",
            user["user"]["id"],
        ) == (1,)
    assert HTTP.get(f"{stack.servers[0]}/auth/me", headers=user["headers"]).status_code == 401


# ---- audit immutability and privileges ---------------------------------------------------
def test_audit_records_append_only_even_for_owner(stack: Stack, unique: str):
    register(stack, stack.servers[0], f"aud.{unique}@pg.test")
    with stack.owner() as conn:
        rid = one(conn, "SELECT id FROM audit_records LIMIT 1")[0]
        for stmt in (
            "UPDATE audit_records SET note='tampered' WHERE id=%s",
            "DELETE FROM audit_records WHERE id=%s",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(stmt, (rid,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("TRUNCATE audit_records")


def test_runtime_role_cannot_modify_audit_records(stack: Stack, unique: str):
    register(stack, stack.servers[0], f"rt.{unique}@pg.test")
    with stack.runtime() as conn:
        rid = one(conn, "SELECT id FROM audit_records LIMIT 1")[0]  # SELECT allowed
        for stmt in (
            "UPDATE audit_records SET note='x' WHERE id=%s",
            "DELETE FROM audit_records WHERE id=%s",
            "ALTER TABLE audit_records DISABLE TRIGGER audit_records_append_only",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(stmt, (rid,) if "%s" in stmt else None)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("TRUNCATE audit_records")
        is_super = one(conn, "SELECT rolsuper FROM pg_roles WHERE rolname = current_user")[0]
        assert is_super is False


def test_user_deletion_still_allowed_and_audit_history_kept(stack: Stack, unique: str):
    user = register(stack, stack.servers[0], f"del.{unique}@pg.test")
    uid = user["user"]["id"]
    with stack.owner() as conn:
        before = one(conn, "SELECT count(*) FROM audit_records WHERE entity_id=%s", uid)[0]
        conn.execute("DELETE FROM users WHERE id=%s", (uid,))
        after = one(
            conn, "SELECT count(*), count(actor_user_id) FROM audit_records WHERE entity_id=%s", uid
        )
    assert before >= 1 and after == (before, 0)  # rows kept; only FK actor_id cleared


def test_failed_login_audit_is_pseudonymised(stack: Stack, unique: str):
    email = f"pii.{unique}@pg.test"
    register(stack, stack.servers[0], email)
    HTTP.post(f"{stack.servers[0]}/auth/login", json={"identifier": email, "password": "Wrong1!x"})
    with stack.owner() as conn:
        rows = conn.execute(
            "SELECT change_summary FROM audit_records WHERE action='auth.login' "
            "AND change_summary->>'status'='failure' AND entity_type='login_identifier' "
            "AND entity_id = %s",
            (ref(email),),
        ).fetchall()
        leaked = one(
            conn,
            "SELECT count(*) FROM audit_records WHERE change_summary::text LIKE %s "
            "OR (entity_type='login_identifier' AND entity_id LIKE %s)",
            f"%{email}%",
            f"%{email}%",
        )
    assert len(rows) == 1 and leaked == (0,)


# ---- rate limiting (real Redis, two processes) -------------------------------------------
def _attempt(
    stack: Stack, i: int, identifier: str, password: str = "Wrong1!pass"
) -> httpx.Response:
    return HTTP.post(
        f"{stack.servers[i % 2]}/auth/login",
        json={"identifier": identifier, "password": password},
        timeout=30,
    )


def test_identifier_limit_shared_across_processes_then_resets(stack: Stack, unique: str):
    email = f"rl.{unique}@pg.test"
    register(stack, stack.servers[0], email)
    started = time.monotonic()
    codes = [_attempt(stack, i, email).status_code for i in range(5)]
    assert codes == [401] * 5
    blocked = [_attempt(stack, i, email, PASSWORD) for i in range(2)]  # correct password, both
    assert [r.status_code for r in blocked] == [429, 429]
    assert time.monotonic() - started < LOGIN_WINDOW, "attempts outlived the test window"
    assert all(0 < int(r.headers["Retry-After"]) <= LOGIN_WINDOW for r in blocked)
    with stack.owner() as conn:
        assert one(
            conn,
            "SELECT count(*) FROM audit_records WHERE change_summary->>'status'='rate_limited' "
            "AND entity_type='login_identifier' AND entity_id=%s",
            ref(email),
        ) == (2,)
    time.sleep(LOGIN_WINDOW + 1)
    assert _attempt(stack, 0, email, PASSWORD).status_code == 200


def test_unknown_identifier_limited_identically(stack: Stack, unique: str):
    real = f"real.{unique}@pg.test"
    register(stack, stack.servers[0], real)
    fake = f"ghost.{unique}@pg.test"
    real_codes = [_attempt(stack, i, real).status_code for i in range(6)]
    fake_codes = [_attempt(stack, i, fake).status_code for i in range(6)]
    assert real_codes == fake_codes == [401] * 5 + [429]


def test_ip_limit_blocks_spraying_across_identifiers(stack: Stack, unique: str):
    codes = [_attempt(stack, i, f"spray{i}.{unique}@pg.test").status_code for i in range(20)]
    assert codes == [401] * 20
    assert _attempt(stack, 0, f"fresh.{unique}@pg.test").status_code == 429


# ---- OpenAPI -----------------------------------------------------------------------------
EXPECTED_OPERATIONS = {
    ("get", "/"),
    ("get", "/api/v1/health"),
    ("post", "/api/v1/auth/register"),
    ("post", "/api/v1/auth/login"),
    ("post", "/api/v1/auth/logout"),
    ("post", "/api/v1/auth/logout-all"),
    ("post", "/api/v1/auth/change-password"),
    ("post", "/api/v1/auth/forgot-password"),
    ("post", "/api/v1/auth/reset-password"),
    ("post", "/api/v1/auth/email/verify"),  # email verification (2026-11-12)
    ("post", "/api/v1/auth/email/verification/resend"),
    ("get", "/api/v1/auth/me"),
    ("post", "/api/v1/auth/google/start"),  # Continue with Google (2026-11-11)
    ("post", "/api/v1/auth/google/callback"),
    ("post", "/api/v1/auth/google/link/start"),
    ("post", "/api/v1/auth/google/link/callback"),
    ("get", "/api/v1/customers/me"),
    ("patch", "/api/v1/customers/me"),
    ("get", "/api/v1/customers/me/orders/{order_id}"),
    ("get", "/api/v1/customers/me/orders/number/{order_number}"),
    ("get", "/api/v1/customers/me/orders/{order_id}/invoice"),
    ("get", "/api/v1/customers/me/orders"),
    ("post", "/api/v1/checkout"),
    ("post", "/api/v1/orders/lookup"),
    ("get", "/api/v1/staff/orders"),
    ("get", "/api/v1/staff/orders/assignees"),
    ("get", "/api/v1/staff/orders/{order_id}"),
    ("post", "/api/v1/payments/{order_number}/initiate"),
    ("post", "/api/v1/payments/{order_number}/method"),  # frontend phase 4 (2026-10-27)
    ("get", "/api/v1/payments/{order_number}/status"),
    ("post", "/api/v1/webhooks/{provider}"),
    ("get", "/api/v1/staff/payments"),
    ("get", "/api/v1/staff/payments/events"),
    ("post", "/api/v1/staff/payments/{attempt_id}/confirm-cod"),
    ("get", "/api/v1/customers/me/addresses"),
    ("post", "/api/v1/customers/me/addresses"),
    ("get", "/api/v1/customers/me/addresses/{address_id}"),
    ("put", "/api/v1/customers/me/addresses/{address_id}"),
    ("delete", "/api/v1/customers/me/addresses/{address_id}"),
    ("post", "/api/v1/customers/me/addresses/{address_id}/default"),
    # Module 21 wishlist (SC-01, 2026-10-27).
    ("get", "/api/v1/customers/me/wishlist"),
    ("get", "/api/v1/customers/me/wishlist/ids"),
    ("put", "/api/v1/customers/me/wishlist/{product_id}"),
    ("delete", "/api/v1/customers/me/wishlist/{product_id}"),
    # Module 20 reviews part 2 (SC-01, 2026-10-27).
    ("post", "/api/v1/customers/me/orders/{order_id}/items/{order_item_id}/review-link"),
    ("post", "/api/v1/orders/review-link"),
    ("get", "/api/v1/reviews/{token}"),
    ("post", "/api/v1/reviews/{token}"),
    ("get", "/api/v1/catalog/products/{slug}/reviews"),
    ("get", "/api/v1/staff/reviews"),
    ("post", "/api/v1/staff/reviews/{review_id}/approve"),
    ("post", "/api/v1/staff/reviews/{review_id}/reject"),
    ("get", "/api/v1/staff/me"),
    ("get", "/api/v1/staff/me/permissions"),
    ("get", "/api/v1/staff"),
    ("post", "/api/v1/staff"),
    ("get", "/api/v1/staff/{staff_id}"),
    ("patch", "/api/v1/staff/{staff_id}"),
    ("patch", "/api/v1/staff/{staff_id}/status"),
    ("get", "/api/v1/staff/categories"),
    ("post", "/api/v1/staff/categories"),
    ("patch", "/api/v1/staff/categories/{category_id}"),
    ("delete", "/api/v1/staff/categories/{category_id}"),
    ("put", "/api/v1/staff/categories/order"),  # category hierarchy (2026-11-16)
    ("put", "/api/v1/staff/categories/{category_id}/menu-brands"),  # menu brands (2026-11-16)
    ("post", "/api/v1/staff/categories/{category_id}/image"),
    ("delete", "/api/v1/staff/categories/{category_id}/image"),
    ("get", "/api/v1/staff/brands"),
    ("post", "/api/v1/staff/brands"),
    ("patch", "/api/v1/staff/brands/{brand_id}"),
    ("delete", "/api/v1/staff/brands/{brand_id}"),
    ("post", "/api/v1/staff/brands/{brand_id}/logo"),
    ("delete", "/api/v1/staff/brands/{brand_id}/logo"),
    ("get", "/api/v1/staff/media/cleanup-problems"),
    ("get", "/api/v1/banners"),
    ("get", "/api/v1/staff/banners"),
    ("post", "/api/v1/staff/banners"),
    ("patch", "/api/v1/staff/banners/{banner_id}"),
    ("delete", "/api/v1/staff/banners/{banner_id}"),
    ("post", "/api/v1/staff/banners/{banner_id}/image"),
    ("delete", "/api/v1/staff/banners/{banner_id}/image"),
    ("get", "/api/v1/staff/jobs/{job_id}"),
    ("post", "/api/v1/staff/jobs/{job_id}/retry-failed"),
    ("get", "/api/v1/staff/products"),
    ("get", "/api/v1/staff/products/{product_id}"),
    ("post", "/api/v1/staff/products/bulk-images"),
    ("post", "/api/v1/staff/products/bulk-activate"),
    ("post", "/api/v1/staff/products"),
    ("patch", "/api/v1/staff/products/{product_id}"),
    ("post", "/api/v1/staff/products/{product_id}/variants"),
    ("patch", "/api/v1/staff/products/{product_id}/variants/{variant_id}"),
    ("delete", "/api/v1/staff/products/{product_id}/variants/{variant_id}"),
    ("post", "/api/v1/staff/products/{product_id}/images"),
    ("put", "/api/v1/staff/products/{product_id}/images/order"),
    ("patch", "/api/v1/staff/images/{image_id}"),
    ("delete", "/api/v1/staff/images/{image_id}"),
    ("post", "/api/v1/staff/imports"),
    ("get", "/api/v1/staff/imports/template"),
    ("get", "/api/v1/staff/imports/{job_id}"),
    ("patch", "/api/v1/staff/orders/{order_id}/status"),
    ("patch", "/api/v1/staff/orders/{order_id}/assignment"),
    ("get", "/api/v1/staff/orders/{order_id}/invoice"),
    ("post", "/api/v1/staff/orders/{order_id}/invoice"),
    ("get", "/api/v1/staff/orders/{order_id}/delivery-note"),
    ("get", "/api/v1/staff/notifications"),
    ("post", "/api/v1/staff/notifications/{notification_id}/retry"),
    ("get", "/api/v1/staff/reports/sales"),
    ("get", "/api/v1/staff/reports/top-products"),
    ("get", "/api/v1/staff/reports/stock"),
    ("get", "/api/v1/staff/reports/{report_type}/export"),
    # Module 19 settings and content (2026-10-29).
    ("get", "/api/v1/settings"),
    ("get", "/api/v1/pages/{slug}"),
    ("get", "/api/v1/staff/pages"),
    ("put", "/api/v1/staff/pages/{slug}"),
    ("post", "/api/v1/quote-requests"),
    ("get", "/api/v1/staff/quote-requests"),
    ("patch", "/api/v1/staff/quote-requests/{quote_id}"),
    # Customer support messages (2026-11-11).
    ("post", "/api/v1/support-messages"),
    ("get", "/api/v1/support-messages/{reference}/{key}"),
    ("post", "/api/v1/support-messages/{reference}/{key}/messages"),
    ("get", "/api/v1/customers/me/support-threads"),
    ("get", "/api/v1/customers/me/support-threads/{reference}"),
    ("post", "/api/v1/customers/me/support-threads/{reference}/messages"),
    ("get", "/api/v1/staff/support-threads"),
    ("get", "/api/v1/staff/support-threads/{thread_id}"),
    ("patch", "/api/v1/staff/support-threads/{thread_id}"),
    ("post", "/api/v1/staff/support-threads/{thread_id}/messages"),
    # Technical services and service requests (ADR-013, SC-02).
    ("get", "/api/v1/services"),
    ("get", "/api/v1/services/{slug}"),
    ("post", "/api/v1/services/{slug}/requests"),
    ("get", "/api/v1/staff/services"),
    ("post", "/api/v1/staff/services"),
    ("put", "/api/v1/staff/services/order"),
    ("patch", "/api/v1/staff/services/{service_id}"),
    ("delete", "/api/v1/staff/services/{service_id}"),
    ("post", "/api/v1/staff/services/{service_id}/image"),
    ("delete", "/api/v1/staff/services/{service_id}/image"),
    ("post", "/api/v1/staff/services/{service_id}/items"),
    ("put", "/api/v1/staff/services/{service_id}/items/order"),
    ("patch", "/api/v1/staff/services/{service_id}/items/{item_id}"),
    ("delete", "/api/v1/staff/services/{service_id}/items/{item_id}"),
    ("get", "/api/v1/staff/service-requests"),
    ("get", "/api/v1/staff/service-requests/assignees"),
    ("get", "/api/v1/staff/service-requests/{request_id}"),
    ("patch", "/api/v1/staff/service-requests/{request_id}"),
    ("get", "/api/v1/audit-logs"),
    ("get", "/api/v1/catalog/categories"),
    ("get", "/api/v1/catalog/brands"),
    ("get", "/api/v1/catalog/products"),
    ("get", "/api/v1/catalog/products/{slug}"),
    ("get", "/api/v1/catalog/facets"),
    ("get", "/api/v1/cart"),
    ("post", "/api/v1/cart/items"),
    ("patch", "/api/v1/cart/items/{item_id}"),
    ("delete", "/api/v1/cart/items/{item_id}"),
    ("post", "/api/v1/cart/merge"),
    ("get", "/api/v1/delivery/zones"),
    ("get", "/api/v1/staff/delivery/zones"),
    ("post", "/api/v1/staff/delivery/zones"),
    ("patch", "/api/v1/staff/delivery/zones/{zone_id}"),
    ("get", "/api/v1/staff/settings"),
    ("patch", "/api/v1/staff/settings"),
    ("post", "/api/v1/cart/apply-code"),
    ("delete", "/api/v1/cart/code"),
    ("post", "/api/v1/cart/accept-prices"),  # frontend phase 4 (2026-10-27)
    ("get", "/api/v1/staff/promotions"),
    ("post", "/api/v1/staff/promotions"),
    ("get", "/api/v1/staff/promotions/{promotion_id}"),
    ("patch", "/api/v1/staff/promotions/{promotion_id}"),
    ("get", "/api/v1/inventory"),
    ("get", "/api/v1/inventory/{sku}"),
    ("post", "/api/v1/inventory/{sku}/adjustments"),
    # Marketplace sellers (ADR-014 phase 1): applications, the seller's store, staff review.
    ("post", "/api/v1/seller/application"),
    ("get", "/api/v1/seller/application"),
    ("put", "/api/v1/seller/application"),
    ("get", "/api/v1/seller/store"),
    ("patch", "/api/v1/seller/store"),
    # ADR-014 phase 2: the seller's own catalogue and the public stores
    ("get", "/api/v1/seller/products"),
    ("post", "/api/v1/seller/products"),
    ("get", "/api/v1/seller/products/{product_id}"),
    ("patch", "/api/v1/seller/products/{product_id}"),
    ("post", "/api/v1/seller/products/{product_id}/variants"),
    ("patch", "/api/v1/seller/products/{product_id}/variants/{variant_id}"),
    ("delete", "/api/v1/seller/products/{product_id}/variants/{variant_id}"),
    ("post", "/api/v1/seller/products/{product_id}/images"),
    ("put", "/api/v1/seller/products/{product_id}/images/order"),
    ("patch", "/api/v1/seller/images/{image_id}"),
    ("delete", "/api/v1/seller/images/{image_id}"),
    ("get", "/api/v1/seller/inventory"),
    ("get", "/api/v1/seller/inventory/{sku}"),
    ("post", "/api/v1/seller/inventory/{sku}/adjustments"),
    ("post", "/api/v1/seller/store/logo"),
    ("delete", "/api/v1/seller/store/logo"),
    ("post", "/api/v1/seller/store/cover"),
    ("delete", "/api/v1/seller/store/cover"),
    ("get", "/api/v1/stores"),
    ("get", "/api/v1/stores/{slug}"),
    ("get", "/api/v1/staff/sellers"),
    ("get", "/api/v1/staff/sellers/{store_id}"),
    ("patch", "/api/v1/staff/sellers/{store_id}/status"),
    ("patch", "/api/v1/staff/sellers/{store_id}/commission"),
}
PUBLIC = {
    ("get", "/"),
    ("get", "/api/v1/stores"),  # approved stores (ADR-014 phase 2)
    ("get", "/api/v1/stores/{slug}"),
    ("get", "/api/v1/health"),
    ("get", "/api/v1/banners"),  # storefront banners (2026-10-26)
    ("post", "/api/v1/auth/register"),
    ("post", "/api/v1/auth/login"),
    ("post", "/api/v1/auth/forgot-password"),
    ("post", "/api/v1/auth/reset-password"),
    ("post", "/api/v1/auth/email/verify"),  # email verification (2026-11-12)
    ("post", "/api/v1/auth/email/verification/resend"),
    ("post", "/api/v1/auth/google/start"),  # Continue with Google (2026-11-11)
    ("post", "/api/v1/auth/google/callback"),
    ("get", "/api/v1/catalog/categories"),
    ("get", "/api/v1/catalog/brands"),
    ("get", "/api/v1/catalog/products"),
    ("get", "/api/v1/catalog/products/{slug}"),
    ("get", "/api/v1/catalog/facets"),
    ("get", "/api/v1/delivery/zones"),
    ("post", "/api/v1/orders/lookup"),
    ("post", "/api/v1/webhooks/{provider}"),
    # Review links are capabilities: the token (or the guest's order lookup) is the credential.
    ("post", "/api/v1/orders/review-link"),
    ("get", "/api/v1/reviews/{token}"),
    ("post", "/api/v1/reviews/{token}"),
    ("get", "/api/v1/catalog/products/{slug}/reviews"),
    # Module 19: the store's public settings, policy pages and business quote requests.
    ("get", "/api/v1/settings"),
    ("get", "/api/v1/pages/{slug}"),
    ("post", "/api/v1/quote-requests"),
    # Support conversations without an account: the reference and private key are the
    # credential.
    ("get", "/api/v1/support-messages/{reference}/{key}"),
    ("post", "/api/v1/support-messages/{reference}/{key}/messages"),
    # Technical services (ADR-013): the list, a service's page and requesting it.
    ("get", "/api/v1/services"),
    ("get", "/api/v1/services/{slug}"),
    ("post", "/api/v1/services/{slug}/requests"),
}
SENSITIVE = {"password_hash", "token_hash"}


def test_live_openapi_is_valid_complete_and_accurate(stack: Stack):
    spec = HTTP.get(stack.servers[0].replace("/api/v1", "") + "/api/v1/openapi.json").json()
    validate(spec)  # OpenAPI 3.1 schema validation
    ops = {(m, p): o for p, item in spec["paths"].items() for m, o in item.items()}
    assert set(ops) == EXPECTED_OPERATIONS
    for key, op in ops.items():
        codes = set(op["responses"])
        assert "400" not in codes, key  # validation errors are 422, never 400
        if key in PUBLIC:
            assert "security" not in op, key
        else:
            assert op["security"] == [{"BearerAuth": []}], key
            # logging out validates only the session token, so it cannot return 403
            logouts = {("post", "/api/v1/auth/logout"), ("post", "/api/v1/auth/logout-all")}
            expected = {"401"} if key in logouts else {"401", "403"}
            assert expected <= codes, key
            assert op["responses"]["401"]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ErrorResponse"
            }
    login = ops[("post", "/api/v1/auth/login")]["responses"]
    assert {"401", "403", "422", "429", "503"} <= set(login) and "Retry-After" in login["429"][
        "headers"
    ]
    assert {"409", "422"} <= set(ops[("post", "/api/v1/auth/register")]["responses"])
    schemas = spec["components"]["schemas"]
    for name, schema in schemas.items():
        assert not SENSITIVE & set(schema.get("properties", {})), name
    assert {t["name"] for t in spec["tags"]} >= {t for o in ops.values() for t in o["tags"]}
