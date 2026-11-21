"""In-process (TestClient) smoke checks against a DISPOSABLE PostgreSQL test database.

This is NOT a real-HTTP test: requests go through Starlette's TestClient inside this process.
Real-HTTP coverage lives in backend/tests/postgres.

The script writes rows, so it only runs against a database you name and confirm as disposable:

    SMOKE_DATABASE_URL        runtime (least-privilege) account the API uses
    SMOKE_OWNER_DATABASE_URL  owner account for setup and assertions (default: SMOKE_DATABASE_URL)
    SMOKE_CONFIRM_DISPOSABLE  must equal the database name, e.g. rwanda_smoke_test
    SMOKE_REDIS_URL           optional (default: TEST_REDIS_URL, then redis://127.0.0.1:6379/15)

These may be set in the shell or in backend/.env (the shell wins).

DATABASE_URL and MIGRATION_DATABASE_URL (backend/.env) are never used. It refuses unless the
database name ends in "_test", the host is loopback, APP_ENV is development, the confirmation
matches, the target is not the database configured in backend/.env, and the database holds no
staff account outside the reserved test domains. If isolation cannot be verified, it stops.

Each run uses a random run ID, random passwords and a random audit HMAC key; none are printed
or stored. Accounts are named for the run (smoke.<run>.*@smoke.invalid) and only those rows are
deleted afterwards. Audit records are append-only and are kept.
"""

import hashlib
import os
import secrets
import string
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dotenv import dotenv_values
from sqlalchemy.engine import URL, make_url

if TYPE_CHECKING:
    import psycopg

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
BACKEND_ENV = BACKEND_DIR / ".env"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
SMOKE_DOMAIN = "smoke.invalid"
# Staff accounts outside these domains mean the database may hold real data.
RESERVED_TEST_EMAIL_PATTERNS = ("%.invalid", "%.test", "%@example.com")


class SmokeRefused(Exception):
    """The target database could not be verified as disposable; nothing was written."""


def _target(url: URL) -> tuple[str | None, int, str | None]:
    return (url.host, url.port or 5432, url.database)


def resolve_target(env: Mapping[str, str], dotenv: Mapping[str, str | None]) -> tuple[URL, URL]:
    """Check the configuration before any connection. Returns (runtime_url, owner_url)."""
    runtime_raw = (env.get("SMOKE_DATABASE_URL") or "").strip()
    if not runtime_raw:
        raise SmokeRefused("Set SMOKE_DATABASE_URL to a disposable test database.")
    owner_raw = (env.get("SMOKE_OWNER_DATABASE_URL") or "").strip() or runtime_raw
    try:
        runtime, owner = make_url(runtime_raw), make_url(owner_raw)
    except Exception:
        raise SmokeRefused("SMOKE_DATABASE_URL / SMOKE_OWNER_DATABASE_URL are not valid.") from None

    if _target(runtime) != _target(owner):
        raise SmokeRefused("The runtime and owner URLs must point to the same database.")
    host, _, dbname = _target(runtime)
    if not dbname or not dbname.endswith("_test"):
        raise SmokeRefused(f"Database '{dbname}' is not disposable: its name must end in _test.")
    if host not in LOOPBACK_HOSTS:
        raise SmokeRefused(f"Host '{host}' is not loopback; smoke checks run only locally.")
    app_env = env.get("APP_ENV") or dotenv.get("APP_ENV") or "development"
    if app_env != "development":
        raise SmokeRefused(f"APP_ENV is '{app_env}'; smoke checks run only in development.")
    if (env.get("SMOKE_CONFIRM_DISPOSABLE") or "") != dbname:
        raise SmokeRefused(f"Set SMOKE_CONFIRM_DISPOSABLE={dbname} to confirm it is disposable.")

    for key in ("DATABASE_URL", "MIGRATION_DATABASE_URL"):
        for source in (env, dotenv):
            configured = (source.get(key) or "").strip()
            if not configured:
                continue
            try:
                configured_target = _target(make_url(configured))
            except Exception:
                raise SmokeRefused(f"Cannot parse {key}; isolation cannot be verified.") from None
            if configured_target == _target(runtime):
                raise SmokeRefused(f"Target is the database configured in {key}; refusing.")
    return runtime, owner


