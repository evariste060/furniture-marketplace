"""Unit rules behind password reset (module 2)."""

import io

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.rate_limit import LoginRateLimiter
from app.core.security import generate_reset_code, hash_reset_code
from app.integrations.notifications import ConsoleProvider, OutboundMessage
from tests.support.memory_rate_limit import FakeClock, MemoryRateLimitStore

KEY = "unit-test-key-0123456789abcdefghijklmnop"


def test_reset_codes_are_six_digits_and_vary():
    generated = {generate_reset_code() for _ in range(200)}
    assert all(len(c) == 6 and c.isdigit() for c in generated)
    assert len(generated) > 150  # random, not a fixed or sequential value


def test_reset_code_hash_is_keyed_and_bound_to_the_user():
    digest = hash_reset_code("user-1", "123456", KEY)
    assert len(digest) == 64 and "123456" not in digest
    assert digest == hash_reset_code("user-1", "123456", KEY)
    assert digest != hash_reset_code("user-2", "123456", KEY)  # another user's code never matches
    assert digest != hash_reset_code("user-1", "123456", KEY + "x")  # needs the server key


def _settings(**overrides) -> Settings:
    base = {
        "database_url": "postgresql+psycopg://x:y@127.0.0.1:1/x",
        "audit_hmac_key": KEY,
        "media_base_url": "https://media.example.rw",  # required outside development (module 7)
        # tests/conftest.py configures the mock payment secret, which production refuses
        "payment_mock_webhook_secret": None,
    }
    return Settings(**{**base, **overrides})


def test_console_provider_is_refused_outside_development():
    assert _settings(app_env="development", notification_provider="console")
    for env in ("staging", "production"):
        with pytest.raises(ValidationError, match="allowed only when APP_ENV=development"):
            _settings(app_env=env, notification_provider="console")
    assert _settings(app_env="production", notification_provider="none")


def test_reset_counters_are_separate_from_login_counters():
    store = MemoryRateLimitStore(FakeClock())
    login = LoginRateLimiter(store, get_settings())
    reset = LoginRateLimiter(store, get_settings(), prefix="reset")
    for _ in range(get_settings().login_max_failures_per_identifier):
        reset.record_failure("ref", "10.0.0.1")
    assert not reset.check("ref", "10.0.0.1").allowed
    assert login.check("ref", "10.0.0.1").allowed


def test_console_sender_prints_the_message_for_local_testing():
    out = io.StringIO()
    message = OutboundMessage("sms", "+250788111222", "Reset code", "Code 123456", "key-1")
    assert ConsoleProvider(out).send(message).startswith("console-")
    printed = out.getvalue()
    assert "[DEV ONLY - not sent] sms to +250788111222" in printed and "Code 123456" in printed
