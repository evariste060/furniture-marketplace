"""Signed client IPs through the API (ADR-006, 2026-11-13): per-IP rate limits isolate customers
the storefront vouches for, callers cannot escape a limit by inventing addresses, and sessions and
audit records keep the verified address."""

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.operations import AuditRecord
from app.models.session import UserSession
from tests.support.client_ip import signed_client_ips, signed_headers

LOGIN = "/api/v1/auth/login"
ALICE_IP = "203.0.113.10"
BOB_IP = "203.0.113.20"


@pytest.fixture(autouse=True)
def signed(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    # After `client`: its database setup (pg_engine) replaces the cached settings, so patching
    # them earlier would leave the API in peer mode.
    with signed_client_ips(monkeypatch):
        yield


def fail_login(client: TestClient, n: int, headers: dict[str, str] | None = None):
    """A failed login for a new unknown identifier each time, so only the per-IP limit applies."""
    return client.post(
        LOGIN,
        json={"identifier": f"nobody.{n}.{time.monotonic_ns()}@example.com", "password": "x" * 8},
        headers=headers or {},
    )


def as_ip(ip: str) -> dict[str, str]:
    return signed_headers(ip, "POST", LOGIN)


def test_customers_with_different_addresses_have_separate_limits(client: TestClient) -> None:
    limit = get_settings().login_max_failures_per_ip
    for n in range(limit):
        assert fail_login(client, n, as_ip(ALICE_IP)).status_code == 401
    blocked = fail_login(client, 999, as_ip(ALICE_IP))
    assert blocked.status_code == 429 and blocked.json()["error"]["code"] == "rate_limited"
    # Bob, at his own address, is not affected by Alice's failures.
    assert fail_login(client, 1000, as_ip(BOB_IP)).status_code == 401


def test_requests_from_one_customer_share_one_limit(client: TestClient) -> None:
    limit = get_settings().login_max_failures_per_ip
    for n in range(limit):
        fail_login(client, n, as_ip(ALICE_IP))
    assert fail_login(client, 500, as_ip(ALICE_IP)).status_code == 429
    assert fail_login(client, 501, as_ip(ALICE_IP)).status_code == 429


@pytest.mark.parametrize(
    "spoof",
    [
        lambda n: {"X-Forwarded-For": f"198.18.0.{n}", "X-Real-IP": f"198.18.1.{n}"},
        lambda n: {"X-Sixty-Client-IP": f"198.18.2.{n}"},  # no signature
        lambda n: signed_headers(
            f"198.18.3.{n}", "POST", LOGIN, secret="an-attackers-guess-at-the-secret-000000"
        ),
        lambda n: signed_headers(f"198.18.4.{n}", "POST", LOGIN, timestamp=int(time.time()) - 600),
    ],
)
def test_inventing_addresses_does_not_escape_the_limit(client: TestClient, spoof) -> None:
    """A caller rotating forwarding headers or unverifiable signatures stays in the transport
    peer's bucket, so it reaches the limit like any other single client."""
    limit = get_settings().login_max_failures_per_ip
    for n in range(limit):
        assert fail_login(client, n, spoof(n)).status_code == 401
    assert fail_login(client, 999, spoof(200)).status_code == 429
    # A customer the storefront vouches for is unaffected.
    assert fail_login(client, 1000, as_ip(BOB_IP)).status_code == 401


def test_a_replayed_signature_on_another_endpoint_is_not_accepted(
    client: TestClient, db: Session
) -> None:
    headers = signed_headers(ALICE_IP, "POST", "/api/v1/auth/forgot-password")
    fail_login(client, 1, headers)  # signed for another path
    db.expire_all()
    [record] = db.scalars(select(AuditRecord).where(AuditRecord.action == "auth.login")).all()
    assert record.change_summary.get("ip_address") != ALICE_IP


def test_sessions_and_audit_records_keep_the_verified_address(
    client: TestClient, db: Session, customer_auth: dict
) -> None:
    res = client.post(
        LOGIN,
        json={"identifier": "customer.a@example.com", "password": "SecurePassword123!"},
        headers=as_ip(ALICE_IP),
    )
    assert res.status_code == 200, res.text
    db.expire_all()
    newest = db.scalars(select(UserSession).order_by(UserSession.created_at.desc())).first()
    assert newest is not None and newest.ip_address == ALICE_IP
    logins = db.scalars(
        select(AuditRecord)
        .where(AuditRecord.action == "auth.login")
        .order_by(AuditRecord.created_at.desc())
    ).all()
    assert logins[0].change_summary["ip_address"] == ALICE_IP


def test_unverified_headers_are_never_stored(
    client: TestClient, db: Session, customer_auth: dict
) -> None:
    res = client.post(
        LOGIN,
        json={"identifier": "customer.a@example.com", "password": "SecurePassword123!"},
        headers={"X-Forwarded-For": ALICE_IP, "X-Sixty-Client-IP": ALICE_IP},
    )
    assert res.status_code == 200
    db.expire_all()
    newest = db.scalars(select(UserSession).order_by(UserSession.created_at.desc())).first()
    assert newest is not None and newest.ip_address != ALICE_IP
    stored = [r.change_summary.get("ip_address") for r in db.scalars(select(AuditRecord))]
    assert ALICE_IP not in stored