def _single_value(conn: "psycopg.Connection[Any]", sql: str, params: Sequence[Any] = ()) -> Any:
    """First column of a query that always returns exactly one row."""
    row = conn.execute(sql, params).fetchone()
    if row is None:
        raise SmokeRefused("Cannot verify the database (query returned no row).")
    return row[0]


def verify_database_is_disposable(owner_url: URL) -> None:
    """Refuse if the database looks like it holds real accounts."""
    import psycopg

    dsn = owner_url.set(drivername="postgresql").render_as_string(hide_password=False)
    try:
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            if _single_value(conn, "SELECT to_regclass('public.users')") is None:
                raise SmokeRefused("Table 'users' not found: run 'alembic upgrade head' first.")
            clause = " AND ".join(["coalesce(email, '') NOT LIKE %s"] * 3)
            real_staff = _single_value(
                conn,
                f"SELECT count(*) FROM users WHERE is_staff AND {clause}",
                RESERVED_TEST_EMAIL_PATTERNS,
            )
    except psycopg.Error as exc:
        raise SmokeRefused(f"Cannot verify the database ({type(exc).__name__}).") from None
    if real_staff:
        raise SmokeRefused(
            f"{real_staff} staff account(s) outside the reserved test domains: this database may "
            "hold real accounts."
        )


def random_password() -> str:
    """Random password meeting the policy; never printed, logged or stored."""
    return secrets.token_urlsafe(24) + "aA1!"


def random_phone() -> str:
    return "+2507" + "".join(secrets.choice(string.digits) for _ in range(8))


def main() -> int:
    print("==================================================")
    print("IN-PROCESS POSTGRESQL & OPENAPI SMOKE CHECKS")
    print("==================================================")
    dotenv = dotenv_values(BACKEND_ENV)
    # SMOKE_* settings may also live in backend/.env; the shell environment wins.
    env = {k: v for k, v in dotenv.items() if k.startswith("SMOKE_") and v} | dict(os.environ)
    try:
        runtime_url, owner_url = resolve_target(env, dotenv)
        verify_database_is_disposable(owner_url)
    except SmokeRefused as exc:
        print(f"Refusing to run: {exc}", file=sys.stderr)
        return 2

    # Point the app at the disposable database before it is imported. Real environment values
    # win over backend/.env in the app settings, so .env database settings are never used.
    os.environ["DATABASE_URL"] = runtime_url.render_as_string(hide_password=False)
    os.environ["MIGRATION_DATABASE_URL"] = owner_url.render_as_string(hide_password=False)
    os.environ["AUDIT_HMAC_KEY"] = secrets.token_hex(32)
    os.environ["REDIS_URL"] = (
        env.get("SMOKE_REDIS_URL")
        or os.environ.get("TEST_REDIS_URL")
        or "redis://127.0.0.1:6379/15"
    )
    os.environ["APP_ENV"] = "development"
    run_checks(runtime_url.database or "")
    return 0


