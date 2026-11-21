"""Signed client-IP headers for tests: what the storefront's server sends (ADR-006, 2026-11-13).

The signing mirrors frontend/src/lib/client-ip.ts; app.core.request_context verifies it.
"""

import hashlib
import hmac
import time
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from app.core.config import get_settings
from app.core.request_context import client_ip_message

SECRET = "test-only-client-ip-signing-secret-0123456789"
NEXT_SECRET = "test-only-next-client-ip-signing-secret-98765"


def signed_headers(
    ip: str,
    method: str,
    path: str,
    *,
    secret: str = SECRET,
    timestamp: int | None = None,
) -> dict[str, str]:
    ts = str(int(time.time()) if timestamp is None else timestamp)
    signature = hmac.new(
        secret.encode(), client_ip_message(ts, ip, method, path), hashlib.sha256
    ).hexdigest()
    return {
        "X-Sixty-Client-IP": ip,
        "X-Sixty-Client-IP-Signature": signature,
        "X-Sixty-Client-IP-Timestamp": ts,
    }


@contextmanager
def signed_client_ips(
    monkeypatch: pytest.MonkeyPatch, *, secret: str = SECRET, next_secret: str | None = None
) -> Iterator[None]:
    """CLIENT_IP_SOURCE=signed on the cached settings for one test. Use it after any fixture
    that clears the settings cache (pg_engine, and so client and db), or the API keeps the
    earlier settings."""
    from pydantic import SecretStr

    settings = get_settings()
    monkeypatch.setattr(settings, "client_ip_source", "signed")
    monkeypatch.setattr(settings, "client_ip_signing_secret", SecretStr(secret))
    monkeypatch.setattr(
        settings, "client_ip_signing_secret_next", SecretStr(next_secret) if next_secret else None
    )
    yield
