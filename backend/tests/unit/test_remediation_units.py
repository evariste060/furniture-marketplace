"""Unit regression tests for the 2026-10-21 acceptance-audit corrections."""

import pytest
from starlette.requests import Request

from app.core.config import get_settings
from app.core.identifiers import normalize_login_identifier, validate_email_format
from app.core.rate_limit import LoginRateLimiter
from app.core.request_context import (
    USER_AGENT_MAX_LENGTH,
    build_request_context,
    sanitize_ip_address,
    sanitize_user_agent,
)
from app.core.security import pseudonymize_identifier, validate_password_strength
from app.services.audit_service import (
    MAX_DETAIL_KEYS,
    MAX_DETAIL_STRING,
    identifier_ref,
    sanitize_audit_details,
)
from tests.support.memory_rate_limit import FakeClock, MemoryRateLimitStore


# ---- request metadata ---------------------------------------------------------------------
def test_user_agent_truncated_and_control_chars_removed():
    assert len(sanitize_user_agent("X" * 5000)) == USER_AGENT_MAX_LENGTH
    assert sanitize_user_agent("Mozilla\x00/5.0\r\n\tEvil") == "Mozilla/5.0Evil"
    assert sanitize_user_agent("\x00\x01") is None
    assert sanitize_user_agent(None) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("127.0.0.1", "127.0.0.1"),
        ("::1", "::1"),
        ("2001:0db8:0000:0000:0000:0000:0000:0001", "2001:db8::1"),
        ("not-an-ip", None),
        ("1" * 100, None),
        ("", None),
        (None, None),
    ],
)
def test_ip_address_validated(raw, expected):
    assert sanitize_ip_address(raw) == expected


def test_build_request_context_bounds_headers():
    scope = {
        "type": "http",
        "headers": [(b"user-agent", b"A" * 2000)],
        "client": ("testclient", 123),  # not an IP -> dropped rather than stored
    }
    ctx = build_request_context(Request(scope))
    assert ctx.ip_address is None
    assert len(ctx.user_agent) == USER_AGENT_MAX_LENGTH


# ---- audit details ------------------------------------------------------------------------
def test_audit_details_are_bounded():
    details = {f"k{i}": "v" * 10_000 for i in range(100)}
    details["k0"] = {"a": {"b": {"c": {"d": "deep"}}}}
    details["k1"] = list(range(1000))
    out = sanitize_audit_details(details)
    assert len(out) == MAX_DETAIL_KEYS
    assert all(len(v) <= MAX_DETAIL_STRING for v in out.values() if isinstance(v, str))
    assert out["k0"]["a"]["b"] == "[TRUNCATED]"
    assert len(out["k1"]) == 20


def test_audit_details_lists_kept_as_lists():
    assert sanitize_audit_details({"updated_fields": ["full_name"]}) == {
        "updated_fields": ["full_name"]
    }


def test_identifier_pseudonym_is_keyed_and_stable():
    a = pseudonymize_identifier("user@example.com", "key-one")
    assert a == pseudonymize_identifier("user@example.com", "key-one")
    assert a != pseudonymize_identifier("user@example.com", "key-two")
    assert "user" not in a and len(a) == 64
    assert identifier_ref("user@example.com") == identifier_ref("user@example.com")


# ---- identifiers / validation -------------------------------------------------------------
@pytest.mark.parametrize(
    "raw",
    ["+250788123456", "250788123456", "0788123456", "078 812 3456", "+250-788-123-456"],
)
def test_login_identifier_phone_formats_share_canonical_form(raw):
    assert normalize_login_identifier(raw) == "+250788123456"


@pytest.mark.parametrize(
    "raw", ["0688123456", "788123456", "+25078812345", "+2507881234567", "hello", ""]
)
def test_login_identifier_invalid_formats_rejected(raw):
    with pytest.raises(ValueError):
        normalize_login_identifier(raw)


def test_login_identifier_email_lowercased():
    assert normalize_login_identifier("  User@Example.COM ") == "user@example.com"


def test_email_max_length():
    validate_email_format("a" * 240 + "@example.com")  # 252 chars ok
    with pytest.raises(ValueError):
        validate_email_format("a" * 250 + "@example.com")


def test_password_max_length():
    assert not validate_password_strength("Aa1!" + "x" * 300)[0]


# ---- rate limiter -------------------------------------------------------------------------
@pytest.fixture
def limiter_and_clock():
    clock = FakeClock()
    return LoginRateLimiter(MemoryRateLimitStore(clock), get_settings()), clock


def test_identifier_threshold_then_reset_after_window(limiter_and_clock):
    limiter, clock = limiter_and_clock
    settings = get_settings()
    for _ in range(settings.login_max_failures_per_identifier):
        assert limiter.check("ref", "10.0.0.1").allowed
        limiter.record_failure("ref", "10.0.0.1")
    decision = limiter.check("ref", "10.0.0.1")
    assert not decision.allowed and decision.scope == "identifier"
    assert 0 < decision.retry_after <= settings.login_window_seconds
    clock.advance(settings.login_window_seconds + 1)
    assert limiter.check("ref", "10.0.0.1").allowed  # temporary, never permanent


def test_ip_threshold_across_identifiers(limiter_and_clock):
    limiter, _ = limiter_and_clock
    for i in range(get_settings().login_max_failures_per_ip):
        assert limiter.check(f"ref{i}", "10.0.0.2").allowed
        limiter.record_failure(f"ref{i}", "10.0.0.2")
    decision = limiter.check("fresh-ref", "10.0.0.2")
    assert not decision.allowed and decision.scope == "ip"
    assert limiter.check("fresh-ref", "10.0.0.3").allowed  # other sources unaffected


def test_success_clears_identifier_counter(limiter_and_clock):
    limiter, _ = limiter_and_clock
    for _ in range(get_settings().login_max_failures_per_identifier - 1):
        limiter.record_failure("ref", "10.0.0.4")
    limiter.record_success("ref")
    for _ in range(get_settings().login_max_failures_per_identifier - 1):
        limiter.record_failure("ref", "10.0.0.4")
    assert limiter.check("ref", "10.0.0.4").allowed