def run_checks(dbname: str) -> None:
    sys.path.insert(0, str(BACKEND_DIR))

    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, delete, func, select
    from sqlalchemy.orm import sessionmaker

    from app.core.config import get_settings
    from app.core.rate_limit import get_login_rate_limiter
    from app.core.security import hash_password
    from app.db.session import SessionLocal, engine
    from app.integrations.notifications.verification import (
        VerificationMailer,
        get_verification_mailer,
    )
    from app.main import app
    from app.models.identity import Address, StaffRoleAssignment, User
    from app.models.operations import AuditRecord
    from app.models.session import UserSession
    from tests.support.messages import RecordingSender, verification_token

    run = secrets.token_hex(6)

    def account(name: str) -> dict:
        return {
            "email": f"smoke.{run}.{name}@{SMOKE_DOMAIN}",
            "phone": random_phone(),
            "password": random_password(),
        }

    alice, bob = account("alice"), account("bob")
    staff = {
        "administrator": account("admin"),
        "sales": account("sales"),
        "operations": account("ops"),
    }
    run_emails = [a["email"] for a in (alice, bob, *staff.values())]
    run_emails.append(f"smoke.{run}.denied@{SMOKE_DOMAIN}")

    # Fail fast with a clear error if Redis (login rate limiting) is not reachable.
    get_login_rate_limiter().check("smoke-check", None)
    with engine.connect():
        print(f"[1] PostgreSQL Connectivity ({dbname}): PASS")

    # Setup/cleanup use the owner role; the API itself runs as the runtime role.
    owner_engine = create_engine(get_settings().alembic_database_url, hide_parameters=True)
    OwnerSession = sessionmaker(bind=owner_engine, expire_on_commit=False)
    client = TestClient(app)
    # Email verification (2026-11-12): registration with an email sends a link. For this run only,
    # the links go to the tests' in-memory recording sender (nothing is sent anywhere); the
    # customers then verify through the real endpoint, exactly as a customer would.
    mailbox = RecordingSender()
    mailer = VerificationMailer(sender=mailbox, page_url="https://smoke.invalid/verify-email")
    app.dependency_overrides[get_verification_mailer] = lambda: mailer

    def verify(who: dict) -> None:
        token = verification_token(mailbox, who["email"])
        res = client.post("/api/v1/auth/email/verify", json={"token": token})
        assert res.status_code == 200, f"Email verification failed: HTTP {res.status_code}"

    try:
        # 2-3. OpenAPI & Swagger docs
        assert client.get("/docs").status_code == 200, "Swagger UI /docs failed"
        print("[2] Swagger UI /docs endpoint: PASS (HTTP 200)")
        openapi_res = client.get("/api/v1/openapi.json")
        assert openapi_res.status_code == 200, "OpenAPI JSON failed"
        paths = openapi_res.json().get("paths", {})
        required_paths = [
            "/api/v1/auth/register",
            "/api/v1/auth/login",
            "/api/v1/auth/logout",
            "/api/v1/auth/me",
            "/api/v1/customers/me",
            "/api/v1/customers/me/addresses",
            "/api/v1/customers/me/addresses/{address_id}",
            "/api/v1/customers/me/addresses/{address_id}/default",
            "/api/v1/staff",
            "/api/v1/staff/me",
            "/api/v1/staff/me/permissions",
            "/api/v1/staff/{staff_id}",
            "/api/v1/staff/{staff_id}/role",
            "/api/v1/staff/{staff_id}/status",
            "/api/v1/audit-logs",
        ]
        for p in required_paths:
            assert p in paths, f"Missing path in OpenAPI: {p}"
        print(f"[3] OpenAPI Schema Inventory: PASS ({len(paths)} endpoints documented)")

        # 4. Register customer Alice
        reg_alice = client.post("/api/v1/auth/register", json={**alice, "full_name": "Smoke Alice"})
        assert reg_alice.status_code == 201, (
            f"Alice registration failed: HTTP {reg_alice.status_code}"
        )
        alice_id = reg_alice.json()["user"]["id"]
        assert reg_alice.json()["verification_required"] is True
        assert reg_alice.json()["session_token"] is None, "a session before verification"
        unverified = client.post(
            "/api/v1/auth/login",
            json={"identifier": alice["email"], "password": alice["password"]},
        )
        assert unverified.status_code == 403, f"Unverified login: HTTP {unverified.status_code}"
        verify(alice)
        print("[4] Customer Alice Registration: PASS (HTTP 201, email verified through the link)")
        with SessionLocal() as db:
            user_row = db.query(User).filter_by(id=alice_id).first()
            assert user_row is not None, "Alice not found in PostgreSQL"
            assert user_row.email == alice["email"]
            assert user_row.is_staff is False and user_row.staff_roles == []
            assert user_row.email_verified_at is not None, "Alice not verified"
            print("    -> Confirmed Alice persisted in PostgreSQL 'users' table")

        # 5. Register customer Bob, verify, sign in
        reg_bob = client.post("/api/v1/auth/register", json={**bob, "full_name": "Smoke Bob"})
        assert reg_bob.status_code == 201
        assert reg_bob.json()["verification_required"] is True
        verify(bob)
        bob_headers = _login(client, bob)
        print("[5] Customer Bob Registration: PASS (HTTP 201, verified, Bearer token issued)")

        # 6. Customer login
        alice_headers = _login(client, alice)
        alice_token = alice_headers["Authorization"].removeprefix("Bearer ")
        print("[6] Customer Alice Login: PASS (HTTP 200, new session token verified)")

        # 7. Customer profile retrieval & update
        prof_res = client.get("/api/v1/customers/me", headers=alice_headers)
        assert prof_res.status_code == 200
        assert prof_res.json()["full_name"] == "Smoke Alice"
        new_phone = random_phone()
        patch_res = client.patch(
            "/api/v1/customers/me",
            json={"full_name": "Smoke Alice Updated", "phone": new_phone},
            headers=alice_headers,
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["full_name"] == "Smoke Alice Updated"
        with SessionLocal() as db:
            row = db.query(User).filter_by(id=alice_id).one()
            assert (row.full_name, row.phone) == ("Smoke Alice Updated", new_phone)
        print(
            "[7] Customer Profile Retrieval & Update: PASS (HTTP 200, row re-read from PostgreSQL)"
        )

        # 8. Address CRUD & default handling
        addr1_res = client.post(
            "/api/v1/customers/me/addresses",
            json={
                "recipient_name": "Smoke Home",
                "phone": new_phone,
                "district": "Gasabo",
                "sector": "Kimironko",
                "cell": "Bibare",
                "street_address": "KG 11 Ave 42",
                "delivery_instructions": "Black gate",
                "is_default": False,
            },
            headers=alice_headers,
        )
        assert addr1_res.status_code == 201
        addr1 = addr1_res.json()
        addr1_id = addr1["id"]
        assert addr1["is_default"] is True, "First address must be auto-default"
        print("    -> Address 1 created: Auto-default verified")

        addr2_res = client.post(
            "/api/v1/customers/me/addresses",
            json={
                "recipient_name": "Smoke Office",
                "phone": new_phone,
                "district": "Nyarugenge",
                "sector": "Kiyovu",
                "street_address": "KN 3 Ave 10",
                "is_default": True,
            },
            headers=alice_headers,
        )
        assert addr2_res.status_code == 201
        addr2_id = addr2_res.json()["id"]
        assert addr2_res.json()["is_default"] is True
        with SessionLocal() as db:
            assert db.query(Address).filter_by(id=addr1_id).one().is_default is False
            assert db.query(Address).filter_by(id=addr2_id).one().is_default is True
            print("    -> Default consistency verified in PostgreSQL")

        # 9. Cross-customer resource isolation
        url = f"/api/v1/customers/me/addresses/{addr1_id}"
        assert client.get(url, headers=bob_headers).status_code == 404
        assert (
            client.put(url, json={"recipient_name": "Hacked"}, headers=bob_headers).status_code
            == 404
        )
        assert client.delete(url, headers=bob_headers).status_code == 404
        print("[8] Cross-Customer Resource Isolation: PASS (Bob denied access to Alice addresses)")

        # 10. Address deletion & default promotion
        del_res = client.delete(f"/api/v1/customers/me/addresses/{addr2_id}", headers=alice_headers)
        assert del_res.status_code == 200
        with SessionLocal() as db:
            assert db.query(Address).filter_by(id=addr1_id).one().is_default is True
            print(
                "[9] Address Deletion & Promotion: PASS (Addr2 deleted, Addr1 promoted to default)"
            )

        # 11. Staff roles & authorization guards (TC-16). Run-scoped staff with random passwords.
        with OwnerSession() as db:
            for role, who in staff.items():
                user = User(
                    email=who["email"],
                    phone=who["phone"],
                    full_name=f"Smoke {role.title()}",
                    password_hash=hash_password(who["password"]),
                    is_active=True,
                    is_staff=True,
                )
                db.add(user)
                db.flush()
                db.add(StaffRoleAssignment(user_id=user.id, role=role))
            db.commit()
        admin_hdrs = _login(client, staff["administrator"])
        sales_hdrs = _login(client, staff["sales"])
        ops_hdrs = _login(client, staff["operations"])

        for hdrs in (sales_hdrs, ops_hdrs):
            assert client.get("/api/v1/staff", headers=hdrs).status_code == 403
            denied = client.post(
                "/api/v1/staff",
                json={
                    "email": f"smoke.{run}.denied@{SMOKE_DOMAIN}",
                    "full_name": "Denied Admin",
                    "password": random_password(),
                    "role": "administrator",
                },
                headers=hdrs,
            )
            assert denied.status_code == 403, "Sales/Ops must not create staff"
            assert client.get("/api/v1/staff/me", headers=hdrs).status_code == 200
        assert client.get("/api/v1/staff", headers=admin_hdrs).status_code == 200
        assert client.get("/api/v1/staff/me", headers=alice_headers).status_code == 403
        print("[10] Staff authorization: PASS (Sales/Ops blocked from staff administration)")

        # 12. Security audit logs
        audit_res = client.get("/api/v1/audit-logs", headers=admin_hdrs)
        assert audit_res.status_code == 200, "Admin cannot retrieve audit logs"
        assert len(audit_res.json()) > 0, "No audit events recorded"
        assert client.get("/api/v1/audit-logs", headers=alice_headers).status_code == 403
        assert client.get("/api/v1/audit-logs", headers=sales_hdrs).status_code == 403
        with SessionLocal() as db:
            audit_count = db.query(func.count(AuditRecord.id)).scalar()
            print(f"[11] Security Audit Logging: PASS ({audit_count} audit rows in PostgreSQL)")

        # 13. Logout & session invalidation
        assert client.post("/api/v1/auth/logout", headers=alice_headers).status_code == 200
        assert client.get("/api/v1/auth/me", headers=alice_headers).status_code == 401
        with SessionLocal() as db:
            digest = hashlib.sha256(alice_token.encode()).hexdigest()
            sess = db.query(UserSession).filter_by(token_hash=digest).one()
            assert sess.is_active is False and sess.revoked_at is not None
        print(
            "[12] Logout & Session Invalidation: PASS (revoked_at set in PostgreSQL, reuse denied)"
        )
    finally:
        app.dependency_overrides.pop(get_verification_mailer, None)
        # Remove only what this run created (sessions and verification tokens cascade). Audit
        # records are kept.
        with OwnerSession() as db:
            ids = select(User.id).where(User.email.in_(run_emails))
            db.execute(delete(Address).where(Address.user_id.in_(ids)))
            db.execute(delete(StaffRoleAssignment).where(StaffRoleAssignment.user_id.in_(ids)))
            db.execute(delete(User).where(User.email.in_(run_emails)))
            db.commit()
        owner_engine.dispose()
        print("    -> Cleanup: removed only this run's accounts")

    print("==================================================")
    print("ALL 12 IN-PROCESS CHECKS PASSED")
    print("==================================================")


def _login(client, who: dict) -> dict:
    res = client.post(
        "/api/v1/auth/login", json={"identifier": who["email"], "password": who["password"]}
    )
    assert res.status_code == 200, f"Login failed: HTTP {res.status_code}"
    return {"Authorization": f"Bearer {res.json()['session_token']}"}


if __name__ == "__main__":
    sys.exit(main())
