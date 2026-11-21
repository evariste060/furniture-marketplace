"""API regression tests for the 2026-10-21 acceptance-audit defects (SQLite suite).

PostgreSQL-specific behaviour (constraints, triggers, row locks, real Redis, concurrency over
real HTTP) is covered by tests/postgres.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.identity import Address, User
from app.models.operations import AuditRecord
from app.repositories.audit_repository import AuditRepository
from app.services.audit_service import identifier_ref

LOGIN = "/api/v1/auth/login"
ADDR = "/api/v1/customers/me/addresses"
ADDRESS = {
    "recipient_name": "Alice Home",
    "phone": "0788123456",
    "district": "Gasabo",
    "street_address": "KG 11 Ave",
}


def _audit_count(db: Session, action: str) -> int:
    count = db.scalar(select(func.count(AuditRecord.id)).where(AuditRecord.action == action))
    assert count is not None
    return count


# ---- D-02 audit bypass / atomicity --------------------------------------------------------
def test_oversized_user_agent_is_truncated_and_change_audited(
    client: TestClient, customer_auth: dict, db: Session
):
    headers = {**customer_auth["headers"], "User-Agent": "X" * 600}
    res = client.post(ADDR, json=ADDRESS, headers=headers)
    assert res.status_code == 201
    record = db.scalar(select(AuditRecord).where(AuditRecord.action == "address.create"))
    assert record is not None and len(record.change_summary["user_agent"]) == 512


@pytest.mark.parametrize("ua", ["\x00\x01\x02", "Mozilla\r\nInjected: header", "é" * 700])
def test_malformed_user_agent_does_not_break_requests(
    client: TestClient, customer_auth: dict, ua: str
):
    headers = [
        (b"authorization", customer_auth["headers"]["Authorization"].encode()),
        (b"user-agent", ua.encode("utf-8")),
    ]
    assert client.post(ADDR, json=ADDRESS, headers=headers).status_code == 201


def _break_audit(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("simulated audit persistence failure")

    monkeypatch.setattr(AuditRepository, "create", staticmethod(boom))


def test_audit_failure_rolls_back_address_create(
    client: TestClient, customer_auth: dict, db: Session, monkeypatch
):
    _break_audit(monkeypatch)
    with pytest.raises(RuntimeError):
        client.post(ADDR, json=ADDRESS, headers=customer_auth["headers"])
    assert db.scalar(select(func.count(Address.id))) == 0


def test_audit_failure_rolls_back_profile_update(
    client: TestClient, customer_auth: dict, db: Session, monkeypatch
):
    _break_audit(monkeypatch)
    with pytest.raises(RuntimeError):
        client.patch(
            "/api/v1/customers/me",
            json={"full_name": "Changed Silently"},
            headers=customer_auth["headers"],
        )
    db.expire_all()
    user = db.scalar(select(User).where(User.email == "customer.a@example.com"))
    assert user is not None
    assert user.full_name == "Customer Alice"


def test_audit_failure_rolls_back_registration(client: TestClient, db: Session, monkeypatch):
    _break_audit(monkeypatch)
    with pytest.raises(RuntimeError):
        client.post(
            "/api/v1/auth/register",
            json={"email": "x@example.com", "full_name": "X Y", "password": "Str0ngPassw0rd!"},
        )
    assert db.scalar(select(func.count(User.id))) == 0


# ---- D-04 registration validation ---------------------------------------------------------
def test_oversized_email_rejected_with_422(client: TestClient):
    res = client.post(
        "/api/v1/auth/register",
        json={"email": "a" * 250 + "@probe.rw", "full_name": "Long", "password": "Str0ngPassw0rd!"},
    )
    assert res.status_code == 422


def test_oversized_password_rejected_with_422(client: TestClient):
    res = client.post(
        "/api/v1/auth/register",
        json={"email": "p@example.com", "full_name": "Long", "password": "Aa1!" + "x" * 300},
    )
    assert res.status_code == 422


def test_public_registration_ignores_role_and_status(client: TestClient, db: Session):
    res = client.post(
        "/api/v1/auth/register",
        json={
            "email": "escalate@example.com",
            "full_name": "Escalate",
            "password": "Str0ngPassw0rd!",
            "role": "admin",
            "is_active": False,
        },
    )
    assert res.status_code == 201
    user = db.scalar(select(User).where(User.email == "escalate@example.com"))
    assert user is not None
    assert (user.is_staff, user.is_active) == (False, True)
    assert user.staff_roles == []


# ---- D-05 phone normalisation -------------------------------------------------------------
@pytest.mark.parametrize("identifier", ["+250788111222", "250788111222", "0788111222"])
def test_login_accepts_every_approved_phone_format(
    client: TestClient, customer_auth: dict, identifier: str
):
    res = client.post(LOGIN, json={"identifier": identifier, "password": "SecurePassword123!"})
    assert res.status_code == 200


def test_login_rejects_invalid_identifier_format(client: TestClient):
    res = client.post(LOGIN, json={"identifier": "12345", "password": "whatever"})
    assert res.status_code == 422


# ---- D-01 rate limiting -------------------------------------------------------------------
def _fail(client: TestClient, identifier: str):
    return client.post(LOGIN, json={"identifier": identifier, "password": "Wrong!pass1"})


def test_login_blocked_after_threshold_then_allowed_after_window(
    client: TestClient, customer_auth: dict, clock
):
    limit = get_settings().login_max_failures_per_identifier
    assert [_fail(client, "customer.a@example.com").status_code for _ in range(limit)] == [
        401
    ] * limit
    blocked = client.post(
        LOGIN, json={"identifier": "customer.a@example.com", "password": "SecurePassword123!"}
    )
    assert blocked.status_code == 429
    assert 0 < int(blocked.headers["Retry-After"]) <= get_settings().login_window_seconds
    clock.advance(get_settings().login_window_seconds + 1)
    ok = client.post(
        LOGIN, json={"identifier": "customer.a@example.com", "password": "SecurePassword123!"}
    )
    assert ok.status_code == 200


def test_rate_limit_identical_for_unknown_accounts(client: TestClient, customer_auth: dict):
    """No enumeration: unknown identifiers are limited and answered exactly like real ones."""
    limit = get_settings().login_max_failures_per_identifier
    real = [_fail(client, "customer.a@example.com") for _ in range(limit + 1)]
    fake = [_fail(client, "nobody@example.com") for _ in range(limit + 1)]
    assert [r.status_code for r in real] == [r.status_code for r in fake]
    assert real[0].json() == fake[0].json() and real[-1].json() == fake[-1].json()


def test_phone_formats_share_one_rate_limit_bucket(client: TestClient, customer_auth: dict):
    limit = get_settings().login_max_failures_per_identifier
    formats = ["+250788111222", "0788111222", "250788111222"]
    for i in range(limit):
        assert _fail(client, formats[i % 3]).status_code == 401
    assert _fail(client, "0788111222").status_code == 429


def test_successful_login_resets_identifier_counter(client: TestClient, customer_auth: dict):
    limit = get_settings().login_max_failures_per_identifier
    for _ in range(limit - 1):
        _fail(client, "customer.a@example.com")
    good = {"identifier": "customer.a@example.com", "password": "SecurePassword123!"}
    assert client.post(LOGIN, json=good).status_code == 200
    for _ in range(limit - 1):
        assert _fail(client, "customer.a@example.com").status_code == 401


def test_rate_limited_attempt_is_audited(client: TestClient, customer_auth: dict, db: Session):
    for _ in range(get_settings().login_max_failures_per_identifier + 1):
        _fail(client, "customer.a@example.com")
    record = db.scalar(
        select(AuditRecord).where(AuditRecord.change_summary["status"].astext == "rate_limited")
    )
    assert record is not None and record.change_summary["scope"] == "identifier"


# ---- D-09 audit data minimisation ---------------------------------------------------------
def test_failed_login_audit_is_pseudonymised(client: TestClient, customer_auth: dict, db: Session):
    _fail(client, "Customer.A@example.com")
    record = db.scalar(
        select(AuditRecord).where(
            AuditRecord.action == "auth.login",
            AuditRecord.change_summary["status"].astext == "failure",
        )
    )
    assert record is not None
    assert "customer.a@example.com" not in str(record.change_summary).lower()
    assert record.entity_type == "login_identifier"
    assert record.entity_id == identifier_ref("customer.a@example.com")


def test_duplicate_registration_audit_is_pseudonymised(
    client: TestClient, customer_auth: dict, db: Session
):
    client.post(
        "/api/v1/auth/register",
        json={"email": "customer.a@example.com", "full_name": "Dup", "password": "Str0ngPassw0rd!"},
    )
    record = db.scalar(
        select(AuditRecord).where(
            AuditRecord.action == "auth.register",
            AuditRecord.change_summary["status"].astext == "failure",
        )
    )
    assert record is not None
    assert "customer.a@example.com" not in str(record.change_summary)
    assert record.change_summary["reason"] == "duplicate_email"


# ---- D-03 default-address rules -----------------------------------------------------------
def test_first_address_default_and_unsetting_default_rejected(
    client: TestClient, customer_auth: dict
):
    h = customer_auth["headers"]
    first = client.post(ADDR, json={**ADDRESS, "is_default": False}, headers=h).json()
    assert first["is_default"] is True
    res = client.put(f"{ADDR}/{first['id']}", json={"is_default": False}, headers=h)
    assert res.status_code == 422
    assert client.get(f"{ADDR}/{first['id']}", headers=h).json()["is_default"] is True


def test_replacement_and_deletion_keep_exactly_one_default(
    client: TestClient, customer_auth: dict, db: Session
):
    h = customer_auth["headers"]
    a = client.post(ADDR, json=ADDRESS, headers=h).json()
    b = client.post(ADDR, json={**ADDRESS, "recipient_name": "Bee"}, headers=h).json()
    c = client.post(ADDR, json={**ADDRESS, "recipient_name": "Cee"}, headers=h).json()
    assert [a["is_default"], b["is_default"], c["is_default"]] == [True, False, False]

    # Replacement via PUT is_default=true
    assert client.put(f"{ADDR}/{b['id']}", json={"is_default": True}, headers=h).status_code == 200
    # is_default=false on a non-default address is a harmless no-op
    assert client.put(f"{ADDR}/{a['id']}", json={"is_default": False}, headers=h).status_code == 200
    defaults = [x["id"] for x in client.get(ADDR, headers=h).json() if x["is_default"]]
    assert defaults == [b["id"]]

    # Deleting the default promotes the newest remaining address (c)
    assert client.delete(f"{ADDR}/{b['id']}", headers=h).status_code == 200
    defaults = [x["id"] for x in client.get(ADDR, headers=h).json() if x["is_default"]]
    assert defaults == [c["id"]]

    # Deleting a non-default address leaves the default alone
    client.delete(f"{ADDR}/{a['id']}", headers=h)
    defaults = [x["id"] for x in client.get(ADDR, headers=h).json() if x["is_default"]]
    assert defaults == [c["id"]]

    # Deleting the last address leaves none
    client.delete(f"{ADDR}/{c['id']}", headers=h)
    assert client.get(ADDR, headers=h).json() == []


# ---- Phase 3 authorization boundaries -----------------------------------------------------
def test_customers_are_denied_admin_paths(client: TestClient, customer_auth: dict):
    h = customer_auth["headers"]
    assert client.get("/api/v1/audit-logs", headers=h).status_code == 403
    assert client.get("/api/v1/staff", headers=h).status_code == 403


def test_inactive_account_token_and_login_refused(
    client: TestClient, customer_auth: dict, db: Session
):
    user = db.scalar(select(User).where(User.email == "customer.a@example.com"))
    assert user is not None
    user.is_active = False
    db.commit()
    assert client.get("/api/v1/customers/me", headers=customer_auth["headers"]).status_code == 403
    res = client.post(
        LOGIN, json={"identifier": "customer.a@example.com", "password": "SecurePassword123!"}
    )
    assert res.status_code == 403


def test_logout_atomic_with_audit(client: TestClient, customer_auth: dict, db: Session):
    assert client.post("/api/v1/auth/logout", headers=customer_auth["headers"]).status_code == 200
    assert _audit_count(db, "auth.logout") == 1
    assert client.get("/api/v1/auth/me", headers=customer_auth["headers"]).status_code == 401


def test_login_fails_closed_when_rate_limit_store_unavailable(
    client: TestClient, customer_auth: dict
):
    from app.core.rate_limit import (
        LoginRateLimiter,
        RateLimitStoreUnavailable,
        get_login_rate_limiter,
    )
    from app.main import app

    class DownStore:
        def get(self, key: str) -> tuple[int, int]:
            raise RateLimitStoreUnavailable

        def hit(self, key: str, window_seconds: int) -> tuple[int, int]:
            raise RateLimitStoreUnavailable

        def reset(self, key: str) -> None:
            raise RateLimitStoreUnavailable

    app.dependency_overrides[get_login_rate_limiter] = lambda: LoginRateLimiter(
        DownStore(), get_settings()
    )
    res = client.post(
        LOGIN, json={"identifier": "customer.a@example.com", "password": "SecurePassword123!"}
    )
    assert res.status_code == 503
    assert "session_token" not in res.text
