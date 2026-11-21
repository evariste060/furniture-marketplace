"""The client IP used for rate limits, sessions and audit records (ADR-006, 2026-11-13): the
transport peer, unless the storefront's server vouched for the shopper's address with a valid,
fresh HMAC signature. Nothing a caller writes in a header can choose the address otherwise."""

import logging
import time

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from app.core.config import Settings
from app.core.request_context import build_request_context, signed_client_ip
from tests.support.client_ip import NEXT_SECRET, SECRET, signed_client_ips, signed_headers

PEER = "198.51.100.10"
SHOPPER = "203.0.113.25"
PATH = "/api/v1/auth/login"


def request(
    headers: dict[str, str] | list[tuple[str, str]] | None = None,
    *,
    method: str = "POST",
    path: str = PATH,
    peer: str | None = PEER,
) -> Request:
    items = headers.items() if isinstance(headers, dict) else (headers or [])
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "raw_path": path.encode(),
            "root_path": "",
            "query_string": b"",
            "scheme": "https",
            "server": ("api.test", 443),
            "client": (peer, 40000) if peer else None,
            "headers": [(k.lower().encode(), v.encode()) for k, v in items],
        }
    )


def ip_of(headers=None, **kwargs) -> str | None:
    return build_request_context(request(headers, **kwargs)).ip_address


@pytest.fixture
def signed(monkeypatch: pytest.MonkeyPatch):
    with signed_client_ips(monkeypatch, next_secret=NEXT_SECRET):
        yield


# ---- peer mode (local development and direct deployments) -------------------------------------
def test_without_signed_mode_the_peer_is_used_and_every_header_is_ignored() -> None:
    assert ip_of() == PEER
    assert ip_of(signed_headers(SHOPPER, "POST", PATH)) == PEER  # even a valid signature
    assert (
        ip_of({"X-Forwarded-For": SHOPPER, "X-Real-IP": SHOPPER, "Forwarded": f"for={SHOPPER}"})
        == PEER
    )


# ---- signed mode ---------------------------------------------------------------------------------
def test_a_direct_request_without_headers_uses_the_peer(signed) -> None:
    assert ip_of() == PEER
    assert ip_of(peer=None) is None  # no peer at all: the 'unknown' bucket


def test_a_valid_signature_gives_the_shoppers_address(signed) -> None:
    assert ip_of(signed_headers(SHOPPER, "POST", PATH)) == SHOPPER


def test_the_next_secret_is_accepted_during_a_rotation(signed) -> None:
    assert ip_of(signed_headers(SHOPPER, "POST", PATH, secret=NEXT_SECRET)) == SHOPPER


def test_a_signature_from_any_other_secret_falls_back_to_the_peer(signed) -> None:
    forged = signed_headers(SHOPPER, "POST", PATH, secret="an-attackers-guess-at-the-secret-000000")
    assert ip_of(forged) == PEER


@pytest.mark.parametrize(
    "change",
    [
        lambda h: {**h, "X-Sixty-Client-IP": "203.0.113.99"},  # another address, same signature
        lambda h: {
            **h,
            "X-Sixty-Client-IP-Timestamp": str(int(h["X-Sixty-Client-IP-Timestamp"]) + 1),
        },
        lambda h: {**h, "X-Sixty-Client-IP-Signature": h["X-Sixty-Client-IP-Signature"][::-1]},
    ],
)
def test_any_tampering_breaks_the_signature(signed, change) -> None:
    assert ip_of(change(signed_headers(SHOPPER, "POST", PATH))) == PEER


def test_a_signature_is_bound_to_the_method_and_path(signed) -> None:
    headers = signed_headers(SHOPPER, "POST", PATH)
    assert ip_of(headers, method="GET") == PEER
    assert ip_of(headers, path="/api/v1/auth/forgot-password") == PEER


@pytest.mark.parametrize("age", [61, 3600, -61])  # replayed later, or dated in the future
def test_stale_or_future_signatures_fall_back_to_the_peer(signed, age: int) -> None:
    old = signed_headers(SHOPPER, "POST", PATH, timestamp=int(time.time()) - age)
    assert ip_of(old) == PEER


def test_a_signature_inside_the_window_is_accepted(signed) -> None:
    recent = signed_headers(SHOPPER, "POST", PATH, timestamp=int(time.time()) - 50)
    assert ip_of(recent) == SHOPPER


@pytest.mark.parametrize(
    "ip",
    [
        "203.0.113.25, 10.0.0.1",  # a list, as in X-Forwarded-For
        "not-an-ip",
        "",
        "203.0.113.256",
        "1" * 46,  # over the header size limit
    ],
)
def test_only_a_single_valid_address_is_accepted_even_when_signed(signed, ip: str) -> None:
    assert ip_of(signed_headers(ip, "POST", PATH)) == PEER


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Sixty-Client-IP": SHOPPER},  # no signature
        {"X-Sixty-Client-IP": SHOPPER, "X-Sixty-Client-IP-Signature": "a" * 64},  # no timestamp
        {
            "X-Sixty-Client-IP": SHOPPER,
            "X-Sixty-Client-IP-Signature": "A" * 64,
            "X-Sixty-Client-IP-Timestamp": str(int(time.time())),
        },
        {
            "X-Sixty-Client-IP": SHOPPER,
            "X-Sixty-Client-IP-Signature": "a" * 65,
            "X-Sixty-Client-IP-Timestamp": str(int(time.time())),
        },
        {
            "X-Sixty-Client-IP": SHOPPER,
            "X-Sixty-Client-IP-Signature": "a" * 64,
            "X-Sixty-Client-IP-Timestamp": "soon",
        },
        {
            "X-Sixty-Client-IP": SHOPPER,
            "X-Sixty-Client-IP-Signature": "a" * 64,
            "X-Sixty-Client-IP-Timestamp": "1" * 13,
        },
    ],
)
def test_incomplete_or_malformed_headers_fall_back_to_the_peer(signed, headers) -> None:
    assert ip_of(headers) == PEER


