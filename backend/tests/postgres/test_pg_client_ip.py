"""The client IP on real uvicorn processes, started like production with --no-proxy-headers and
CLIENT_IP_SOURCE=signed (ADR-006, 2026-11-13). The test connects from 127.0.0.1, the transport
peer: only a valid, fresh signature can replace it, and no forwarding header ever does."""

import hashlib
import time

from tests.postgres.conftest import Stack
from tests.postgres.test_pg_http import HTTP, PASSWORD, one, register
from tests.support.client_ip import signed_headers

SHOPPER = "203.0.113.25"
WRONG_SECRET = "an-attackers-guess-at-the-secret-000000"
LOGIN = "/api/v1/auth/login"


def login_ip(stack: Stack, phone: str, headers: dict[str, str]) -> str | None:
    """Sign in and return the address stored on the new session."""
    res = HTTP.post(
        f"{stack.servers[0]}/auth/login",
        json={"identifier": phone, "password": PASSWORD},
        headers=headers,
        timeout=30,
    )
    assert res.status_code == 200, res.text
    token_hash = hashlib.sha256(res.json()["session_token"].encode()).hexdigest()
    with stack.owner() as conn:
        return one(conn, "SELECT ip_address FROM user_sessions WHERE token_hash=%s", token_hash)[0]


def test_only_a_valid_fresh_signature_replaces_the_transport_peer(stack: Stack, phone_factory):
    phone = phone_factory()
    register(stack, stack.servers[0], phone=phone)

    assert login_ip(stack, phone, signed_headers(SHOPPER, "POST", LOGIN)) == SHOPPER
    # Everything else is the transport peer: the test runs on this machine.
    assert login_ip(stack, phone, {}) == "127.0.0.1"
    spoofed = {"X-Forwarded-For": SHOPPER, "X-Real-IP": SHOPPER, "Forwarded": f"for={SHOPPER}"}
    assert login_ip(stack, phone, spoofed) == "127.0.0.1"
    assert login_ip(stack, phone, {"X-Sixty-Client-IP": SHOPPER}) == "127.0.0.1"
    forged = signed_headers(SHOPPER, "POST", LOGIN, secret=WRONG_SECRET)
    assert login_ip(stack, phone, forged) == "127.0.0.1"
    stale = signed_headers(SHOPPER, "POST", LOGIN, timestamp=int(time.time()) - 600)
    assert login_ip(stack, phone, stale) == "127.0.0.1"
    elsewhere = signed_headers(SHOPPER, "POST", "/api/v1/auth/register")
    assert login_ip(stack, phone, elsewhere) == "127.0.0.1"
