"""Payment provider rules without a database (module 15; §7 Q21)."""

import json
import os
import time

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.integrations.payments import (
    METHOD_PROVIDERS,
    InvalidWebhook,
    MalformedWebhook,
    WebhookRequest,
    get_provider,
)
from app.integrations.payments.mock import MockProvider, mask_phone, sign

SECRET = os.environ["PAYMENT_MOCK_WEBHOOK_SECRET"]


def request(body: dict | bytes, *, secret: str = SECRET, ts: int | None = None) -> WebhookRequest:
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    stamp = ts if ts is not None else int(time.time())
    return WebhookRequest(
        headers={"x-mock-timestamp": str(stamp), "x-mock-signature": sign(raw, stamp, secret)},
        body=raw,
    )


GOOD = {
    "event_id": "evt-000001",
    "reference": "MOCK-ABCDEF",
    "status": "succeeded",
    "amount": 1500,
    "currency": "RWF",
}


def test_methods_map_to_the_approved_providers_and_card_stays_disabled():
    assert METHOD_PROVIDERS == {
        "mtn_momo": "mock",
        "airtel_money": "mock",
        "cash_on_delivery": "cod",
    }
    assert "card" not in METHOD_PROVIDERS  # §7 Q21
    assert get_provider("stripe") is None


def test_the_mock_verifies_hmac_signatures_and_freshness():
    provider = MockProvider()
    provider.verify_webhook(request(GOOD))
    for bad in (
        request(GOOD, secret="wrong-secret-" * 3),
        request(GOOD, ts=int(time.time()) - 10_000),
        WebhookRequest(headers={}, body=b"{}"),
        WebhookRequest(
            headers={"x-mock-timestamp": "abc", "x-mock-signature": "sha256=00"}, body=b"{}"
        ),
    ):
        with pytest.raises(InvalidWebhook):
            provider.verify_webhook(bad)
    signed = request(GOOD)
    tampered = WebhookRequest(headers=signed.headers, body=signed.body.replace(b"1500", b"1"))
    with pytest.raises(InvalidWebhook):
        provider.verify_webhook(tampered)


@pytest.mark.parametrize(
    "change",
    [
        {"event_id": "x"},
        {"reference": "bad ref with spaces"},
        {"status": "refunded"},
        {"status": ["succeeded"]},
        {"status": {"value": "succeeded"}},
        {"status": 1},
        {"status": None},
        {"amount": -1},
        {"amount": "1500"},
        {"amount": True},
        {"currency": "rwf"},
    ],
)
def test_the_mock_refuses_malformed_events(change):
    with pytest.raises(MalformedWebhook):
        MockProvider().parse_event(request({**GOOD, **change}))


def test_parsed_events_keep_only_allow_listed_facts():
    parsed = MockProvider().parse_event(
        request({**GOOD, "payer_phone": "0788 123 456", "card_number": "4111", "pin": "1234"})
    )
    assert parsed.event_key == "evt-000001" and parsed.status == "succeeded"
    assert parsed.metadata == {
        "event_type": "succeeded",
        "reference": "MOCK-ABCDEF",
        "amount": 1500,
        "currency": "RWF",
        "payer_phone_masked": "+250******456",  # canonical first, then masked
    }
    assert mask_phone("+250788123456") == "+250******456"
    assert mask_phone("12") is None and mask_phone(None) is None


@pytest.mark.parametrize(
    ("reason", "stored"),
    [
        ("timeout", "timeout"),
        ("Payer jane@example.rw 0788123456", "other"),
        (["declined"], "other"),
        (None, "other"),
    ],
)
def test_only_allow_listed_reason_codes_reach_the_metadata(reason, stored):
    parsed = MockProvider().parse_event(request({**GOOD, "status": "failed", "reason": reason}))
    assert parsed.metadata["reason"] == stored
    assert "jane" not in str(parsed.metadata) and "788123456" not in str(parsed.metadata)


def test_the_mock_secret_is_required_long_and_never_in_production():
    with pytest.raises(ValueError, match="production"):
        Settings(
            app_env="production",
            media_base_url="https://m.example.rw",
            payment_mock_webhook_secret=SecretStr("x" * 40),
        )
    with pytest.raises(ValueError, match="32"):
        Settings(payment_mock_webhook_secret=SecretStr("short"))
    assert (
        Settings(payment_mock_webhook_secret=SecretStr("")).payment_mock_webhook_secret is not None
    )