def test_repeated_headers_are_refused(signed) -> None:
    good = signed_headers(SHOPPER, "POST", PATH)
    repeated = [*good.items(), ("X-Sixty-Client-IP", "203.0.113.99")]
    assert ip_of(repeated) == PEER


def test_forwarding_headers_never_choose_the_address(signed) -> None:
    spoofed = {
        "X-Forwarded-For": "203.0.113.77",
        "X-Real-IP": "203.0.113.78",
        "Forwarded": "for=203.0.113.79",
    }
    assert ip_of(spoofed) == PEER
    # A valid signature still wins over them, and they do not change it.
    assert ip_of({**signed_headers(SHOPPER, "POST", PATH), **spoofed}) == SHOPPER


def test_ipv6_addresses_are_accepted_and_normalised(signed) -> None:
    assert ip_of(signed_headers("2001:DB8::0001", "POST", PATH)) == "2001:db8::1"


def test_refusals_log_the_reason_only(signed, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    forged = signed_headers(SHOPPER, "POST", PATH, secret="an-attackers-guess-at-the-secret-000000")
    assert signed_client_ip(request(forged)) is None
    assert "bad_signature" in caplog.text
    for secret_part in (SHOPPER, forged["X-Sixty-Client-IP-Signature"], SECRET, NEXT_SECRET):
        assert secret_part not in caplog.text


# ---- settings ------------------------------------------------------------------------------------
BASE = {
    "database_url": "postgresql+psycopg://u:p@127.0.0.1:1/x",
    "audit_hmac_key": "k" * 32,
    "image_public_base_url": "https://img.example.rw/media",
    "client_ip_signing_secret": None,
    "client_ip_signing_secret_next": None,
}


def make(**values: object) -> Settings:
    return Settings(_env_file=None, **{**BASE, "client_ip_source": "peer", **values})  # type: ignore[arg-type,call-arg]


def test_peer_mode_is_the_default_and_needs_no_secret() -> None:
    assert make().client_ip_source == "peer"


@pytest.mark.parametrize(
    "values",
    [
        {"client_ip_source": "signed"},  # no secret
        {"client_ip_source": "signed", "client_ip_signing_secret": ""},
        {"client_ip_source": "signed", "client_ip_signing_secret": "short"},
        {"client_ip_source": "signed", "client_ip_signing_secret": " " + SECRET},
        {
            "client_ip_source": "signed",
            "client_ip_signing_secret": SECRET,
            "client_ip_signing_secret_next": "short",
        },
        {
            "client_ip_source": "signed",
            "client_ip_signing_secret": SECRET,
            "client_ip_signing_secret_next": SECRET,
        },
        {"client_ip_source": "peer", "client_ip_signing_secret": SECRET},  # set but not enabled
    ],
)
def test_signed_mode_refuses_to_start_with_missing_or_invalid_secrets(values) -> None:
    for env in ("development", "production"):
        with pytest.raises(ValidationError) as refused:
            make(app_env=env, payment_mock_webhook_secret=None, **values)
        assert SECRET not in str(refused.value)


def test_signed_mode_with_valid_secrets_starts() -> None:
    settings = make(
        client_ip_source="signed",
        client_ip_signing_secret=SECRET,
        client_ip_signing_secret_next=NEXT_SECRET,
    )
    assert settings.client_ip_signing_secrets == [SECRET, NEXT_SECRET]
    assert make(
        client_ip_source="signed", client_ip_signing_secret=SECRET, client_ip_signing_secret_next=""
    ).client_ip_signing_secrets == [SECRET]


def test_production_warns_when_it_still_uses_the_peer(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.core.config import get_settings
    from app.core.request_context import warn_if_peer_client_ip_in_production

    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "client_ip_source", "peer")
    with caplog.at_level(logging.WARNING):
        warn_if_peer_client_ip_in_production()
    assert "CLIENT_IP_SOURCE=peer with APP_ENV=production" in caplog.text
    caplog.clear()
    monkeypatch.setattr(settings, "client_ip_source", "signed")
    warn_if_peer_client_ip_in_production()
    assert caplog.text == ""


def test_the_storefront_and_the_api_sign_the_same_bytes() -> None:
    """A fixed vector shared with frontend/src/lib/client-ip.test.ts: both sides must produce it."""
    import hashlib
    import hmac

    from app.core.request_context import client_ip_message

    message = client_ip_message("1700000000", "203.0.113.25", "post", "/api/v1/auth/login")
    assert message == b"sixty-client-ip-v1\n1700000000\n203.0.113.25\nPOST\n/api/v1/auth/login"
    assert (
        hmac.new(SECRET.encode(), message, hashlib.sha256).hexdigest()
        == "c7e7cc427d810262e6e6c05349b37d6d0320c23df2e918824f7528581b701280"
    )
